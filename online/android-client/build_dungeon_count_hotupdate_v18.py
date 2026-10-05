"""Sign the daily-attempt counter repair as a Lua-only sequence-18 update."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

import build_dungeon_sweep_hotupdate_v17 as previous


ROOT = previous.ROOT
KEY = previous.KEY
APK = previous.APK
APK_SHA256 = previous.APK_SHA256
OPENSSL = previous.OPENSSL
TEMP_PARENT = previous.TEMP_PARENT
PREVIOUS = "17-871dc9f4df7ecd06d3ee7308128044415fc031898d6fcb83bc504a7e6a0cc65c"
NEW_LUA = "7eedd74aa0e7306864a44fbe405f087d8c2cc709e9aa8ea13014c1656ae38a05"
ASSETS = dict(previous.ASSETS)
ASSETS["assetbundle/lua/lua.ab"] = NEW_LUA


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> str:
    if (ROOT / "current").read_text(encoding="utf-8").strip() != PREVIOUS:
        raise ValueError("Sequence-17 is not the local baseline")
    if digest(APK) != APK_SHA256 or not OPENSSL.is_file() or not KEY.is_file():
        raise ValueError("Reviewed APK or signing dependency changed")
    assets = []
    for logical, sha in sorted(ASSETS.items()):
        blob = ROOT / "blobs" / sha
        if not blob.is_file() or digest(blob) != sha:
            raise ValueError("Reviewed asset blob missing: " + logical)
        assets.append({"path": logical,
                       "url": "/updates/stable/blobs/" + sha,
                       "size": blob.stat().st_size, "sha256": sha})
    with zipfile.ZipFile(APK) as source:
        client_public = source.read("assets/update_public_key.der")
    data = {"schema": 1,
            "packageId": "com.codex.witchweapon.online.originalui.test",
            "targetAppVersion": "2.0.1.20043082",
            "minBootstrapVersion": 1,
            "releaseSequence": 18,
            "assets": assets}
    manifest = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    sha = hashlib.sha256(manifest).hexdigest()
    release = "18-" + sha
    folder = ROOT / "releases" / release
    if folder.exists():
        raise FileExistsError("Sequence-18 candidate already exists")
    public_pem = subprocess.run(
        [str(OPENSSL), "pkey", "-in", str(KEY), "-pubout"],
        check=True, capture_output=True).stdout
    public_der = subprocess.run(
        [str(OPENSSL), "pkey", "-pubin", "-inform", "PEM", "-outform", "DER"],
        input=public_pem, check=True, capture_output=True).stdout
    if public_der != client_public:
        raise ValueError("Signing key differs from installed client")
    signature = subprocess.run(
        [str(OPENSSL), "dgst", "-sha256", "-sign", str(KEY)],
        input=manifest, check=True, capture_output=True).stdout
    TEMP_PARENT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="witch-daily-v18-", dir=TEMP_PARENT) as tmp:
        temp = Path(tmp)
        (temp / "manifest.json").write_bytes(manifest)
        (temp / "manifest.sig").write_bytes(signature)
        (temp / "public.pem").write_bytes(public_pem)
        result = subprocess.run(
            [str(OPENSSL), "dgst", "-sha256", "-verify", str(temp / "public.pem"),
             "-signature", str(temp / "manifest.sig"), str(temp / "manifest.json")],
            check=True, capture_output=True)
        if b"Verified OK" not in result.stdout:
            raise ValueError("Signed manifest failed local verification")
    encoded = base64.b64encode(signature) + b"\n"
    if len(encoded) != 513:
        raise ValueError("Unexpected manifest signature length")
    folder.mkdir(parents=False)
    (folder / "manifest.json").write_bytes(manifest)
    (folder / "manifest.sig").write_bytes(encoded)
    if digest(folder / "manifest.json") != sha:
        raise ValueError("Manifest write did not round-trip")
    return release


if __name__ == "__main__":
    print("DUNGEON_COUNT_HOTUPDATE_V18_CANDIDATE_OK", build())
