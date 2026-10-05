"""Create the reviewed Lua bundle for the unlimited-stock UI repair."""
from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import patch_unlimited_stock_v24 as stock


HERE = Path(__file__).resolve().parent
APK = HERE / "build/witchweapon-resource-shop-v101-test.apk"
APK_SHA = "8af6932968f68ef79434a2ef7e7ade5ca605227a8a890b42b26ab88d015be4d0"
BLOBS = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs")
MEMBER = "assets/assetbundle/lua/lua.ab"


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> str:
    if sha_file(APK) != APK_SHA or not BLOBS.is_dir():
        raise ValueError("Reviewed v101 APK or release blob store missing")
    with zipfile.ZipFile(APK) as archive:
        patched = stock.patch(archive.read(MEMBER))
    digest = hashlib.sha256(patched).hexdigest()
    target = BLOBS / digest
    if target.exists():
        if sha_file(target) != digest:
            raise ValueError("Existing release blob differs")
    else:
        with target.open("xb") as stream:
            stream.write(patched)
        if sha_file(target) != digest:
            raise ValueError("Written release blob differs")
    return digest


if __name__ == "__main__":
    print("UNLIMITED_STOCK_LUA_V24", build())
