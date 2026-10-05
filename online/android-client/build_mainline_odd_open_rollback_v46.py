"""Sign a release-43 asset rollback before publishing the odd-stage gate."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile


PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / "热更新测试" / "主线热更候选"
BASE = "43-2cc5f626dbbb12a7cf53a264c65125112346e489425fbe2b9b8cad7ce945f1b0"
LUA = "assetbundle/lua/lua.ab"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_release(name: str) -> dict:
    raw = (ROOT / "releases" / name / "manifest.json").read_bytes()
    if sha(raw) != name.split("-", 1)[1]:
        raise ValueError("Release manifest changed: " + name)
    return json.loads(raw)


def main() -> None:
    local_current = (ROOT / "current").read_text(encoding="utf-8").strip()
    if local_current not in {BASE,
            "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023"}:
        raise ValueError("Local update pointer changed; inspect rollback base first")
    original = read_release(BASE)
    candidates = sorted((ROOT / "releases").glob("45-*/manifest.json"))
    if len(candidates) != 1:
        raise ValueError("Expected exactly one reviewed release 45")
    fix_name = candidates[0].parent.name
    fixed = read_release(fix_name)
    old_assets = {item["path"]: item["sha256"] for item in original["assets"]}
    new_assets = {item["path"]: item["sha256"] for item in fixed["assets"]}
    if (original["releaseSequence"] != 43 or fixed["releaseSequence"] != 45 or
            len(original["assets"]) != 73 or len(fixed["assets"]) != 73 or
            set(old_assets) != set(new_assets) or
            {path for path in old_assets if old_assets[path] != new_assets[path]} != {LUA} or
            sha((ROOT / "blobs" / new_assets[LUA]).read_bytes()) != new_assets[LUA]):
        raise ValueError("Furnace fix differs from one-bundle reviewed change")

    rollback = copy.deepcopy(original)
    rollback["releaseSequence"] = 46
    data = (json.dumps(rollback, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    name = "46-" + sha(data)
    folder = ROOT / "releases" / name
    if folder.exists():
        raise FileExistsError("Furnace rollback already exists: " + name)

    sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    apk_path = PROJECT / "android-client" / "build" / "witchweapon-original-stardust-v105-test.apk"
    with zipfile.ZipFile(apk_path) as apk:
        public = serialization.load_der_public_key(apk.read("assets/update_public_key.der"))
    for source in (BASE, fix_name):
        raw = (ROOT / "releases" / source / "manifest.json").read_bytes()
        prior_signature = base64.b64decode(
            (ROOT / "releases" / source / "manifest.sig").read_bytes())
        public.verify(prior_signature, raw, padding.PKCS1v15(), hashes.SHA256())
    key_path = PROJECT / ".local" / "热更新密钥" / "签名私钥.pem"
    private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    if public.public_numbers() != private.public_key().public_numbers():
        raise ValueError("Update signing key differs from installed client")
    signature = private.sign(data, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    folder.mkdir(parents=False)
    (folder / "manifest.json").write_bytes(data)
    (folder / "manifest.sig").write_bytes(base64.b64encode(signature) + b"\n")
    if sha((folder / "manifest.json").read_bytes()) != name.split("-", 1)[1]:
        raise ValueError("Saved rollback manifest failed verification")
    print("FURNACE_SELECTION_ROLLBACK_READY", name)


if __name__ == "__main__":
    main()
