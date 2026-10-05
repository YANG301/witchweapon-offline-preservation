"""Build a separate signed v4 APK with only the original task counter fixed.

The source is the already validated v3 activity APK. This changes one Lua
TextAsset in lua_projx_patch.ab and its m.assets_list entry; no v3 file is
overwritten, and this script never installs an APK or touches the server.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run, sha256
from build_online_apk import patch_index
import patch_task_item_progress


SOURCE = Path(r"D:\Project\魔女兵器在线版\构建\witchweapon-online-original-ui-activity-banner-v3-test.apk")
SOURCE_SHA256 = "39cab2099156673591c5eeebd50693168547288208959bdef1f0deaaef451be4"
OUT = Path(r"D:\Project\魔女兵器在线版\构建")
RESULT = OUT / "witchweapon-online-original-ui-task-progress-v4-test.apk"
REPORT = OUT / "原版每日任务进度候选包验收-v4.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-task-progress-v4")
BUNDLE = "assets/assetbundle/lua/lua_projx_patch.ab"
INDEX = "assets/m.assets_list.txt"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v3 source APK is missing or changed")
    for tool in (JAVA, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar", KEY):
        if not tool.is_file():
            raise ValueError("Portable signing dependency missing: " + str(tool))
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or BUNDLE not in names or INDEX not in names:
            raise ValueError("Unexpected source APK member set")
        lua = patch_task_item_progress.patch(source.read(BUNDLE))
        index = patch_index(source.read(INDEX), {"/lua/lua_projx_patch.ab": lua})
    return {BUNDLE: lua, INDEX: index}


def verify_payload(apk_path: Path, replacements: dict[str, bytes]) -> int:
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
            a, b = source.getinfo(name), built.getinfo(name)
            if (a.file_size, a.CRC, a.compress_size) != (b.file_size, b.CRC, b.compress_size):
                raise ValueError("Unrelated APK member metadata differs: " + name)
            unchanged += 1
    return unchanged


def signer_env() -> dict[str, str]:
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"
    return env


def finalize(replacements: dict[str, bytes]) -> dict[str, object]:
    candidate = TEMP / "signed.apk"
    if not candidate.is_file() or RESULT.exists() or REPORT.exists():
        raise ValueError("Signed candidate missing or final output already exists")
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    signature = run([*signer, "verify", "--verbose", candidate], signer_env())
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
        "changedUnityTextAsset": patch_task_item_progress.ASSET_NAME,
        "originalUnityTextAssetSha256": patch_task_item_progress.ORIGINAL_RAW_SHA256,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "runtimeValidated": False,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidate, RESULT)
    sidecar = Path(str(candidate) + ".idsig")
    if sidecar.is_file():
        shutil.copyfile(sidecar, Path(str(RESULT) + ".idsig"))
    if sha256(RESULT) != report["testApk"]["sha256"]:
        raise ValueError("Desktop APK differs from signed candidate")
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build(replacements: dict[str, bytes]) -> dict[str, object]:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned output already exists")
    TEMP.mkdir(parents=True, exist_ok=True)
    unsigned, aligned, candidate = (TEMP / name for name in
                                    ("unsigned.apk", "aligned.apk", "signed.apk"))
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
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
         "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
         "--out", candidate, aligned], signer_env())
    return finalize(replacements)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    mode.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    replacements = prepare()
    if args.check:
        import hashlib
        print("TASK_PROGRESS_V4_STATIC_CHECK_OK",
              hashlib.sha256(replacements[BUNDLE]).hexdigest())
        return
    report = build(replacements) if args.build else finalize(replacements)
    print("TASK_PROGRESS_V4_APK_READY", report["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
