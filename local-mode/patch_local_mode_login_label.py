"""Precisely rename the original login screen's visitor button in its prefab.

This module only transforms two Unity AssetBundle byte strings. It neither
repackages an APK nor changes the Android bridge or either server endpoint.
The caller must put both bundles into the APK and update m.assets_list.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zipfile
from pathlib import Path

import UnityPy


SOURCE_APK = Path(
    r"D:\Project\魔女兵器在线版\android-client\build\witchweapon-stardust-skip-v106-test.apk"
)
SOURCE_APK_SHA256 = "81a609fc57fd68db934cfb58d672e0716fb8eb86a6fe22d62744a9c485f08271"
LOGIN_PREFAB = "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab"
LOGIN_PREFAB_SHA256 = "39a465c50277a615d74883a18936be47034c2112711ae6838e4b7b4fe20b2812"
LOGIN_SCENE = "assets/assetbundle/scene/loginfromal.ab"
LOGIN_SCENE_SHA256 = "10dafba6fe685e317ab55ed956a714bb2a8f2db3b1d89645bf50ae4940cbfd79"
LOGIN_BUNDLES = {LOGIN_PREFAB: LOGIN_PREFAB_SHA256,
                 LOGIN_SCENE: LOGIN_SCENE_SHA256}
ASSET_INDEX = "assets/m.assets_list.txt"
ASSET_INDEX_SHA256 = "ad7227416f76c3689bb54412b80b9e763d5843fbc9afe06e0542ef0c0d11da37"

# These IDs are from the reviewed v106 prefab, not a name search across the UI.
ENTRY_VIEW_GAME_OBJECT = -1932461559518643629
ENTRY_VIEW_COMPONENT = 2782934152693128823
VISITOR_BUTTON_COMPONENT = 2080513491140642746
VISITOR_BUTTON_GAME_OBJECT = 1014635688734296921
VISITOR_BUTTON_TRANSFORM = -2506326525682881863
VISITOR_LABEL_GAME_OBJECT = -6122528199120936120
VISITOR_LABEL_TRANSFORM = 4262454970153816973
VISITOR_LABEL_COMPONENT = -5276754001437707263

OLD_TEXT = "游客"
NEW_TEXT = "本地模式"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_reviewed_bundles(apk_path: Path = SOURCE_APK) -> dict[str, bytes]:
    """Read both reviewed login bundles from the exact, unchanged v106 APK."""
    if not apk_path.is_file() or digest_file(apk_path) != SOURCE_APK_SHA256:
        raise ValueError("The reviewed v106 APK is absent or changed")
    with zipfile.ZipFile(apk_path) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK member")
        result = {member: apk.read(member) for member in LOGIN_BUNDLES}
    for member, expected in LOGIN_BUNDLES.items():
        if digest(result[member]) != expected:
            raise ValueError("The reviewed login bundle is changed: " + member)
    return result


def read_reviewed_assets(apk_path: Path = SOURCE_APK) -> dict[str, bytes]:
    """Read the two bundles and their index with one source APK hash check."""
    if not apk_path.is_file() or digest_file(apk_path) != SOURCE_APK_SHA256:
        raise ValueError("The reviewed v106 APK is absent or changed")
    with zipfile.ZipFile(apk_path) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK member")
        result = {member: apk.read(member) for member in (*LOGIN_BUNDLES, ASSET_INDEX)}
    for member, expected in (*LOGIN_BUNDLES.items(), (ASSET_INDEX, ASSET_INDEX_SHA256)):
        if digest(result[member]) != expected:
            raise ValueError("The reviewed login asset is changed: " + member)
    return result


def _pointer(tree: dict, name: str) -> int:
    value = tree[name]
    if value["m_FileID"] != 0:
        raise ValueError("Unexpected external Unity object reference")
    return value["m_PathID"]


def _component_ids(game_object: dict) -> set[int]:
    return {_pointer(entry, "component") for entry in game_object["m_Component"]}


def _replace_serialized_text(raw: bytes) -> bytes:
    """Change only the serialized mText length and UTF-8 bytes."""
    old = OLD_TEXT.encode("utf-8")
    new = NEW_TEXT.encode("utf-8")
    if raw.count(old) != 1:
        raise ValueError("Expected one original visitor label in its component")
    offset = raw.index(old)
    if offset < 4 or struct.unpack_from("<I", raw, offset - 4)[0] != len(old):
        raise ValueError("Visitor label does not have the reviewed string layout")
    old_padding = (-len(old)) % 4
    old_end = offset + len(old) + old_padding
    if raw[offset + len(old):old_end] != b"\0" * old_padding:
        raise ValueError("Unexpected visitor label padding")
    new_padding = (-len(new)) % 4
    return (raw[:offset - 4] + struct.pack("<I", len(new)) + new
            + b"\0" * new_padding + raw[old_end:])


def patch_login_prefab(raw: bytes) -> bytes:
    """Return a prefab whose EntryOptionView visitor button reads 本地模式.

    Rejects other prefab versions and verifies that exactly one serialized
    object changes, with no non-text bytes changed inside that object.
    """
    if digest(raw) != LOGIN_PREFAB_SHA256:
        raise ValueError("Input is not the reviewed v106 login prefab")
    bundle = UnityPy.load(raw)
    objects = {obj.path_id: obj for obj in bundle.objects}
    if len(objects) != len(bundle.objects) or len(objects) != 4704:
        raise ValueError("Login prefab object inventory changed")
    required = (ENTRY_VIEW_GAME_OBJECT, ENTRY_VIEW_COMPONENT,
                VISITOR_BUTTON_COMPONENT, VISITOR_BUTTON_GAME_OBJECT,
                VISITOR_BUTTON_TRANSFORM, VISITOR_LABEL_GAME_OBJECT,
                VISITOR_LABEL_TRANSFORM, VISITOR_LABEL_COMPONENT)
    if not set(required).issubset(objects):
        raise ValueError("Login prefab visitor object path changed")

    entry_go = objects[ENTRY_VIEW_GAME_OBJECT].read_typetree()
    entry = objects[ENTRY_VIEW_COMPONENT].read_typetree()
    button = objects[VISITOR_BUTTON_COMPONENT].read_typetree()
    button_go = objects[VISITOR_BUTTON_GAME_OBJECT].read_typetree()
    button_transform = objects[VISITOR_BUTTON_TRANSFORM].read_typetree()
    label_go = objects[VISITOR_LABEL_GAME_OBJECT].read_typetree()
    label_transform = objects[VISITOR_LABEL_TRANSFORM].read_typetree()
    label = objects[VISITOR_LABEL_COMPONENT].read_typetree()
    if (entry_go["m_Name"] != "EntryOptionView"
            or ENTRY_VIEW_COMPONENT not in _component_ids(entry_go)
            or _pointer(entry, "m_GameObject") != ENTRY_VIEW_GAME_OBJECT
            or _pointer(entry, "VisitorBtn") != VISITOR_BUTTON_COMPONENT
            or _pointer(button, "m_GameObject") != VISITOR_BUTTON_GAME_OBJECT
            or button_go["m_Name"] != "RegistBtn"
            or {VISITOR_BUTTON_COMPONENT, VISITOR_BUTTON_TRANSFORM}
               - _component_ids(button_go)
            or _pointer(button_transform, "m_GameObject") != VISITOR_BUTTON_GAME_OBJECT
            or {child["m_PathID"] for child in button_transform["m_Children"]}
               != {-6319718257938724053, VISITOR_LABEL_TRANSFORM}
            or label_go["m_Name"] != "Label"
            or {VISITOR_LABEL_COMPONENT, VISITOR_LABEL_TRANSFORM}
               - _component_ids(label_go)
            or _pointer(label_transform, "m_GameObject") != VISITOR_LABEL_GAME_OBJECT
            or _pointer(label_transform, "m_Father") != VISITOR_BUTTON_TRANSFORM
            or _pointer(label, "m_GameObject") != VISITOR_LABEL_GAME_OBJECT
            or label["mText"] != OLD_TEXT):
        raise ValueError("Reviewed visitor button and label wiring changed")

    before = {path_id: digest(obj.get_raw_data()) for path_id, obj in objects.items()}
    old_object = objects[VISITOR_LABEL_COMPONENT].get_raw_data()
    new_object = _replace_serialized_text(old_object)
    objects[VISITOR_LABEL_COMPONENT].set_raw_data(new_object)
    result = bundle.file.save(packer="original")

    verified = UnityPy.load(result)
    after = {obj.path_id: obj for obj in verified.objects}
    if set(after) != set(objects):
        raise ValueError("Patched prefab object inventory changed")
    changed = {path_id for path_id, obj in after.items()
               if digest(obj.get_raw_data()) != before[path_id]}
    if changed != {VISITOR_LABEL_COMPONENT}:
        raise ValueError("Patched prefab changed unrelated Unity objects")
    if (after[VISITOR_LABEL_COMPONENT].get_raw_data() != new_object
            or after[VISITOR_LABEL_COMPONENT].read_typetree()["mText"] != NEW_TEXT):
        raise ValueError("Patched visitor label did not round-trip")
    return result


def patch_login_scene(raw: bytes) -> bytes:
    """Rename the matching visitor button in the original login scene."""
    if digest(raw) != LOGIN_SCENE_SHA256:
        raise ValueError("Input is not the reviewed v106 login scene")
    bundle = UnityPy.load(raw)
    if set(bundle.file.files) != {"BuildPlayer-LoginFromal.sharedAssets",
                                  "BuildPlayer-LoginFromal"}:
        raise ValueError("Login scene serialized-file inventory changed")
    objects = bundle.file.files["BuildPlayer-LoginFromal"].objects
    if len(objects) != 4649 or len(bundle.file.files[
            "BuildPlayer-LoginFromal.sharedAssets"].objects) != 82:
        raise ValueError("Login scene object inventory changed")
    required = (1068, 4303, 3429, 413, 1676, 1178, 2441, 4442)
    if not set(required).issubset(objects):
        raise ValueError("Login scene visitor object path changed")
    entry_go = objects[1068].read_typetree()
    entry = objects[4303].read_typetree()
    button = objects[3429].read_typetree()
    button_go = objects[413].read_typetree()
    button_transform = objects[1676].read_typetree()
    label_go = objects[1178].read_typetree()
    label_transform = objects[2441].read_typetree()
    label = objects[4442].read_typetree()
    if (entry_go["m_Name"] != "EntryOptionView"
            or 4303 not in _component_ids(entry_go)
            or _pointer(entry, "m_GameObject") != 1068
            or _pointer(entry, "VisitorBtn") != 3429
            or _pointer(button, "m_GameObject") != 413
            or button_go["m_Name"] != "RegistBtn"
            or {1676, 3429} - _component_ids(button_go)
            or _pointer(button_transform, "m_GameObject") != 413
            or {child["m_PathID"] for child in button_transform["m_Children"]}
               != {1950, 2441}
            or label_go["m_Name"] != "Label"
            or {2441, 4442} - _component_ids(label_go)
            or _pointer(label_transform, "m_GameObject") != 1178
            or _pointer(label_transform, "m_Father") != 1676
            or _pointer(label, "m_GameObject") != 1178
            or label["mText"] != OLD_TEXT):
        raise ValueError("Reviewed scene visitor button and label wiring changed")

    before = {(obj.assets_file.name, obj.path_id): digest(obj.get_raw_data())
              for obj in bundle.objects}
    new_object = _replace_serialized_text(objects[4442].get_raw_data())
    objects[4442].set_raw_data(new_object)
    result = bundle.file.save(packer="original")

    verified = UnityPy.load(result)
    after = {(obj.assets_file.name, obj.path_id): obj for obj in verified.objects}
    if set(after) != set(before):
        raise ValueError("Patched scene object inventory changed")
    changed = {key for key, obj in after.items()
               if digest(obj.get_raw_data()) != before[key]}
    target_key = ("BuildPlayer-LoginFromal", 4442)
    if changed != {target_key}:
        raise ValueError("Patched scene changed unrelated Unity objects")
    if (after[target_key].get_raw_data() != new_object
            or after[target_key].read_typetree()["mText"] != NEW_TEXT):
        raise ValueError("Patched scene visitor label did not round-trip")
    return result


def patch_login_resources(source: dict[str, bytes]) -> dict[str, bytes]:
    """Return exactly two APK member replacements, ready for index updating."""
    if set(source) != set(LOGIN_BUNDLES):
        raise ValueError("Both reviewed login bundles are required")
    return {LOGIN_PREFAB: patch_login_prefab(source[LOGIN_PREFAB]),
            LOGIN_SCENE: patch_login_scene(source[LOGIN_SCENE])}


def patch_login_asset_index(raw: bytes, changed: dict[str, bytes]) -> bytes:
    """Update only the two login bundle MD5/size rows in m.assets_list.txt."""
    if digest(raw) != ASSET_INDEX_SHA256 or set(changed) != set(LOGIN_BUNDLES):
        raise ValueError("Reviewed asset index and both login bundles are required")
    if not raw.endswith(b"\n") or b"\r" in raw:
        raise ValueError("Unexpected asset index line endings")
    lines = raw.decode("utf-8").splitlines()
    for member in LOGIN_BUNDLES:
        name = "/" + member.removeprefix("assets/assetbundle/")
        positions = [i for i, line in enumerate(lines) if "=" + name + ":" in line]
        if len(positions) != 1:
            raise ValueError("Expected one login asset index entry: " + name)
        old = lines[positions[0]]
        if not re.fullmatch(r"[0-9a-f]{32}=" + re.escape(name) + r":[0-9]+", old):
            raise ValueError("Unexpected login asset index format: " + name)
        lines[positions[0]] = (hashlib.md5(changed[member]).hexdigest()
                               + "=" + name + ":" + str(len(changed[member])))
    result = ("\n".join(lines) + "\n").encode("utf-8")
    if len(lines) != len(result.splitlines()):
        raise ValueError("Asset index row count changed")
    return result


def patch_login_assets(source: dict[str, bytes]) -> dict[str, bytes]:
    """Return exactly the two edited login bundles and their updated index."""
    if set(source) != {*LOGIN_BUNDLES, ASSET_INDEX}:
        raise ValueError("Reviewed bundles and index are all required")
    changed = patch_login_resources({member: source[member] for member in LOGIN_BUNDLES})
    changed[ASSET_INDEX] = patch_login_asset_index(source[ASSET_INDEX], changed)
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Run a read-only v106 patch check")
    args = parser.parse_args()
    if not args.check:
        parser.error("Use --check; this module never writes an APK")
    source = read_reviewed_assets()
    changed = patch_login_assets(source)
    print(json.dumps({"sourceApk": str(SOURCE_APK),
                      "members": {member: {"oldSha256": digest(source[member]),
                                           "newSha256": digest(changed[member])}
                                  for member in changed},
                      "oldText": OLD_TEXT, "newText": NEW_TEXT}))


if __name__ == "__main__":
    main()
