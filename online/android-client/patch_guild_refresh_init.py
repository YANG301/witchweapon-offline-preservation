"""Append the guild UI listener to the active Lua startup script in v92."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import UnityPy


HERE = Path(__file__).resolve().parent
APK = HERE / "build/witchweapon-hide-guide-envelope-v92-test.apk"
MEMBER = "assets/assetbundle/lua/lua.ab"
SOURCE = HERE / "lua/init-guild-refresh.lua"
OUTPUT = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs")
BASE_BUNDLE = "edc4d4831829ee0fa844e095e62dc66b53116edb67793ca133ff4229356cd4cb"
BASE_OBJECT = "f3d2f104b856fdd44b349deafab8fd260f59fdd60a1d317521be5e3eda3b9e85"
BASE_SCRIPT = "82977ac90f62bc176ae9f2c59e8884c6605ed07cc3600135fceeb70552e392fa"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    with zipfile.ZipFile(APK) as package:
        raw = package.read(MEMBER)
    if sha(raw) != BASE_BUNDLE:
        raise ValueError("Reviewed v92 startup bundle changed")
    block = SOURCE.read_text(encoding="utf-8")
    if ("ONLINE_GUILD_REFRESH_READY" not in block
            or "UpdateBeat:Add(function()" not in block
            or "FindObjectOfType" not in block):
        raise ValueError("Guild startup listener is incomplete")

    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    matches = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(matches) != 1 or before[matches[0].path_id] != BASE_OBJECT:
        raise ValueError("Reviewed init.lua TextAsset is missing")
    target = matches[0]
    tree = target.read_typetree()
    old = tree.get("m_Script")
    if not isinstance(old, str) or sha(old.encode("utf-8")) != BASE_SCRIPT:
        raise ValueError("Reviewed init.lua script changed")
    expected = old + "\n" + block
    tree["m_Script"] = expected
    target.save_typetree(tree)
    data = bundle.file.save(packer="original")
    result = UnityPy.load(data)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in result.objects}
    if set(before) != set(after) or {
            key for key in before if before[key] != after[key]
            } != {target.path_id}:
        raise ValueError("Guild startup patch changed unrelated objects")
    scripts = [obj.read_typetree().get("m_Script") for obj in result.objects
               if obj.path_id == target.path_id]
    if scripts != [expected]:
        raise ValueError("Guild startup script failed round-trip")
    digest = sha(data)
    output = OUTPUT / digest
    if output.exists():
        if sha(output.read_bytes()) != digest:
            raise ValueError("Content-addressed startup bundle is occupied")
    else:
        output.write_bytes(data)
    print("GUILD_STARTUP_PATCH_OK", digest, len(data))


if __name__ == "__main__":
    main()
