"""Build the isolated local v14 client from the pinned v13 APK.

Only the original shop tables and two reviewed Lua TextAssets change. The
endpoint stays on the local HTTPS test service; no production APK is produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_online_apk import patch_index
import patch_resource_shop_tables as resources
import patch_virtual_yuan_display as yuan
import patch_exchange_counter_ui as counter
import patch_hide_gift_duplicate_diamond as gift_counter


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SOURCE = BUILD / "witchweapon-online-local-staging-exchange-shared-v13.apk"
SOURCE_SHA256 = "ceaf9eadc117116386ff439b583a92afc088ff58cc1790f79b49a3f8ac92fe3b"
ORIGINAL_ASSETS = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程")
RESULT = BUILD / "witchweapon-online-local-staging-shop-policy-v14.apk"
REPORT = BUILD / "本地测试服商店与兑换显示验收-v14.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-shop-policy-v14-local"
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"


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
        raise ValueError("Pinned v13 local APK is absent or changed")
    with zipfile.ZipFile(SOURCE) as source:
        if len(source.namelist()) != len(set(source.namelist())):
            raise ValueError("Duplicate APK member")
        if source.read(ENDPOINT) != b"https://127.0.0.1:19443\n":
            raise ValueError("Client is not locked to the isolated local test service")
        changed = resources.replacements(
            source.read,
            lambda member: (ORIGINAL_ASSETS / member).read_bytes(),
        )
        if len(changed) != 5:
            raise ValueError("Expected five reviewed shop configuration bundles")
        original_lua = source.read(yuan.MEMBER)
        changed[yuan.MEMBER] = gift_counter.patch(
            counter.patch_bundle(yuan.patch(original_lua))
        )
        if changed[yuan.MEMBER] == original_lua:
            raise ValueError("Shop UI Lua bundle is unchanged")
        before_index = source.read(INDEX)
        changed[INDEX] = patch_index(before_index, {
            "/" + member.removeprefix("assets/assetbundle/"): data
            for member, data in changed.items()
        })
        if changed[INDEX] == before_index:
            raise ValueError("Asset index is unchanged")
    return changed


def build(changed: dict[str, bytes]) -> dict:
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise ValueError("v14 output or temporary build already exists")
    try:
        signer.SOURCE = SOURCE
        signer.SOURCE_SHA256 = SOURCE_SHA256
        signer.TEMP = TEMP
        report = signer.build(changed, RESULT, REPORT)
        with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(RESULT) as new:
            for member in ("AndroidManifest.xml", "classes.dex", "classes2.dex", ENDPOINT):
                if old.read(member) != new.read(member):
                    raise ValueError("Core APK member changed: " + member)
            for member, expected in changed.items():
                if new.read(member) != expected:
                    raise ValueError("Signed shop asset differs: " + member)
        report.update({
            "purpose": "Local shop categories, virtual free pricing and original exchange counters",
            "endpoint": "https://127.0.0.1:19443",
            "sourceApkSha256": SOURCE_SHA256,
            "changedBundleSha256": {
                member: digest(data) for member, data in changed.items() if member != INDEX
            },
            "bundleIndexSha256": digest(changed[INDEX]),
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
                    TEMP.resolve().name != "witch-online-shop-policy-v14-local":
                raise ValueError("Unsafe build-temp cleanup target")
            shutil.rmtree(TEMP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changed = prepare()
    if not args.build:
        print("SHOP_POLICY_V14_STATIC_OK", len(changed), digest(changed[INDEX]))
        return
    report = build(changed)
    print("SHOP_POLICY_V14_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
