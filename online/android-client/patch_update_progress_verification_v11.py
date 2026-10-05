"""Build a no-op Lua resource release to verify the visible download animation.

The source is the already published sequence-10 blob. Only a Lua comment
changes; this cannot alter gameplay or account data. The ZIP is a publisher
input, not an installable APK.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import UnityPy


SOURCE = Path(
    r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs\2da2592affdaf1614519d4120a672c31c182227563178f913f835c51eaa63c98"
)
OUTPUT = Path(r"D:\Environment\Android\temp\witch-progress-v11\verification-patch.apk")
EXPECTED = "2da2592affdaf1614519d4120a672c31c182227563178f913f835c51eaa63c98"
MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
NAME = "LoginFormalPatch.lua"
OLD = "-- signed resource progress delivery v10\n"
NEW = "-- signed resource progress verified v11\n"


def digest(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def main() -> None:
    source = SOURCE.read_bytes()
    if digest(source) != EXPECTED:
        raise ValueError("Sequence-10 blob changed")
    bundle = UnityPy.load(source)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    selected = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
                and obj.read_typetree().get("m_Name") == NAME]
    if len(selected) != 1:
        raise ValueError("Login Lua inventory changed")
    target = selected[0]
    tree = target.read_typetree()
    script = tree.get("m_Script")
    if not isinstance(script, str) or script.count(OLD) != 1:
        raise ValueError("Sequence-10 no-op comment missing")
    tree["m_Script"] = script.replace(OLD, NEW, 1)
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    verified = UnityPy.load(result)
    after = {obj.path_id: digest(obj.get_raw_data()) for obj in verified.objects}
    changed = {key for key in before if before[key] != after[key]}
    if set(before) != set(after) or changed != {target.path_id}:
        raise ValueError("Unexpected Unity object change")
    check = [obj.read_typetree().get("m_Script") for obj in verified.objects
             if obj.path_id == target.path_id]
    if check != [tree["m_Script"]] or result == source:
        raise ValueError("No-op Lua comment failed to round-trip")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(MEMBER, result)
    with zipfile.ZipFile(OUTPUT) as archive:
        if archive.namelist() != [MEMBER] or archive.read(MEMBER) != result:
            raise ValueError("Publisher ZIP changed the Lua bundle")
    print("NOOP_PROGRESS_BLOB_SHA256=" + digest(result))
    print("NOOP_PROGRESS_BLOB_BYTES=" + str(len(result)))


if __name__ == "__main__":
    main()
