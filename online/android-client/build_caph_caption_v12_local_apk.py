"""Build only an isolated local v12 APK with the stale C.A.P.H caption hidden."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_online_apk import patch_index
import patch_caph_open_shop_caption as caption


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
SOURCE = BUILD / "witchweapon-online-local-staging-activity-long-preflight-v11.apk"
SOURCE_SHA256 = "82da77fbdc13c47ecab700f4e6d42fc58bc7f11e8bc6a68702c6bdd587047b83"
INDEX = "assets/m.assets_list.txt"
INDEX_SHA256 = "32413681f1da729590ee2c3fae5f4cf5c7a68158bb5eee3b76a748a970e2dd26"
ENDPOINT = "assets/online_endpoint.txt"
RESULT = BUILD / "witchweapon-online-local-staging-caph-caption-v12.apk"
REPORT = BUILD / "本地测试服CAPH商店提示修正验收-v12.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-caph-caption-v12-local")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(block)
    return hashed.hexdigest()


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or sha256_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed local v11 APK missing or changed")
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate APK member")
        if apk.read(ENDPOINT) != b"https://127.0.0.1:19443\n":
            raise ValueError("This build must only point at the local test service")
        index = apk.read(INDEX)
        if digest(index) != INDEX_SHA256:
            raise ValueError("Unreviewed bundle index")
        bundle = caption.patch_bundle(apk.read(caption.MEMBER))
    return {
        caption.MEMBER: bundle,
        INDEX: patch_index(index, {
            "/assets/resources/ui/prefab/vip/vippanel.ab": bundle,
        }),
    }


def build(replacements: dict[str, bytes]) -> dict:
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise ValueError("v12 output or temporary build already exists")
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
                raise ValueError("Signed C.A.P.H payload differs")
        report.update({
            "purpose": "Hide obsolete special-action-closed caption while keeping original C.A.P.H shop button and closed ActOpen state",
            "endpoint": "https://127.0.0.1:19443",
            "sourceApkSha256": SOURCE_SHA256,
            "bundleSha256": digest(replacements[caption.MEMBER]),
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
            if TEMP.resolve().parent != Path(r"D:\Environment\Android\temp").resolve():
                raise ValueError("Unsafe build-temp cleanup target")
            shutil.rmtree(TEMP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    replacements = prepare()
    if not args.build:
        print("CAPH_CAPTION_V12_STATIC_OK", digest(replacements[caption.MEMBER]),
              digest(replacements[INDEX]))
        return
    report = build(replacements)
    print("CAPH_CAPTION_V12_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
