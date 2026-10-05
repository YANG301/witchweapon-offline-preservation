"""Build a separate signed APK with the original three-card activities carousel.

Only UIActivities.lua and MainScenePanelAdd.lua inside lua_projx_ui.ab plus its
m.assets_list entry change. The original lobby, sign-in and mail prefabs remain untouched. Deploy the APK
before enabling ActivityBanner on a server, or old expired adverts may appear.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run, sha256
from build_online_apk import patch_index
import patch_uiactivities_banner


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build" / "witchweapon-online-original-ui-chat-relay-api24-level1-v7-diagnostic.apk"
SOURCE_SHA256 = "475f16948445132e68950656071e927676f2b00671f0f2bd85bffb93ee0e803b"
OUT = Path(r"D:\Project\魔女兵器在线版\构建")
RESULT = OUT / "witchweapon-online-original-ui-activity-banner-v3-test.apk"
REPORT = OUT / "原版活动轮播候选包验收-v3.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-activity-banner-v3")
BUNDLE = "assets/assetbundle/lua/lua_projx_ui.ab"
INDEX = "assets/m.assets_list.txt"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def prepare():
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned installed diagnostic APK is missing or changed")
    for tool in (JAVA, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar", KEY):
        if not tool.is_file():
            raise ValueError("Portable signing dependency missing: " + str(tool))
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or BUNDLE not in names or INDEX not in names:
            raise ValueError("Unexpected source APK member set")
        lua = patch_uiactivities_banner.patch(source.read(BUNDLE))
        index = patch_index(source.read(INDEX), {"/lua/lua_projx_ui.ab": lua})
    return {BUNDLE: lua, INDEX: index}


def verify_payload(apk_path: Path, replacements: dict[str, bytes]):
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(apk_path) as built:
        old = {name for name in source.namelist() if not SIGNATURE.fullmatch(name)}
        new = {name for name in built.namelist() if not SIGNATURE.fullmatch(name)}
        if old != new or len(built.namelist()) != len(set(built.namelist())):
            raise ValueError("Signed APK member set differs")
        for name, expected in replacements.items():
            if built.read(name) != expected:
                raise ValueError("Patched payload differs: " + name)
        unchanged = 0
        for name in old - set(replacements):
            a = source.getinfo(name)
            b = built.getinfo(name)
            if (a.file_size, a.CRC, a.compress_size) != (b.file_size, b.CRC, b.compress_size):
                raise ValueError("Unrelated APK member metadata differs: " + name)
            unchanged += 1
    return unchanged


def build(replacements: dict[str, bytes]):
    OUT.mkdir(parents=True, exist_ok=True)
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned output already exists")
    TEMP.mkdir(parents=True, exist_ok=True)
    unsigned = TEMP / "unsigned.apk"
    aligned = TEMP / "aligned.apk"
    candidate = TEMP / "signed.apk"
    if any(path.exists() for path in (unsigned, aligned, candidate)):
        raise ValueError("Stale build intermediate exists")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(unsigned, "x", allowZip64=False) as target:
        for info in source.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in replacements:
                target.writestr(copy.copy(info), replacements[info.filename])
            else:
                copy_compressed_entry(source, target, info)
    run([TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
         "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
         "--out", candidate, aligned], env)
    return finalize(replacements)


def finalize(replacements: dict[str, bytes]):
    OUT.mkdir(parents=True, exist_ok=True)
    candidate = TEMP / "signed.apk"
    if not candidate.is_file() or RESULT.exists() or REPORT.exists():
        raise ValueError("Signed candidate missing or final output already exists")
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    signature = run([*signer, "verify", "--verbose", candidate], env)
    alignment = run([TOOLS / "zipalign.exe", "-c", "-p", "4", candidate])
    unchanged = verify_payload(candidate, replacements)
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned source APK changed during build")
    report = {
        "status": "signed_static_validation_only",
        "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256},
        "testApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                    "sha256": sha256(candidate)},
        "changedPayloadMembers": sorted(replacements),
        "unchangedPayloadMembersCheckedByZipMetadata": unchanged,
        "sourceUnityTextAssetSha256": patch_uiactivities_banner.ORIGINAL_TEXT_ASSET_SHA256,
        "sourceDailyGateTextAssetSha256": patch_uiactivities_banner.ORIGINAL_MAIN_ASSET_SHA256,
        "originalCarousel": True,
        "cardDestinations": ["UIAnnouncement", "MAIL_SCENE", "UIActivitiesReward(26)"],
        "dailyTaskVisibleFromLevel": 1,
        "firstOpenDayBoundary": "UTC+08:00",
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "runtimeValidated": False,
    }
    # The controlled build intermediates live on D: while user-facing APKs
    # belong on the actual desktop (E:), so os.replace cannot cross volumes.
    shutil.copyfile(candidate, RESULT)
    sidecar = Path(str(candidate) + ".idsig")
    if sidecar.is_file():
        shutil.copyfile(sidecar, Path(str(RESULT) + ".idsig"))
    if sha256(RESULT) != report["testApk"]["sha256"]:
        raise ValueError("Desktop APK differs from signed candidate")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--check", action="store_true")
    choice.add_argument("--build", action="store_true")
    choice.add_argument("--finalize", action="store_true",
                        help="Verify/copy an already signed candidate after a cross-volume interruption")
    args = parser.parse_args()
    replacements = prepare()
    if args.check:
        print("ACTIVITY_BANNER_STATIC_CHECK_OK",
              hashlib.sha256(replacements[BUNDLE]).hexdigest())
    elif args.build:
        report = build(replacements)
        print("ACTIVITY_BANNER_APK_BUILT", report["testApk"]["sha256"], RESULT)
    else:
        report = finalize(replacements)
        print("ACTIVITY_BANNER_APK_FINALIZED", report["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
