"""Sign v10 APKs from v9 with original 7# link and runtime payment-icon fixes."""

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
import patch_payment_icons_runtime as payment
import patch_special_shop_activity_links as activity


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"
DEX = "classes2.dex"
EXPECTED_INDEX_SHA256 = "8dbc9d24ce5aec5a488c158b91438e994a83d0da7590829c91a415ddeb4267a2"
EXPECTED_SCRIPT_SHA256 = {
    "patch_special_shop_activity_links.py": "3140540aca77b4acf01157018c8f6417de963169a267f122e51b9abc9fdbee8a",
    "patch_payment_icons_runtime.py": "ccd952dbf6a8f53a30068fbbdd36c970c64540ff22bf465faef398de57965626",
}
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-exchange-levels-v9-test.apk",
        "sha256": "a55afa61de302263463918da0201fc58dd4a1ae61f671b78475314470baf8d02",
        "endpoint": "https://212.192.15.11:18443",
        "dexSha256": "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9",
        "result": BUILD / "witchweapon-online-activity-payment-v10-test.apk",
        "report": BUILD / "活动入口与支付图标候选包验收-v10.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-exchange-levels-v9.apk",
        "sha256": "2dabf4f3363366e31595bf6298bd4f68da279d44d78b3d638f0de3f0437b9aed",
        "endpoint": "https://127.0.0.1:19443",
        "dexSha256": "024ac5e3c3bebed9e2a0b2eb5258696daef7a2c5811bddf8c080f7058f4e3a56",
        "result": BUILD / "witchweapon-online-local-staging-activity-payment-v10.apk",
        "report": BUILD / "本地测试服活动入口与支付图标验收-v10.json",
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


def prepare(kind: str) -> tuple[dict[str, bytes], dict]:
    entry = SOURCE[kind]
    if sha256_file(entry["apk"]) != entry["sha256"]:
        raise ValueError("Reviewed v9 source APK changed: " + kind)
    with zipfile.ZipFile(entry["apk"]) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read(ENDPOINT) != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected endpoint: " + kind)
        if digest(apk.read(DEX)) != entry["dexSha256"]:
            raise ValueError("Network DEX changed: " + kind)
        before_index = apk.read(INDEX)
        if digest(before_index) != EXPECTED_INDEX_SHA256:
            raise ValueError("Unreviewed v9 bundle index")
        targets = {activity.MEMBER, *payment.EXPECTED_BUNDLES}
        before = {name: apk.read(name) for name in targets}

    replacements = {activity.MEMBER: activity.patch_bundle(before[activity.MEMBER])}
    replacements.update(payment.patch_bundles(
        {name: before[name] for name in payment.EXPECTED_BUNDLES}))
    if set(replacements) != targets or any(replacements[name] == before[name]
                                              for name in replacements):
        raise ValueError("Unexpected v10 target bundle set")
    prefix = "assets/assetbundle"
    index_mapping = {name[len(prefix):]: data for name, data in replacements.items()
                     if name.startswith(prefix)}
    if len(index_mapping) != 4:
        raise ValueError("Unexpected v10 asset path")
    replacements[INDEX] = patch_index(before_index, index_mapping)
    if replacements[INDEX] == before_index:
        raise ValueError("Bundle index unchanged")
    return replacements, {
        "sourceApkSha256": entry["sha256"],
        "sourceEndpoint": entry["endpoint"],
        "networkDexSha256": entry["dexSha256"],
        "changedUnityResources": [
            "UIActivities.lua: 7# overview uses restored ShopSet 44000070",
            "NewShopPanel, ShopPanel, LoginMain: legacy payment/login marks hidden",
        ],
        "patchedBundleSha256": {name: digest(data) for name, data in replacements.items()
                                if name != INDEX},
        "bundleIndexSha256": digest(replacements[INDEX]),
        "runtimeValidated": False,
    }


def build_one(kind: str, replacements: dict[str, bytes], detail: dict) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-activity-payment-v10-" + kind)
    if temp.exists():
        raise ValueError("Stale v10 temp: " + str(temp))
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
                    resolved.name != "witch-online-activity-payment-v10-" + kind:
                raise ValueError("Unsafe v10 temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build two signed v10 APKs")
    args = parser.parse_args()
    for name, expected in EXPECTED_SCRIPT_SHA256.items():
        if sha256_file(HERE / name) != expected:
            raise ValueError("Patch script changed after review: " + name)
    prepared = {kind: prepare(kind) for kind in SOURCE}
    if prepared["candidate"][0] != prepared["staging"][0]:
        raise ValueError("Candidate/staging game assets differ")
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_ACTIVITY_PAYMENT_V10_READY", report["testApk"]["sha256"])
    else:
        print("ACTIVITY_PAYMENT_V10_STATIC_OK",
              json.dumps(prepared["candidate"][1], sort_keys=True))


if __name__ == "__main__":
    main()
