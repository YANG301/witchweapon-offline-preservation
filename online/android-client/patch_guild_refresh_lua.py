"""Patch the existing MainScenePanel Lua hook for guild log repainting."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import UnityPy


APK = Path(r"D:\Project\魔女兵器在线版\android-client\build"
           r"\witchweapon-hide-guide-envelope-v92-test.apk")
MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
SOURCE = Path(__file__).resolve().parent / "lua/MainScenePanelPatch-guild-refresh.lua"
OUTPUT_ROOT = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs")
BASE_BUNDLE = "82ffcd50e67a7ad9806b10d1ffd051dbfc36fe57aaefca4f1056b2c3e30928c1"
BASE_OBJECT = "fae61d1b2969ba26a43b4fd98b93ad0e88184dbde35187c3823949d6e59153e9"
BASE_SCRIPT = "48c007c740acd1c2d0a88db023600ea489d2d6250da264529c03482df7b82c58"
TARGET = "MainScenePanelPatch.lua"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch(raw: bytes, script: str) -> bytes:
    if sha(raw) != BASE_BUNDLE:
        raise ValueError("Current signed Lua AssetBundle changed")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    matches = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == TARGET]
    if len(matches) != 1 or before[matches[0].path_id] != BASE_OBJECT:
        raise ValueError("Guild refresh hook object is missing or changed")
    target = matches[0]
    tree = target.read_typetree()
    if not isinstance(tree.get("m_Script"), str) or sha(tree["m_Script"].encode()) != BASE_SCRIPT:
        raise ValueError("Original lobby Lua script differs from reviewed version")
    if "ONLINE_GUILD_REFRESH_READY" not in script or "SetGuildLogUI" not in script:
        raise ValueError("Guild refresh implementation is incomplete")
    tree["m_Script"] = script
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    after_bundle = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in after_bundle.objects}
    if set(before) != set(after) or {key for key in before if before[key] != after[key]} != {target.path_id}:
        raise ValueError("Guild refresh patch changed unrelated Unity objects")
    verified = [obj.read_typetree()["m_Script"] for obj in after_bundle.objects
                if obj.path_id == target.path_id]
    if verified != [script]:
        raise ValueError("Patched guild refresh Lua did not round-trip")
    return result


def main() -> None:
    with zipfile.ZipFile(APK) as package:
        raw = package.read(MEMBER)
    script = SOURCE.read_text(encoding="utf-8")
    data = patch(raw, script)
    digest = sha(data)
    path = OUTPUT_ROOT / digest
    if path.exists():
        if sha(path.read_bytes()) != digest:
            raise ValueError("Content-addressed guild patch path is occupied")
    else:
        path.write_bytes(data)
    print("GUILD_LUA_PATCH_OK", digest, len(data))


if __name__ == "__main__":
    main()
