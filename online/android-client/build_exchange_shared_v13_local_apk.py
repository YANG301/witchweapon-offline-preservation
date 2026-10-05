"""Upgrade only the local v12 APK's exchange entrances to shared group-0 stores."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_online_apk import patch_index
from patch_exchange_shop_tables import patch_shopstructure_bundle
from patch_gift_shop_tables import SHOPSTRUCTURE_MEMBER


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SOURCE = BUILD / "witchweapon-online-local-staging-caph-caption-v12.apk"
SOURCE_SHA256 = "872dd365f37e289a2272bfa5fa8ba4d743491b6afa44f730b6fb22eff375aecb"
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程"
                r"\assets\assetbundle\config\clientexel\shopstructure.ab")
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"
OLD_STRUCTURE_SHA256 = "04da9c62690ece05419fb8936df9c91bb881e1c86edc4e0fa6646b13bfb9cff4"
OLD_INDEX_SHA256 = "70c430ead9971b69b8142348c7daa81ea5f4e1ba8af47eae1476a4a580bfcd2e"
NEW_STRUCTURE_SHA256 = "bdc4235539c9cb22a6824c0bbe42a4377aea08f013f7e6fac84d2cacb1824a01"
RESULT = BUILD / "witchweapon-online-local-staging-exchange-shared-v13.apk"
REPORT = BUILD / "本地测试服兑换所共享货架验收-v13.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-exchange-shared-v13-local"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(block)
    return hashed.hexdigest()


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or file_digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed local v12 APK missing or changed")
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate APK member")
        if apk.read(ENDPOINT) != b"https://127.0.0.1:19443\n":
            raise ValueError("Only the isolated local service is allowed")
        before = apk.read(SHOPSTRUCTURE_MEMBER)
        index = apk.read(INDEX)
    if digest(before) != OLD_STRUCTURE_SHA256 or digest(index) != OLD_INDEX_SHA256:
        raise ValueError("Unreviewed v12 exchange bundle or index")
    updated = patch_shopstructure_bundle(before, ORIGINAL.read_bytes())
    if digest(updated) != NEW_STRUCTURE_SHA256 or updated == before:
        raise ValueError("Shared exchange structure patch differs")
    changed_index = patch_index(index, {"/config/clientexel/shopstructure.ab": updated})
    if changed_index == index:
        raise ValueError("ShopStructure bundle index unchanged")
    return {SHOPSTRUCTURE_MEMBER: updated, INDEX: changed_index}


def build(replacements: dict[str, bytes]) -> dict:
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise ValueError("v13 output or temporary build already exists")
    try:
        signer.SOURCE = SOURCE
        signer.SOURCE_SHA256 = SOURCE_SHA256
        signer.TEMP = TEMP
        report = signer.build(replacements, RESULT, REPORT)
        with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(RESULT) as new:
            for member in ("AndroidManifest.xml", "classes.dex", "classes2.dex", ENDPOINT):
                if old.read(member) != new.read(member):
                    raise ValueError("Core APK member changed: " + member)
            if any(new.read(member) != data for member, data in replacements.items()):
                raise ValueError("Signed exchange payload differs")
        report.update({
            "purpose": "Restore original CN exchange entrances to shared channel-group-0 BigSets 47000024/05/25",
            "endpoint": "https://127.0.0.1:19443",
            "sourceApkSha256": SOURCE_SHA256,
            "shopStructureSha256": digest(replacements[SHOPSTRUCTURE_MEMBER]),
            "bundleIndexSha256": digest(replacements[INDEX]),
            "runtimeValidated": False,
        })
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        return report
    finally:
        if TEMP.is_dir():
            if TEMP.resolve().parent != TEMP_PARENT.resolve() or \
                    TEMP.resolve().name != "witch-online-exchange-shared-v13-local":
                raise ValueError("Unsafe build-temp cleanup target")
            shutil.rmtree(TEMP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    replacements = prepare()
    if not args.build:
        print("EXCHANGE_SHARED_V13_STATIC_OK",
              digest(replacements[SHOPSTRUCTURE_MEMBER]), digest(replacements[INDEX]))
        return
    report = build(replacements)
    print("EXCHANGE_SHARED_V13_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
