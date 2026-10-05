"""Build two signed v8 APKs with original exchange and UI link/icon assets.

Sources are reviewed v7 production and loopback-only test APKs. Only the two
exchange tables, three UI bundles, and their bundle index are changed. This
builder does not install, deploy, or modify any server.
"""

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
from build_task_reflection_v6_apk import local_cert_base64
from patch_feature_level_gates import _csv_tree
from patch_exchange_shop_tables import (
    exchange_bundle_replacements, patch_shopbigset_text,
    patch_shopstructure_text,
)
from patch_gift_shop_tables import SHOPBIGSET_MEMBER, SHOPSTRUCTURE_MEMBER
import patch_legacy_links_and_payment_icons as ui_patch


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel")
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"
DEX = "classes2.dex"
EXPECTED_INDEX_SHA256 = "b4cb04fc9acd513e1c80078d0729ad78d396bf43656245d92bb59788cca24089"
EXPECTED_SHOP_BUNDLES = {
    SHOPSTRUCTURE_MEMBER: "20f7ddef9fac5d7bbe2519b49351f5f9a40a79c36b477e906afd8f1b8ecbe8f3",
    SHOPBIGSET_MEMBER: "fad15eec18dab32bf1fc72a8b58a1977defc549112fc68f5f131677177bf5318",
}
EXPECTED_ORIGINAL_BUNDLES = {
    SHOPSTRUCTURE_MEMBER: "edf13285af2f57c61bbf7005f614df8abcee6fad84d21ab43892ee3ccac615b5",
    SHOPBIGSET_MEMBER: "8300853579caceae36ff937d46e9355de509235a89b1d34c2364d78767b33d2b",
}
EXPECTED_PATCH_SCRIPTS = {
    "patch_exchange_shop_tables.py": "2959b1cf72039d0e2bbc125927eef53b0d221415dbe2f27dadc9ec30ebb8e7d8",
    "patch_legacy_links_and_payment_icons.py": "20695618149cba1a771b63cbdcfea98cb1759272cb60c3fe693736a0d6d847b1",
}
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-sweep-param-v7-test.apk",
        "sha256": "73bcde2c97392e072c6d3d2f95ddc71e067cdc3a4d26249d56c9c3ddd02c8e1a",
        "endpoint": "https://212.192.15.11:18443",
        "dexSha256": "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9",
        "result": BUILD / "witchweapon-online-exchange-links-v8-test.apk",
        "report": BUILD / "兑换商店与界面入口候选包验收-v8.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-sweep-param-v7.apk",
        "sha256": "17273ccd12d9900352eb563c52569b8733263e4a2e7ad614b815beb60f3a0bf1",
        "endpoint": "https://127.0.0.1:19443",
        "dexSha256": "024ac5e3c3bebed9e2a0b2eb5258696daef7a2c5811bddf8c080f7058f4e3a56",
        "result": BUILD / "witchweapon-online-local-staging-exchange-links-v8.apk",
        "report": BUILD / "本地测试服兑换商店与界面入口验收-v8.json",
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


def reviewed_reference() -> dict[str, bytes]:
    for script, expected in EXPECTED_PATCH_SCRIPTS.items():
        if sha256_file(HERE / script) != expected:
            raise ValueError("Patch source changed after review: " + script)
    result = {}
    for member, expected in EXPECTED_ORIGINAL_BUNDLES.items():
        raw = (ORIGINAL / Path(member).name).read_bytes()
        if digest(raw) != expected:
            raise ValueError("Original exchange reference changed: " + member)
        result[member] = raw
    return result


def count_exchange_changes(before: dict[str, bytes], original: dict[str, bytes]) -> dict[str, int]:
    changes = {}
    for member, asset, patch, wanted in (
            (SHOPSTRUCTURE_MEMBER, "ShopStructure", patch_shopstructure_text, 3),
            (SHOPBIGSET_MEMBER, "ShopBigSet", patch_shopbigset_text, 9)):
        current_text = _csv_tree(before[member], asset)[3]
        original_text = _csv_tree(original[member], asset)[3]
        after, count = patch(current_text, original_text)
        if count != wanted or patch(after, original_text) != (after, 0):
            raise ValueError("Exchange text patch coverage changed: " + asset)
        changes[asset] = count
    return changes


