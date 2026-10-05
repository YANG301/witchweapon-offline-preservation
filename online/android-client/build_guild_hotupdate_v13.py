"""Create a signed sequence-13 resource release for original guild repaint."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, r"D:\Environment\VPS-SSH\packages")
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


ROOT = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选")
KEY = Path(r"D:\Project\魔女兵器在线版\.local\热更新密钥\签名私钥.pem")
APK = Path(r"D:\Project\魔女兵器在线版\android-client\build\witchweapon-hide-guide-envelope-v92-test.apk")
PREVIOUS = "12-c8733ced65498b6e9aeb0dc63d271f68f70a5d7446214840e3fe38a8c082f658"
ASSETS = {
    "assetbundle/assets/resources/ui/prefab/mainscenepanel.ab":
        "7566ab0e12b7c65018418644e4e7f084a70565739c0c2efa1d6458123da15a24",
    "assetbundle/lua/lua_projx_patch.ab":
        "b05e31437acd6055178da7057dbda118239af29222c9988c877b31267282aeaf",
}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    if (ROOT / "current").read_text(encoding="utf-8").strip() != PREVIOUS:
        raise ValueError("Sequence-12 release is no longer current")
    if digest(APK) != "b77d722ffad01337eb1ec2b5ab6d130a480a5279c7b1074d65a33709bff4c55e":
        raise ValueError("Reviewed v92 APK changed")
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read("assets/update_public_key.der"))
    assets = []
    for logical, sha in sorted(ASSETS.items()):
        blob = ROOT / "blobs" / sha
        if not blob.is_file() or digest(blob) != sha:
            raise ValueError("Signed asset blob missing or changed: " + logical)
        assets.append({"path": logical, "url": "/updates/stable/blobs/" + sha,
                       "size": blob.stat().st_size, "sha256": sha})
    data = {"schema": 1,
            "packageId": "com.codex.witchweapon.online.originalui.test",
            "targetAppVersion": "2.0.1.20043082", "minBootstrapVersion": 1,
            "releaseSequence": 13, "assets": assets}
    manifest = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sha = hashlib.sha256(manifest).hexdigest()
    release = "13-" + sha
    folder = ROOT / "releases" / release
    if folder.exists():
        raise FileExistsError("Sequence-13 release already exists")
    private = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if private.public_key().public_numbers() != public.public_numbers():
        raise ValueError("Signing key does not match the v92 client public key")
    signature = private.sign(manifest, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, manifest, padding.PKCS1v15(), hashes.SHA256())
    encoded = base64.b64encode(signature) + b"\n"
    if len(encoded) != 513:
        raise ValueError("Unexpected manifest signature format")
    folder.mkdir(parents=False)
    (folder / "manifest.json").write_bytes(manifest)
    (folder / "manifest.sig").write_bytes(encoded)
    if digest(folder / "manifest.json") != sha:
        raise ValueError("Manifest write did not round-trip")
    public.verify(base64.b64decode((folder / "manifest.sig").read_bytes()),
                  (folder / "manifest.json").read_bytes(),
                  padding.PKCS1v15(), hashes.SHA256())
    print("GUILD_HOTUPDATE_V13_SIGNED", release)


if __name__ == "__main__":
    main()
