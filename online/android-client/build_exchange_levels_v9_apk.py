"""Sign v9 APKs from the reviewed v8 pair with only Shop level bands opened."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
from patch_exchange_shop_tables import patch_shop_level_bundle, patch_shop_level_text
from patch_feature_level_gates import _csv_tree
from patch_gift_shop_tables import SHOP_MEMBER


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
ORIGINAL_SHOP = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程"
                     r"\assets\assetbundle\config\clientexel\shop.ab")
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"
DEX = "classes2.dex"
EXPECTED_SHOP_SHA256 = "6dfa643023ce926885903238b2ac3bda5eb28635426c172cc875b6bc31171682"
EXPECTED_INDEX_SHA256 = "26048c3ad63c1dc5191cf5681e763a08f0cbe600d514735d2a219e3624eb6246"
EXPECTED_ORIGINAL_SHA256 = "1ca9a2fb04c2a0c8db6503166e761c9e3124140ed54a0e1010830f540f00506e"
EXPECTED_PATCH_SHA256 = "fcebd516d9518478be728c9864f7819872e9eb400df44a403f9e2558bedc1f66"
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-exchange-links-v8-test.apk",
        "sha256": "001af90d0e901a6965d647624b3056b281a458538ad112755c55632eba07130f",
        "endpoint": "https://212.192.15.11:18443",
        "dexSha256": "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9",
        "result": BUILD / "witchweapon-online-exchange-levels-v9-test.apk",
        "report": BUILD / "兑换货架等级解锁候选包验收-v9.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-exchange-links-v8.apk",
        "sha256": "b07715a3c4a053e87f96856f55c8edf3d32d12ac6dcb76d9a570d442b698b841",
        "endpoint": "https://127.0.0.1:19443",
        "dexSha256": "024ac5e3c3bebed9e2a0b2eb5258696daef7a2c5811bddf8c080f7058f4e3a56",
        "result": BUILD / "witchweapon-online-local-staging-exchange-levels-v9.apk",
        "report": BUILD / "本地测试服兑换货架等级解锁验收-v9.json",
    },
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hashed.update(block)
    return hashed.hexdigest()


def prepare(kind: str, original_shop: bytes) -> tuple[dict[str, bytes], dict]:
    entry = SOURCE[kind]
    if sha256_file(entry["apk"]) != entry["sha256"]:
        raise ValueError("Reviewed v8 source APK changed: " + kind)
    with zipfile.ZipFile(entry["apk"]) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read(ENDPOINT) != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected endpoint: " + kind)
        if digest(apk.read(DEX)) != entry["dexSha256"]:
            raise ValueError("Network DEX changed: " + kind)
        shop_before, index_before = apk.read(SHOP_MEMBER), apk.read(INDEX)
    if digest(shop_before) != EXPECTED_SHOP_SHA256 or \
            digest(index_before) != EXPECTED_INDEX_SHA256:
        raise ValueError("Unreviewed v8 Shop bundle or bundle index")

    current_text = _csv_tree(shop_before, "Shop")[3]
    original_text = _csv_tree(original_shop, "Shop")[3]
    patched_text, count = patch_shop_level_text(current_text, original_text)
    if count != 24 or patch_shop_level_text(patched_text, original_text) != (patched_text, 0):
        raise ValueError("Expected 24 idempotent level-band changes")
    shop_after = patch_shop_level_bundle(shop_before, original_shop)
    if shop_after == shop_before or _csv_tree(shop_after, "Shop")[3] != patched_text:
        raise ValueError("Shop bundle patch failed")
    index_after = patch_index(index_before, {"/config/clientexel/shop.ab": shop_after})
    if index_after == index_before:
        raise ValueError("Shop bundle index unchanged")
    return {SHOP_MEMBER: shop_after, INDEX: index_after}, {
        "sourceApkSha256": entry["sha256"],
        "sourceEndpoint": entry["endpoint"],
        "networkDexSha256": entry["dexSha256"],
        "tieredShopRowsOpened": count,
        "shopBundleSha256": digest(shop_after),
        "bundleIndexSha256": digest(index_after),
        "runtimeValidated": False,
    }


def build_one(kind: str, replacements: dict[str, bytes], detail: dict) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-exchange-levels-v9-" + kind)
    if temp.exists():
        raise ValueError("Stale v9 temp: " + str(temp))
    try:
        signer.SOURCE = entry["apk"]
        signer.SOURCE_SHA256 = entry["sha256"]
        signer.TEMP = temp
        report = signer.build(replacements, entry["result"], entry["report"])
        verify = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                  "verify", "--print-certs"]
        before_cert = cert_digest(signer.run([*verify, entry["apk"]], signer.signer_env()))
        after_cert = cert_digest(signer.run([*verify, entry["result"]], signer.signer_env()))
        if before_cert != EXPECTED_SIGNER_SHA256 or after_cert != before_cert:
            raise ValueError("APK signer changed")
        with zipfile.ZipFile(entry["apk"]) as old, zipfile.ZipFile(entry["result"]) as new:
            for name in ("AndroidManifest.xml", "classes.dex", DEX, ENDPOINT):
                if old.read(name) != new.read(name):
                    raise ValueError("Core APK member changed: " + name)
            if any(new.read(name) != data for name, data in replacements.items()):
                raise ValueError("Signed target member differs")
        report.update(detail)
        report["signerCertificateSha256"] = after_cert
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        entry["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        sidecar = Path(str(entry["result"]) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(entry["result"]) != report["testApk"]["sha256"]:
            raise ValueError("Signed result hash differs")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-exchange-levels-v9-" + kind:
                raise ValueError("Unsafe v9 temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build two signed v9 APKs")
    args = parser.parse_args()
    if sha256_file(HERE / "patch_exchange_shop_tables.py") != EXPECTED_PATCH_SHA256:
        raise ValueError("Exchange patch changed after review")
    original_shop = ORIGINAL_SHOP.read_bytes()
    if digest(original_shop) != EXPECTED_ORIGINAL_SHA256:
        raise ValueError("Original Shop reference changed")
    prepared = {kind: prepare(kind, original_shop) for kind in SOURCE}
    if prepared["candidate"][0] != prepared["staging"][0]:
        raise ValueError("Candidate/staging game assets differ")
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_EXCHANGE_LEVELS_V9_READY", report["testApk"]["sha256"])
    else:
        print("EXCHANGE_LEVELS_V9_STATIC_OK", json.dumps(prepared["candidate"][1], sort_keys=True))


if __name__ == "__main__":
    main()
