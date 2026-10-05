"""Build the isolated v16 APK with the actually executed shop presentation hook.

This is a local test build. It uses the pinned v15 APK, adds the reviewed
Dictionary/Goods corrections, patches the active lua.ab/init.lua, and advances
the embedded asset version so an in-place installation refreshes its index.
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
import patch_embedded_asset_version as version
import patch_resource_shop_tables as resources
import patch_shop_runtime_init as init


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SOURCE = BUILD / "witchweapon-online-local-staging-shop-policy-v15.apk"
SOURCE_SHA256 = "46527f7ef00cce8fccb7777715d8595a19a1d6846b88746369959198ddec2d3a"
ORIGINAL_ASSETS = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程")
RESULT = BUILD / "witchweapon-online-local-staging-shop-runtime-v16.apk"
REPORT = BUILD / "本地测试服商店运行时验收-v16.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-shop-runtime-v16-local"
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
        raise ValueError("Pinned v15 local test APK is absent or changed")
    with zipfile.ZipFile(SOURCE) as source:
        if len(source.namelist()) != len(set(source.namelist())):
            raise ValueError("Duplicate source APK member")
        if source.read(ENDPOINT) != b"https://127.0.0.1:19443\n":
            raise ValueError("Source client is not locked to the local test service")
        changed = resources.replacements(
            source.read, lambda member: (ORIGINAL_ASSETS / member).read_bytes())
        expected_resource = {
            "assets/assetbundle/config/clientexel/dictionary.ab",
            "assets/assetbundle/config/clientexel/goods.ab",
        }
        if set(changed) != expected_resource:
            raise ValueError("Unexpected shop table delta: " + repr(sorted(changed)))
        changed[init.MEMBER] = init.patch_bundle(source.read(init.MEMBER), enabled=True)
        if changed[init.MEMBER] == source.read(init.MEMBER):
            raise ValueError("Active init.lua was not patched")
        changed.update(version.replacements(source.read))
        bundles = {"/" + member.removeprefix("assets/assetbundle/"): data
                   for member, data in changed.items()
                   if member.startswith("assets/assetbundle/")}
        changed[INDEX] = patch_index(source.read(INDEX), bundles)
        if changed[INDEX] == source.read(INDEX):
            raise ValueError("Asset index did not change")
    return changed


def build(changed: dict[str, bytes]) -> dict:
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise ValueError("v16 output or temporary build already exists")
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
                    raise ValueError("Signed payload differs: " + member)
        report.update({
            "purpose": "Local original shop names, recharge descriptions and live RMB display",
            "endpoint": "https://127.0.0.1:19443",
            "sourceApkSha256": SOURCE_SHA256,
            "changedBundleSha256": {
                member: digest(data) for member, data in changed.items()
                if member.startswith("assets/assetbundle/")
            },
            "bundleIndexSha256": digest(changed[INDEX]),
            "assetVersion": version.NEW_VERSION.decode("ascii"),
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
                    TEMP.resolve().name != "witch-online-shop-runtime-v16-local":
                raise ValueError("Unsafe build-temp cleanup target")
            shutil.rmtree(TEMP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changed = prepare()
    if not args.build:
        print("SHOP_RUNTIME_V16_STATIC_OK", len(changed), digest(changed[INDEX]))
        return
    report = build(changed)
    print("SHOP_RUNTIME_V16_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
