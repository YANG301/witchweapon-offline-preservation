"""Build a one-Lua-bundle guild recall fix and a signed rollback release."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import UnityPy


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "热更新测试/主线热更候选"
SOURCE = PROJECT / "android-client/lua/init-guild-recall-reward.lua"
KEY = PROJECT / ".local/热更新密钥/签名私钥.pem"
APK = PROJECT / "android-client/build/witchweapon-original-stardust-v105-test.apk"
BASE = "33-b369a1bc311d9963b7235c27e034e0420d61f2f8a6a7229f1943d19c3bb90fb0"
LUA_PATH = "assetbundle/lua/lua.ab"
LUA_SHA = "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94"
OBJECT_SHA = "c8e9f6a7f032a18b645f3aadba4c3c2d592b2c29b60d0208819a4f1dececdb1e"
SCRIPT_SHA = "2f5a7956a5794a1335a3dfe5f9423d026fd84acd5d7c0a3987172b458f88774f"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install_blob(data: bytes) -> str:
    digest = sha(data)
    path = ROOT / "blobs" / digest
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Content-addressed blob differs")
    else:
        path.write_bytes(data)
    return digest


def build_lua() -> tuple[str, int]:
    old = (ROOT / "blobs" / LUA_SHA).read_bytes()
    if sha(old) != LUA_SHA:
        raise ValueError("Reviewed base Lua bundle changed")
    source = SOURCE.read_text(encoding="utf-8")
    if (source.count("ONLINE_GUILD_RECALL_WALLET_REFRESH") != 1 or
            source.count("ONLINE_GUILD_RECALL_REWARD_SHOWN") != 1 or
            "RoleGetRoleInfoLogic" not in source or
            "ShowGuildServantReward" not in source):
        raise ValueError("Guild recall source is incomplete")
    bundle = UnityPy.load(old)
    original = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(targets) != 1 or sha(targets[0].get_raw_data()) != OBJECT_SHA:
        raise ValueError("Reviewed startup Lua object changed")
    target = targets[0]
    tree = target.read_typetree()
    script = tree["m_Script"]
    if sha(script.encode("utf-8")) != SCRIPT_SHA or "ONLINE_GUILD_RECALL_REWARD" in script:
        raise ValueError("Reviewed startup Lua script changed")
    patched = script.rstrip("\n") + "\n\n" + source.rstrip("\n") + "\n"
    tree["m_Script"] = patched
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    verify = UnityPy.load(result)
    changed = {obj.path_id for obj in verify.objects
               if sha(obj.get_raw_data()) != original[obj.path_id]}
    if (len(verify.objects) != len(bundle.objects) or changed != {target.path_id} or
            next(obj.read_typetree()["m_Script"] for obj in verify.objects
                 if obj.path_id == target.path_id) != patched):
        raise ValueError("Guild recall Lua failed byte-object round trip")
    return install_blob(result), len(result)


def sign_release(base: dict, sequence: int, private, public) -> str:
    data = copy.deepcopy(base)
    data["releaseSequence"] = sequence
    manifest = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    digest = sha(manifest)
    name = str(sequence) + "-" + digest
    folder = ROOT / "releases" / name
    if folder.exists():
        raise FileExistsError("Release already exists: " + name)
    signature = private.sign(manifest, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, manifest, padding.PKCS1v15(), hashes.SHA256())
    folder.mkdir(parents=False)
    (folder / "manifest.json").write_bytes(manifest)
    (folder / "manifest.sig").write_bytes(base64.b64encode(signature) + b"\n")
    if sha((folder / "manifest.json").read_bytes()) != digest:
        raise ValueError("Release manifest did not round trip")
    return name


def main() -> None:
    base_path = ROOT / "releases" / BASE / "manifest.json"
    original = base_path.read_bytes()
    if sha(original) != BASE.split("-", 1)[1]:
        raise ValueError("Base release changed")
    base = json.loads(original)
    if base["releaseSequence"] != 33 or len(base["assets"]) != 73:
        raise ValueError("Unexpected base release")
    original_assets = {asset["path"]: asset for asset in base["assets"]}
    if original_assets[LUA_PATH]["sha256"] != LUA_SHA:
        raise ValueError("Base release Lua differs")
    new_sha, new_size = build_lua()
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read("assets/update_public_key.der"))
    private = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if public.public_numbers() != private.public_key().public_numbers():
        raise ValueError("Client updater public key differs")
    proposed = copy.deepcopy(base)
    for asset in proposed["assets"]:
        if asset["path"] == LUA_PATH:
            asset.update({"url": "/updates/stable/blobs/" + new_sha,
                          "size": new_size, "sha256": new_sha})
    candidate = sign_release(proposed, 35, private, public)
    rollback = sign_release(base, 36, private, public)
    print("GUILD_RECALL_HOTUPDATE_READY", candidate, rollback, new_sha)


if __name__ == "__main__":
    main()
