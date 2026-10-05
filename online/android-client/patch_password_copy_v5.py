"""Correct the original login UI's password copy in reviewed Unity bundles.

The original email-registration input is capped at 16 characters, while the
new account service requires at least 12. Its API may accept up to 128; this
old UI cannot enter more than 16, so the in-game copy says 12-16.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


DICTIONARY_MEMBER = "assets/assetbundle/config/clientexel/dictionarystatic.ab"
LOGIN_MEMBER = "assets/assetbundle/scene/loginfromal.ab"
INDEX_NAMES = {
    DICTIONARY_MEMBER: "/config/clientexel/dictionarystatic.ab",
    LOGIN_MEMBER: "/scene/loginfromal.ab",
}
EXPECTED_BUNDLE_SHA256 = {
    DICTIONARY_MEMBER: "6653b08baf5742958623c5dad966e7021dd5582f7e863c30c89ebebd29c53131",
    LOGIN_MEMBER: "e14676e148d0bfb5cfdd51cb54801dbcce9ff1b3b2eb610672cc89c5dca3401f",
}
OLD_SHORT = "请设置密码（6-15位）"
NEW_SHORT = "请设置密码（12-16位）"
OLD_LONG = "输入6-15位数字和字母"
NEW_LONG = "输入12-16位数字和字母"
SCENE_IDS = {
    2880, 3207, 3211, 3366, 3435, 3522, 3623, 3649, 3677, 3910,
    4035, 4088, 4135, 4169, 4269, 4320, 4356, 4372, 4433, 4459, 4541,
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _checked_bundle(raw: bytes, member: str):
    if sha256(raw) != EXPECTED_BUNDLE_SHA256[member]:
        raise ValueError("Unreviewed Unity bundle: " + member)
    return UnityPy.load(raw)


def _replace_dictionary_rows(source: str) -> str:
    # Preserve all existing line endings and the leading UTF-8 BOM.
    replacements = {
        "CE10114": (
            "密码有效长度为12-16位",
            "密碼有效長度為12-16個字元",
            "パスワードは12-16文字です",
            "비밀번호 길이는 12-16자입니다.",
            "12-16 characters.",
        ),
        "": (
            NEW_LONG,
            "輸入12-16個字元的數字和字母",
            "数字か英文を入力（12-16文字）",
            "12-16자 사이 숫자 와 문자 입력",
            "12-16 characters (numbers and letters only)",
        ),
    }
    counts = {key: 0 for key in replacements}
    out = []
    for line in source.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        fields = body.split("\t")
        if len(fields) == 7 and fields[0] == "CE10114":
            if fields[1] != "密码有效长度为6-16位":
                raise ValueError("Original CE10114 translation changed")
            fields[1:6] = replacements["CE10114"]
            counts["CE10114"] += 1
            line = "\t".join(fields) + ending
        elif len(fields) == 7 and fields[0] == "" and fields[1] == OLD_LONG:
            fields[1:6] = replacements[""]
            counts[""] += 1
            line = "\t".join(fields) + ending
        out.append(line)
    if counts != {"CE10114": 1, "": 1}:
        raise ValueError("Original password dictionary rows are missing or duplicated")
    updated = "".join(out)
    if "CE10114\t密码有效长度为12-16位" not in updated or OLD_LONG in updated:
        raise ValueError("Password dictionary patch did not apply")
    return updated


def patch_dictionary(raw: bytes) -> bytes:
    bundle = _checked_bundle(raw, DICTIONARY_MEMBER)
    before = {obj.path_id: sha256(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "MonoBehaviour"
               and obj.read_typetree().get("m_Name") == "DictionaryStatic"]
    if len(targets) != 1:
        raise ValueError("Original DictionaryStatic object is missing or duplicated")
    target = targets[0]
    tree = target.read_typetree()
    if tree.get("isEncrypt") != 1:
        raise ValueError("Expected XOR-encrypted dictionary")
    original = bytes(value ^ 255 for value in tree["bytes"]).decode("utf-8")
    if not original.startswith("\ufefftag\t"):
        raise ValueError("Unexpected dictionary encoding/header")
    updated = _replace_dictionary_rows(original)
    tree["bytes"] = [value ^ 255 for value in updated.encode("utf-8")]
    target.save_typetree(tree)
    output = bundle.file.save(packer="original")
    check = UnityPy.load(output)
    changed = {obj.path_id for obj in check.objects
               if sha256(obj.get_raw_data()) != before[obj.path_id]}
    if changed != {target.path_id}:
        raise ValueError("Unrelated dictionary object changed: " + str(changed))
    matched = next(obj for obj in check.objects if obj.path_id == target.path_id)
    decoded = bytes(value ^ 255 for value in matched.read_typetree()["bytes"]).decode("utf-8")
    if decoded != updated:
        raise ValueError("Password dictionary failed Unity round-trip")
    return output


def patch_login_scene(raw: bytes) -> bytes:
    bundle = _checked_bundle(raw, LOGIN_MEMBER)
    # Scene bundles contain both a scene serialized file and sharedAssets;
    # their path IDs overlap, so use both coordinates for comparison.
    before = {(obj.assets_file.name, obj.path_id): sha256(obj.get_raw_data())
              for obj in bundle.objects}
    changed_ids = set()
    replacements = {OLD_SHORT: NEW_SHORT, OLD_LONG: NEW_LONG}
    for obj in bundle.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        tree = obj.read_typetree()
        fields = [key for key in ("DefaultText", "mText")
                  if tree.get(key) in replacements]
        if not fields:
            continue
        if obj.path_id not in SCENE_IDS or len(fields) != 1:
            raise ValueError("Unreviewed password label in original scene")
        key = fields[0]
        tree[key] = replacements[tree[key]]
        obj.save_typetree(tree)
        changed_ids.add(obj.path_id)
    if changed_ids != SCENE_IDS:
        raise ValueError("Original scene password labels changed")
    output = bundle.file.save(packer="original")
    check = UnityPy.load(output)
    changed = {obj.path_id for obj in check.objects
               if sha256(obj.get_raw_data()) != before[(obj.assets_file.name, obj.path_id)]}
    if changed != SCENE_IDS:
        raise ValueError("Unrelated scene objects changed: " + str(changed ^ SCENE_IDS))
    for obj in check.objects:
        if obj.path_id not in SCENE_IDS:
            continue
        tree = obj.read_typetree()
        if tree.get("DefaultText") not in (NEW_SHORT, NEW_LONG) and \
                tree.get("mText") not in (NEW_SHORT, NEW_LONG):
            raise ValueError("Password scene label failed Unity round-trip")
    # The original registration input remains exactly 16 characters long.
    field = next(obj for obj in check.objects if obj.path_id == 4588)
    if field.read_typetree().get("characterLimit") != 16:
        raise ValueError("Registration password input limit changed")
    return output


def patch_bundles(raws: dict[str, bytes]) -> dict[str, bytes]:
    if set(raws) != set(INDEX_NAMES):
        raise ValueError("Both reviewed password UI bundles are required")
    return {
        DICTIONARY_MEMBER: patch_dictionary(raws[DICTIONARY_MEMBER]),
        LOGIN_MEMBER: patch_login_scene(raws[LOGIN_MEMBER]),
    }
