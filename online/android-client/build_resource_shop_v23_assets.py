"""Create the four reviewed sequence-23 AssetBundle blobs from the v100 APK."""
from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import patch_resource_shop_v23 as patch


HERE = Path(__file__).resolve().parent
APK = HERE / "build/witchweapon-welfare-return-v100-test.apk"
APK_SHA = "7d88a0a08f6ba4aa829b2f6473a7e9a37ae101e99419016e4df36bc79caaac67"
BLOBS = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs")


def sha_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def build() -> dict[str, str]:
    if sha_file(APK) != APK_SHA or not BLOBS.is_dir():
        raise ValueError("Reviewed APK or content-addressed release store missing")
    with zipfile.ZipFile(APK) as source:
        result = patch.replacements(source.read)
    records = {}
    for member, data in result.items():
        digest = hashlib.sha256(data).hexdigest()
        destination = BLOBS / digest
        if destination.exists():
            if sha_file(destination) != digest:
                raise ValueError("Existing content-addressed blob differs")
        else:
            with destination.open("xb") as target:
                target.write(data)
            if sha_file(destination) != digest:
                raise ValueError("Written AssetBundle differs from reviewed patch")
        records[member.removeprefix("assets/")] = digest
    return records


if __name__ == "__main__":
    for logical, digest in sorted(build().items()):
        print(logical, digest)

