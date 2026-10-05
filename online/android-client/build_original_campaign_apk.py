"""Build an upgrade-compatible APK restoring original campaign selection.

No install, emulator access, user-data clearing, or server deployment occurs.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import patch_original_campaign as patch


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-lottery-lua-input-probe-v5.apk"
SOURCE_SHA256 = "7e9711768b23d79451fac08265df3d30e28e941b738e06ef5cddd9cd5e4652ce"
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle")
RESULT = HERE / "build/witchweapon-online-original-ui-campaign-restore-v1.apk"
REPORT = HERE / "build/原版主线选关恢复候选包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-campaign-restore")
INDEX = "assets/m.assets_list.txt"
PACKAGE = "com.codex.witchweapon.online.originalui.test"
LAUNCHER = "com.shuiqinling.ww.android.LingGameActivity"


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Installed v5 base APK missing or changed")
    replacements = {}
    with zipfile.ZipFile(SOURCE) as source:
        prefix = "assets/assetbundle/"
        init_name = prefix + "lua/lua.ab"
        detail_name = prefix + "lua/lua_projx_patch.ab"
        replacements[init_name] = patch.patch_asset(source.read(init_name), "init.lua", patch.patch_init)
        original_detail = patch.extract((ORIGINAL / "lua/lua_projx_patch.ab").read_bytes(), "SelectLevelDetailPatch.lua")
        replacements[detail_name] = patch.patch_asset(source.read(detail_name), "SelectLevelDetailPatch.lua",
                                                      lambda s: patch.patch_detail(s, original_detail))
        for name, ids, delimiter in (("Instance", {"3110001003"}, ","),
                                     ("InstanceMobList", {"3110001003"}, ","),
                                     ("Dictionary", {"1311000100301", "1311000100302"}, "\t")):
            member = "config/clientexel/" + name.lower() + ".ab"
            replacements[prefix + member] = patch.restore_rows(
                source.read(prefix + member), (ORIGINAL / member).read_bytes(), name, ids, delimiter)
        replacements[INDEX] = patch_index(source.read(INDEX),
            {"/" + n[len(prefix):]: value for n, value in replacements.items()})
    return replacements


def build(replacements, finalize=False):
    if TEMP.exists():
        raise ValueError("Unexpected prior campaign build directory")
    base.SOURCE = SOURCE
    base.SOURCE_SHA256 = SOURCE_SHA256
    base.TEMP = TEMP
    try:
        if finalize:
            TEMP.mkdir(parents=True)
            report = json.loads(REPORT.read_text(encoding="utf-8"))
            if report["source"]["sha256"] != SOURCE_SHA256 or \
                    base.sha256(RESULT) != report["testApk"]["sha256"]:
                raise ValueError("Existing candidate or report changed")
            base.verify_payload(RESULT, replacements)
        else:
            report = base.build(replacements, RESULT, REPORT)
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        report["status"] = "pending_final_static_validation"
        report["changedUnityAssets"] = ["init.lua", "SelectLevelDetailPatch.lua", "Instance:3110001003",
                                       "InstanceMobList:3110001003", "Dictionary:1311000100301,1311000100302"]
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
        original_cert = cert_digest(base.run([*signer, "verify", "--print-certs", SOURCE], base.signer_env()))
        candidate_cert = cert_digest(base.run([*signer, "verify", "--print-certs", RESULT], base.signer_env()))
        if original_cert != candidate_cert:
            raise ValueError("Signing identity changed; upgrade would not preserve data")
        # aapt on Windows cannot open this project's Chinese path. A same-volume
        # hard link gives it an ASCII path without a second 1.8 GB copy.
        ascii_candidate = TEMP / "candidate-aapt.apk"
        os.link(RESULT, ascii_candidate)
        badging = base.run([base.TOOLS / "aapt.exe", "dump", "badging", ascii_candidate])
        if "package: name='" + PACKAGE + "'" not in badging or \
                "launchable-activity: name='" + LAUNCHER + "'" not in badging:
            raise ValueError("Original package or launcher changed")
        preserved = {}
        reviewed_native_fixes = {}
        with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(RESULT) as target:
            for name in source.namelist():
                if name in ("AndroidManifest.xml", "classes.dex", "classes2.dex",
                            "assets/assetbundle/config/clientexel/lessontrigger.ab") or \
                        name.startswith("lib/"):
                    expected = hashlib.sha256(source.read(name)).hexdigest()
                    actual = hashlib.sha256(target.read(name)).hexdigest()
                    if actual != expected:
                        if name not in ("lib/armeabi-v7a/libil2cpp.so", "lib/arm64-v8a/libil2cpp.so"):
                            raise ValueError("Critical inherited payload changed: " + name)
                        from patch_chapter_level_up_duplicates import patch_level_up_dictionary
                        patched, count = patch_level_up_dictionary(source.read(name), name.split('/')[1])
                        if count != 19 or hashlib.sha256(patched).hexdigest() != actual:
                            raise ValueError("Native change differs from reviewed level-up fix: " + name)
                        reviewed_native_fixes[name] = dict(sourceSha256=expected, sha256=actual,
                                                          levelUpDictionaryCallsites=count)
                    else:
                        preserved[name] = expected
        report.update({
            "status": "signed_static_validation_only",
            "restoresOriginalChapterAndDifficultyControls": True,
            "preservesDataOnSamePackageUpgrade": True,
            "signerCertificateSha256": candidate_cert,
            "criticalInheritedPayloadSha256": preserved,
            "reviewedNativeFixes": reviewed_native_fixes,
            "demoMazeMigration": "pending independent original maze route; no longer replaces stage 1-3",
            "mazeCheckpointStage": 3130001026,
            "chapter16MissingMobData": "not added; server must keep unavailable",
            "removedReadOnlyLotteryLuaProbe": True,
            "runtimeValidated": False,
        })
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r"D:\Environment\Android\temp").resolve() or resolved.name != "witch-online-campaign-restore":
                raise ValueError("Unsafe temporary cleanup path")
            shutil.rmtree(resolved)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--finalize", action="store_true",
                      help="Verify an existing signed candidate without rebuilding")
    args = parser.parse_args()
    replacements = prepare()
    if args.check:
        print("ORIGINAL_CAMPAIGN_PATCH_CHECK_OK", len(replacements), "APK members")
        return
    report = build(replacements, finalize=args.finalize)
    print("ORIGINAL_CAMPAIGN_APK_READY", report["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
