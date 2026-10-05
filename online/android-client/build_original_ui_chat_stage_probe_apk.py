"""Build a v8 diagnostic APK with status-only router/WS/TLS Android logs.

It retains the v7 API24 manifest, original Unity UI and Lv.1 test gate. Only
the Android adapter DEX changes; no account, token, email or message is logged.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import zipfile

import build_online_apk as adapter
import build_original_ui_xinfengzhou_apk as base


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
SOURCE = OUTPUT / "witchweapon-online-original-ui-chat-relay-api24-level1-v7-diagnostic.apk"
SOURCE_SHA256 = "475f16948445132e68950656071e927676f2b00671f0f2bd85bffb93ee0e803b"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-relay-api24-level1-v8-stage-diagnostic.apk"
REPORT = OUTPUT / "原版聊天链路阶段诊断包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-stage-v8")
DEX = "classes2.dex"
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v7 diagnostic APK is missing or changed")
    for path in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Portable Android build dependency missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())) or DEX not in apk.namelist():
            raise ValueError("Pinned v7 APK member set invalid")
        old_dex = apk.read(DEX)
    files, old_source_classes, _ = adapter.check_inputs()
    dex, new_classes = adapter.compile_dex(files, old_source_classes)
    if set(adapter.dex_classes(old_dex)) != set(new_classes):
        raise ValueError("Stage probe changed Android adapter class set")
    if dex == old_dex:
        raise ValueError("Status-only stage instrumentation was not compiled")
    return dex, len(new_classes)


def verify(path, dex):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Unexpected signed APK member set")
        if new.read(DEX) != dex:
            raise ValueError("Signed APK lost diagnostic DEX")
        unchanged = 0
        for name in sorted(old_names - {DEX}):
            with old.open(name) as before, new.open(name) as after:
                if base.stream_digest(before) != base.stream_digest(after):
                    raise ValueError("Unrelated APK member changed: " + name)
            unchanged += 1
        for critical in ("AndroidManifest.xml", "assets/offline_responses.json",
                         "assets/assetbundle/config/clientexel/constant.ab"):
            if old.read(critical) != new.read(critical):
                raise ValueError("Critical original UI/chat member changed: " + critical)
    if base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v7 APK changed during build")
    return unchanged


def build(dex, classes):
    unsigned = OUTPUT / "chat-stage-v8-unsigned.apk"
    aligned = OUTPUT / "chat-stage-v8-aligned.apk"
    candidate = OUTPUT / "chat-stage-v8-candidate.next.apk"
    staged_report = OUTPUT / "chat-stage-v8-report.next.json"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, sidecar):
        if path.exists():
            raise ValueError("Versioned v8 output/intermediate already exists: " + str(path))
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for info in old.infolist():
            if base.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == DEX:
                new.writestr(copy.copy(info), dex)
            else:
                base.copy_compressed_entry(old, new, info)
    base.run([TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    base.run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
              "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
              "--out", candidate, aligned], env)
    signature = base.run([*signer, "verify", "--verbose", "--print-certs", candidate], env)
    alignment = base.run([TOOLS / "zipalign.exe", "-c", "-p", "4", candidate])
    unchanged = verify(candidate, dex)
    report = {
        "status": "controlled_emulator_stage_diagnostic_static_validation_only",
        "source": base.record(SOURCE),
        "diagnosticApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                          "sha256": base.sha256(candidate)},
        "minSdk24OriginalUiAndLevel1GatePreserved": True,
        "changedPayloadMembers": [DEX],
        "verifiedUnchangedPayloadMembers": unchanged,
        "androidAdapterClasses": classes,
        "logcatTag": "WWChatProbe",
        "logScope": "fixed route/upgrade/TCP/TLS/status stage codes only",
        "logsCredentialsOrMessages": False,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "chatEndToEndTested": False,
        "publicUseAllowed": False,
        "diagnosticOnly": True,
    }
    staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.rename(RESULT)
    staged_report.rename(REPORT)
    unsigned.unlink()
    aligned.unlink()
    if sidecar.exists():
        sidecar.unlink()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.check == args.build:
        parser.error("choose exactly one of --check or --build")
    dex, classes = prepare()
    if args.check:
        print(json.dumps({"status": "in_memory_check_ok", "source": str(SOURCE),
                          "changedPayloadMembers": [DEX], "androidAdapterClasses": classes,
                          "apkCreated": False}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build(dex, classes), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
