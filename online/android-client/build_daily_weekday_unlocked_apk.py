"""Build a separately signed original-UI APK with all six daily sets open every day.

Only the two original libil2cpp.so ABI members change. The patch returns
true from the menu and pre-battle weekday predicates; all Unity asset bundles,
daily attempt limits, stage definitions, and reward records are carried over
unchanged from the pinned priced-draw APK. No install or deployment occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from patch_daily_weekday_unlocked import METHODS, RETURN_TRUE, patch_daily_weekday
from patch_chapter_level_up_duplicates import _PROFILES, _file_offset, _load_segments


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-priced-draw-v1.apk"
SOURCE_SHA256 = "3aaa032145e29fdadc8fef6a39d381a346fcf1f2316aa80d37ad32fcfd0c9904"
SOURCE_LIB_SHA256 = {
    "arm64-v8a": "54f9957290d03abde10110fcf1cfa673e15802d1259ed071a81b58681493273c",
    "armeabi-v7a": "b4f67c30e36878a9ab45c1e29bd8d068dff46d2773a08ba9e7522a7f267e09ae",
}
RESULT = HERE / "build/witchweapon-online-original-ui-daily-all-week-v1.apk"
REPORT = HERE / "build/原版日常全周开放候选包验收.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-daily-all-week"


def member(abi: str) -> str:
    return "lib/" + abi + "/libil2cpp.so"


def changed_offsets(original: bytes, patched: bytes, abi: str) -> list[int]:
    """Verify that no byte outside the two 8-byte method entries changed."""
    if len(original) != len(patched):
        raise ValueError("Native library size changed: " + abi)
    offsets = sorted(_file_offset(_load_segments(original, _PROFILES[abi]), m.rva)
                     for m in METHODS[abi])
    cursor = 0
    for offset in offsets:
        if original[cursor:offset] != patched[cursor:offset]:
            raise ValueError("Unrelated native bytes changed before weekday method")
        if patched[offset:offset + 8] != RETURN_TRUE[abi]:
            raise ValueError("Weekday return instruction differs")
        cursor = offset + 8
    if original[cursor:] != patched[cursor:]:
        raise ValueError("Unrelated native bytes changed after weekday method")
    return offsets


def prepare() -> tuple[dict[str, bytes], dict[str, list[int]]]:
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned priced-draw APK is missing or changed")
    changes = {}
    offsets = {}
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Source APK contains duplicate members")
        for abi, expected_sha in SOURCE_LIB_SHA256.items():
            name = member(abi)
            if name not in names:
                raise ValueError("Source APK lacks " + name)
            original = source.read(name)
            if hashlib.sha256(original).hexdigest() != expected_sha:
                raise ValueError("Pinned native library changed: " + abi)
            patched, count = patch_daily_weekday(original, abi)
            if count != 2:
                raise ValueError("Expected exactly two unpatched weekday methods: " + abi)
            offsets[abi] = changed_offsets(original, patched, abi)
            again, second_count = patch_daily_weekday(patched, abi)
            if again != patched or second_count != 0:
                raise ValueError("Native weekday patch is not idempotent")
            changes[name] = patched
    if set(changes) != {member(abi) for abi in METHODS}:
        raise ValueError("Unexpected daily weekday change set")
    return changes, offsets


def verify_signed_payload(changes: dict[str, bytes]) -> tuple[int, str]:
    signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
    original_cert = cert_digest(base.run(
        [*signer, "verify", "--print-certs", SOURCE], base.signer_env()))
    result_cert = cert_digest(base.run(
        [*signer, "verify", "--print-certs", RESULT], base.signer_env()))
    if original_cert != result_cert:
        raise ValueError("APK signing certificate changed")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(RESULT) as built:
        original_names = {n for n in source.namelist() if not base.SIGNATURE.fullmatch(n)}
        built_names = {n for n in built.namelist() if not base.SIGNATURE.fullmatch(n)}
        if original_names != built_names or len(built.namelist()) != len(set(built.namelist())):
            raise ValueError("APK payload member inventory changed")
        for name, expected in changes.items():
            if built.read(name) != expected:
                raise ValueError("Patched native member differs: " + name)
        untouched = original_names - changes.keys()
        for name in untouched:
            old, new = source.getinfo(name), built.getinfo(name)
            if (old.file_size, old.CRC, old.compress_size) != (
                    new.file_size, new.CRC, new.compress_size):
                raise ValueError("Unrelated APK payload changed: " + name)
        for name in ("AndroidManifest.xml", "classes.dex", "classes2.dex",
                     "assets/m.assets_list.txt"):
            if source.read(name) != built.read(name):
                raise ValueError("Original application or asset index changed: " + name)
    return len(untouched), result_cert


def build(changes: dict[str, bytes], offsets: dict[str, list[int]]) -> dict:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned daily candidate already exists")
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA256, TEMP
    report = base.build(changes, RESULT, REPORT)
    untouched, certificate = verify_signed_payload(changes)
    for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                  "preservesV4TaskItemPatch", "nativeRefreshClass"):
        report.pop(stale, None)
    report.update(
        purpose="Six original daily sets 3020001..3020006 open every weekday",
        changedNativeMethods=[m.name for m in METHODS["arm64-v8a"]],
        nativeMethodRvas={abi: [f"0x{m.rva:X}" for m in methods]
                          for abi, methods in METHODS.items()},
        changedFileOffsets={abi: [f"0x{offset:X}" for offset in values]
                            for abi, values in offsets.items()},
        changedBytesPerAbi=16,
        untouchedPayloadMembersChecked=untouched,
        sameSignerCertificateSha256=certificate,
        dailyAttemptLimitsUnchanged=True,
        allUnityAssetBundlesUnchanged=True,
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
        raise ValueError("Unexpected previous daily-build temporary directory")
    try:
        changes, offsets = prepare()
        if args.build:
            report = build(changes, offsets)
            print("DAILY_ALL_WEEK_APK_READY", report["testApk"]["sha256"], RESULT)
        else:
            print("DAILY_ALL_WEEK_PATCH_CHECK_OK", offsets)
    finally:
        if TEMP.exists():
            if TEMP.resolve().parent != TEMP_PARENT.resolve() or \
                    TEMP.resolve().name != "witch-online-daily-all-week":
                raise ValueError("Unsafe daily-build temporary cleanup")
            shutil.rmtree(TEMP)


if __name__ == "__main__":
    main()
