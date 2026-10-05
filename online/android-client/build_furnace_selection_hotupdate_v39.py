"""Build a signed furnace selection gate on top of the live guild recall update."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import UnityPy


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
ROOT = PROJECT / "热更新测试" / "主线热更候选"
SOURCE = HERE / "lua" / "init-furnace-selection-gate.lua"
KEY = PROJECT / ".local" / "热更新密钥" / "签名私钥.pem"
APK = HERE / "build" / "witchweapon-original-stardust-v105-test.apk"
BASE = "35-daaeb76b24c29cdd19e8230f4d8013f66ae8653f210ee5851f6fa05f273f423a"
LUA_PATH = "assetbundle/lua/lua.ab"
LUA_SHA = "8023bdee7eb770f1e5f24d3f60a0d85297dc4337859391e53b5e5835a87e1912"
OBJECT_SHA = "311eb7a19d77d66608ae38a9e181b40c115411687d3d356e31f3c4e76a173710"
SCRIPT_SHA = "986dd3b3111bb444a49f7f9aa1032ad8f26f8719182ee915fead48f3b8ee4b8f"
SEQUENCE = 39


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    local_current = (ROOT / "current").read_text(encoding="utf-8").strip()
    if local_current not in {BASE,
            "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023"}:
        raise ValueError("Local update pointer changed; inspect the new base first")
    base_raw = (ROOT / "releases" / BASE / "manifest.json").read_bytes()
    if sha(base_raw) != BASE.split("-", 1)[1]:
        raise ValueError("Active manifest changed")
    manifest = json.loads(base_raw)
    if manifest["releaseSequence"] != 35 or len(manifest["assets"]) != 73:
        raise ValueError("Unexpected guild recall base manifest")
    lua_asset = next((a for a in manifest["assets"] if a["path"] == LUA_PATH), None)
    if lua_asset is None or lua_asset["sha256"] != LUA_SHA:
        raise ValueError("Active startup Lua differs")
    old_bundle = (ROOT / "blobs" / LUA_SHA).read_bytes()
    if sha(old_bundle) != LUA_SHA:
        raise ValueError("Active startup Lua blob changed")
    addition = SOURCE.read_text(encoding="utf-8")
    if (addition.count("ONLINE_FURNACE_SELECTION_GATE") < 1 or
            "selectWeaponID" not in addition or "CTLD_LevelButton" not in addition):
        raise ValueError("Furnace gate source is incomplete")
    bundle = UnityPy.load(old_bundle)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(targets) != 1 or before[targets[0].path_id] != OBJECT_SHA:
        raise ValueError("Reviewed init.lua object is missing")
    target = targets[0]
    tree = target.read_typetree()
    old_script = tree["m_Script"]
    if (sha(old_script.encode("utf-8")) != SCRIPT_SHA or
            "ONLINE_GUILD_RECALL_REWARD" not in old_script or
            "ONLINE_FURNACE_SELECTION_GATE" in old_script):
        raise ValueError("Reviewed guild recall init.lua script changed")
    new_script = old_script.rstrip("\n") + "\n\n" + addition.rstrip("\n") + "\n"
    tree["m_Script"] = new_script
    target.save_typetree(tree)
    new_bundle = bundle.file.save(packer="original")
    reopened = UnityPy.load(new_bundle)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in reopened.objects}
    if (set(before) != set(after) or
            {key for key in before if before[key] != after[key]} != {target.path_id}):
        raise ValueError("Unrelated Unity objects changed")
    matching = [obj for obj in reopened.objects if obj.path_id == target.path_id]
    if len(matching) != 1 or matching[0].read_typetree()["m_Script"] != new_script or \
            "ONLINE_GUILD_RECALL_REWARD" not in new_script:
        raise ValueError("Patched Lua failed round-trip")
    new_sha = sha(new_bundle)

    proposed = copy.deepcopy(manifest)
    proposed["releaseSequence"] = SEQUENCE
    for asset in proposed["assets"]:
        if asset["path"] == LUA_PATH:
            asset.update({"url": "/updates/stable/blobs/" + new_sha,
                          "size": len(new_bundle), "sha256": new_sha})
    signed_bytes = (json.dumps(proposed, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    release_name = str(SEQUENCE) + "-" + sha(signed_bytes)
    release_dir = ROOT / "releases" / release_name
    if release_dir.exists():
        raise FileExistsError("Furnace release already exists: " + release_name)

    sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read("assets/update_public_key.der"))
    public.verify(base64.b64decode((ROOT / "releases" / BASE / "manifest.sig").read_bytes()),
                  base_raw, padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if public.public_numbers() != private.public_key().public_numbers():
        raise ValueError("Update signing key differs from installed client")
    signature = private.sign(signed_bytes, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, signed_bytes, padding.PKCS1v15(), hashes.SHA256())

    blob_path = ROOT / "blobs" / new_sha
    if blob_path.exists():
        if blob_path.read_bytes() != new_bundle:
            raise ValueError("Content-addressed blob differs")
    else:
        blob_path.write_bytes(new_bundle)
    release_dir.mkdir(parents=False)
    (release_dir / "manifest.json").write_bytes(signed_bytes)
    (release_dir / "manifest.sig").write_bytes(base64.b64encode(signature) + b"\n")
    if sha((release_dir / "manifest.json").read_bytes()) != release_name.split("-", 1)[1]:
        raise ValueError("Saved manifest failed verification")
    print("FURNACE_SELECTION_HOTUPDATE_READY", release_name, new_sha)


if __name__ == "__main__":
    main()
