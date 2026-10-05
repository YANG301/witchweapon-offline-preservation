"""Sign the corrected ordinary-draw bridge over the pinned all-week APK.

Only classes2.dex changes. The original game data, restored draw prices and
both weekday-unlock native patches come from the all-week source unchanged.
This builder never installs an APK or contacts the game server.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_online_apk as adapter
import build_priced_draw_apk as priced
import build_original_ui_quest_refresh_v6_apk as base
from build_original_ui_lottery_lua_input_probe_apk import cert_digest


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-daily-all-week-v1.apk"
SOURCE_SHA256 = "fb9deb79839e758de0dc974ae430be71fe84699535f0e7f9a80ecfd979c593aa"
OLD_DEX_SHA256 = "c2cc5a8dd2213fb2217a3044a42332478aa0b5fbae481f480cbdd722866f0ae4"
RESULT = HERE / "build/witchweapon-online-original-ui-draw-retry-all-week-v2.apk"
REPORT = HERE / "build/原版抽卡连续点击修复与全周日常候选包验收.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-draw-retry-all-week"
DEX = "classes2.dex"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned all-week source APK is missing or changed")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(priced.SOURCE) as original:
        if len(source.namelist()) != len(set(source.namelist())):
            raise ValueError("Source APK has duplicate members")
        old = source.read(DEX)
        baseline = original.read(DEX)
        if sha256(old) != OLD_DEX_SHA256 or sha256(baseline) != priced.SOURCE_DEX_SHA256:
            raise ValueError("Pinned draw bridge baseline DEX changed")
    priced.TEMP = TEMP / "bridge-build"
    revised = priced.compile_bridge(baseline)
    if revised == old or set(adapter.dex_classes(revised)) != set(adapter.dex_classes(old)):
        raise ValueError("Bridge did not preserve the inherited DEX class inventory")
    return {DEX: revised}


def verify_signed_payload(replacements: dict[str, bytes]) -> tuple[int, str]:
    signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
    before = cert_digest(base.run(
        [*signer, "verify", "--print-certs", SOURCE], base.signer_env()))
    after = cert_digest(base.run(
        [*signer, "verify", "--print-certs", RESULT], base.signer_env()))
    if before != after:
        raise ValueError("APK signing certificate changed")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(RESULT) as built:
        old_names = {n for n in source.namelist() if not base.SIGNATURE.fullmatch(n)}
        new_names = {n for n in built.namelist() if not base.SIGNATURE.fullmatch(n)}
        if old_names != new_names or len(built.namelist()) != len(set(built.namelist())):
            raise ValueError("APK payload member inventory changed")
        if built.read(DEX) != replacements[DEX]:
            raise ValueError("Signed bridge DEX differs from compiled DEX")
        for member in ("AndroidManifest.xml", "classes.dex", "assets/m.assets_list.txt",
                       "assets/assetbundle/config/clientexel/constant.ab",
                       "assets/assetbundle/lua/lua.ab", "lib/arm64-v8a/libil2cpp.so",
                       "lib/armeabi-v7a/libil2cpp.so"):
            if source.read(member) != built.read(member):
                raise ValueError("Original or all-week payload changed: " + member)
        untouched = old_names - replacements.keys()
        for name in untouched:
            old, new = source.getinfo(name), built.getinfo(name)
            if (old.file_size, old.CRC, old.compress_size) != (
                    new.file_size, new.CRC, new.compress_size):
                raise ValueError("Unrelated payload member changed: " + name)
    return len(untouched), before


def build(replacements: dict[str, bytes]) -> dict:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned output already exists")
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA256, TEMP / "apk-build"
    report = base.build(replacements, RESULT, REPORT)
    untouched, certificate = verify_signed_payload(replacements)
    for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                  "preservesV4TaskItemPatch", "nativeRefreshClass"):
        report.pop(stale, None)
    report.update(
        purpose="Ordinary draws accept distinct completed clicks and preserve uncertain retries",
        drawRoutes=["/draw/gold/single", "/draw/gold/ten",
                    "/draw/rmb/single", "/draw/rmb/ten"],
        changedPayloadMembers=[DEX],
        untouchedPayloadMembersChecked=untouched,
        sameSignerCertificateSha256=certificate,
        allWeekDailyNativePatchPreserved=True,
        originalDrawPricesPreserved=True,
        guideDrawUnchanged=True,
        runtimeValidated=False,
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign candidate; never install")
    args = parser.parse_args()
    if TEMP.exists():
        raise ValueError("Unexpected previous draw-retry build directory")
    try:
        replacements = prepare()
        if args.build:
            report = build(replacements)
            print("DRAW_RETRY_ALL_WEEK_APK_READY", report["testApk"]["sha256"], RESULT)
        else:
            print("DRAW_RETRY_ALL_WEEK_PATCH_CHECK_OK", sha256(replacements[DEX]))
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or resolved.name != "witch-online-draw-retry-all-week":
                raise ValueError("Unsafe draw-retry build cleanup")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