def prepare(kind: str, original: dict[str, bytes], cert_base64: bytes):
    entry = SOURCE[kind]
    if sha256_file(entry["apk"]) != entry["sha256"]:
        raise ValueError("Reviewed v7 source APK changed: " + kind)
    with zipfile.ZipFile(entry["apk"]) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read(ENDPOINT) != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected v7 endpoint: " + kind)
        dex = apk.read(DEX)
        if digest(dex) != entry["dexSha256"]:
            raise ValueError("Network DEX changed: " + kind)
        if kind == "staging" and cert_base64 not in dex:
            raise ValueError("Staging certificate pin missing")
        index = apk.read(INDEX)
        if digest(index) != EXPECTED_INDEX_SHA256:
            raise ValueError("Unreviewed v7 bundle index")
        current = {name: apk.read(name) for name in
                   (*EXPECTED_SHOP_BUNDLES, *ui_patch.EXPECTED_BUNDLES)}
    for name, expected in {**EXPECTED_SHOP_BUNDLES,
                           **ui_patch.EXPECTED_BUNDLES}.items():
        if digest(current[name]) != expected:
            raise ValueError("Unreviewed v7 target bundle: " + name)

    exchange_counts = count_exchange_changes(current, original)
    exchange = exchange_bundle_replacements(
        lambda name: current[name], lambda name: original[name])
    ui = ui_patch.patch_bundles({name: current[name] for name in ui_patch.EXPECTED_BUNDLES})
    replacements = {**exchange, **ui}
    if set(replacements) != set(current):
        raise ValueError("Exchange and UI patch target set changed")
    for name, data in replacements.items():
        if data == current[name]:
            raise ValueError("Target bundle unchanged: " + name)
    mapping = {}
    for name, data in replacements.items():
        prefix = "assets/assetbundle"
        if not name.startswith(prefix):
            raise ValueError("Unexpected bundle path: " + name)
        mapping[name[len(prefix):]] = data
    replacements[INDEX] = patch_index(index, mapping)
    detail = {
        "sourceApkSha256": entry["sha256"],
        "sourceEndpoint": entry["endpoint"],
        "networkDexSha256": entry["dexSha256"],
        "exchangeRowsRestored": exchange_counts,
        "patchedBundleSha256": {name: digest(data) for name, data in replacements.items()
                                if name != INDEX},
        "bundleIndexSha256": digest(replacements[INDEX]),
        "changedUnityObjects": {
            "UIActivities.lua": "Wiki URL on original button",
            "LoginMain": ["WechatContainner", "WeixinRegistBtn"],
            "NewShopPanel": ["zhifubao", "weixin"],
        },
    }
    return replacements, detail


def build_one(kind: str, replacements: dict[str, bytes], detail: dict) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-exchange-links-v8-" + kind)
    if temp.exists():
        raise ValueError("Stale v8 build temp: " + str(temp))
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
            raise ValueError("APK signing identity changed")
        with zipfile.ZipFile(entry["apk"]) as old, zipfile.ZipFile(entry["result"]) as new:
            for name in ("AndroidManifest.xml", "classes.dex", DEX, ENDPOINT,
                         "assets/assetbundle/lua/lua_projx_patch.ab",
                         "assets/assetbundle/config/clientexel/instancemoblist.ab",
                         "assets/assetbundle/config/clientexel/dictionarystatic.ab",
                         "assets/assetbundle/scene/loginfromal.ab"):
                if old.read(name) != new.read(name):
                    raise ValueError("Unrelated client payload changed: " + name)
            for name, data in replacements.items():
                if new.read(name) != data:
                    raise ValueError("Signed patched member differs: " + name)
        report.update(detail)
        report["signerCertificateSha256"] = after_cert
        report["runtimeValidated"] = False
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        entry["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        sidecar = Path(str(entry["result"]) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(entry["result"]) != report["testApk"]["sha256"]:
            raise ValueError("Final signed APK differs from verification record")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-exchange-links-v8-" + kind:
                raise ValueError("Unsafe v8 temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign both v8 APKs")
    args = parser.parse_args()
    original = reviewed_reference()
    cert = local_cert_base64()
    prepared = {kind: prepare(kind, original, cert) for kind in SOURCE}
    for name in prepared["candidate"][0]:
        if prepared["candidate"][0][name] != prepared["staging"][0][name]:
            raise ValueError("Production/test v8 game asset diverged: " + name)
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_EXCHANGE_LINKS_V8_READY", report["testApk"]["sha256"])
    else:
        print("EXCHANGE_LINKS_V8_STATIC_OK", json.dumps(prepared["candidate"][1], sort_keys=True))


if __name__ == "__main__":
    main()
