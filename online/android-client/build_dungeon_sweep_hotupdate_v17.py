"""Sign an isolated sequence-17 candidate with the post-battle refresh Lua."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent / "热更新测试" / "主线热更候选"
KEY = HERE.parent / ".local" / "热更新密钥" / "签名私钥.pem"
APK = HERE / "build" / "witchweapon-hide-guide-envelope-v92-test.apk"
APK_SHA256 = "b77d722ffad01337eb1ec2b5ab6d130a480a5279c7b1074d65a33709bff4c55e"
OPENSSL = Path(r"C:\Program Files\Git\usr\bin\openssl.exe")
TEMP_PARENT = Path(r"D:\Environment\VPS-SSH\temp")
PREVIOUS = "16-3d1ca7690f57b71d6399eae3e2ad7558450598135a6d84f1c23563402109a156"
ASSETS = {
    "assetbundle/assets/resources/ui/prefab/mainscenepanel.ab":
        "7566ab0e12b7c65018418644e4e7f084a70565739c0c2efa1d6458123da15a24",
    "assetbundle/lua/lua_projx_patch.ab":
        "e68bdef08a277149f23096a2383c48530e3ed86cb05485377779325b6141376b",
    "assetbundle/lua/lua.ab":
        "2b17e98fc0f82d2fc3306b3beb51ccf6f94ba1c30e9ee394a81ce1746216a330",
}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    if (ROOT / "current").read_text(encoding="utf-8").strip() != PREVIOUS:
        raise ValueError("Sequence-16 is not the local baseline")
    if digest(APK) != APK_SHA256:
        raise ValueError("Reviewed v92 APK changed")
    if not OPENSSL.is_file() or not KEY.is_file():
        raise FileNotFoundError("Portable signing dependency is missing")
    with zipfile.ZipFile(APK) as apk:
        public_der = apk.read("assets/update_public_key.der")
    assets = []
    for logical, sha in sorted(ASSETS.items()):
        blob = ROOT / "blobs" / sha
        if not blob.is_file() or digest(blob) != sha:
            raise ValueError("Missing reviewed asset blob: " + logical)
        assets.append({"path": logical, "url": "/updates/stable/blobs/" + sha,
                       "size": blob.stat().st_size, "sha256": sha})
    data = {"schema": 1,
            "packageId": "com.codex.witchweapon.online.originalui.test",
            "targetAppVersion": "2.0.1.20043082", "minBootstrapVersion": 1,
            "releaseSequence": 17, "assets": assets}
    manifest = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sha = hashlib.sha256(manifest).hexdigest()
    release = "17-" + sha
    folder = ROOT / "releases" / release
    if folder.exists():
        raise FileExistsError("Sequence-17 candidate already exists")
    public_pem = subprocess.run(
        [str(OPENSSL), "pkey", "-in", str(KEY), "-pubout"],
        check=True, capture_output=True).stdout
    derived_der = subprocess.run(
        [str(OPENSSL), "pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
        input=public_pem, check=True, capture_output=True).stdout
    if derived_der != public_der:
        raise ValueError("Private key does not match the installed client")
    signature = subprocess.run(
        [str(OPENSSL), "dgst", "-sha256", "-sign", str(KEY)],
        input=manifest, check=True, capture_output=True).stdout
    TEMP_PARENT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="witch-sweep-v17-", dir=TEMP_PARENT) as tmp:
        temp = Path(tmp)
        (temp / "manifest.json").write_bytes(manifest)
        (temp / "manifest.sig").write_bytes(signature)
        (temp / "public.pem").write_bytes(public_pem)
        verified = subprocess.run(
            [str(OPENSSL), "dgst", "-sha256", "-verify", str(temp / "public.pem"),
             "-signature", str(temp / "manifest.sig"), str(temp / "manifest.json")],
            check=True, capture_output=True)
        if b"Verified OK" not in verified.stdout:
            raise ValueError("Manifest signature failed local verification")
    encoded = base64.b64encode(signature) + b"\n"
    if len(encoded) != 513:
        raise ValueError("Unexpected manifest signature length")
    folder.mkdir(parents=False)
    (folder / "manifest.json").write_bytes(manifest)
    (folder / "manifest.sig").write_bytes(encoded)
    if digest(folder / "manifest.json") != sha:
        raise ValueError("Manifest write did not round-trip")
    if base64.b64decode((folder / "manifest.sig").read_bytes()) != signature:
        raise ValueError("Saved signature differs")
    print("DUNGEON_SWEEP_HOTUPDATE_V17_CANDIDATE_OK", release)


if __name__ == "__main__":
    main()
