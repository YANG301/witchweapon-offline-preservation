"""Build an isolated Lv.1-gate diagnostic APK from the pinned API24 relay v6.

Only current channel 25 chat visibility/speech levels change. This package is
for an existing Lv.5 account to test the real HTTPS/WSS gateway in one emulator.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import zipfile

import build_original_ui_chat_level_probe_apk as levels
import build_original_ui_xinfengzhou_apk as base
import probe_original_chat_assets as probe


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
SOURCE = OUTPUT / "witchweapon-online-original-ui-chat-relay-api24-v6-test.apk"
SOURCE_SHA256 = "3ea37b4db7f1a80ec0fc77716e78a4424442e29bb60c4330424bd8266429bc61"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-relay-api24-level1-v7-diagnostic.apk"
REPORT = OUTPUT / "原版聊天公网等级诊断包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-level1-relay-v7")
BUNDLE = levels.BUNDLE
INDEX = probe.INDEX
CHANGED = {BUNDLE, INDEX}
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned API24 v6 APK is missing or changed")
    for path in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Portable Android build dependency missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())) or not CHANGED.issubset(apk.namelist()):
            raise ValueError("Pinned v6 APK member set invalid")
        old_bundle = apk.read(BUNDLE)
        old_index = apk.read(INDEX)
    bundle = levels.patch_bundle(old_bundle)
    index = probe.base.patch_index(old_index, {"/config/clientexel/constant.ab": bundle})
    if bundle == old_bundle or index == old_index:
        raise ValueError("Diagnostic level bundle or index did not change")
    return {BUNDLE: bundle, INDEX: index}


def verify(path, prepared):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Unexpected signed APK member set")
        for name in CHANGED:
            if new.read(name) != prepared[name]:
                raise ValueError("Signed APK lost diagnostic change: " + name)
        unchanged = 0
        for name in sorted(old_names - CHANGED):
            with old.open(name) as before, new.open(name) as after:
                if base.stream_digest(before) != base.stream_digest(after):
                    raise ValueError("Unrelated APK member changed: " + name)
            unchanged += 1
        for critical in ("AndroidManifest.xml", "classes2.dex", probe.FIXTURES):
            if old.read(critical) != new.read(critical):
                raise ValueError("Original UI chat relay critical member changed: " + critical)
    if base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v6 APK changed during build")
    return unchanged


def build(prepared):
    unsigned = OUTPUT / "chat-level1-relay-v7-unsigned.apk"
    aligned = OUTPUT / "chat-level1-relay-v7-aligned.apk"
    candidate = OUTPUT / "chat-level1-relay-v7-candidate.next.apk"
    staged_report = OUTPUT / "chat-level1-relay-v7-report.next.json"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, sidecar):
        if path.exists():
            raise ValueError("Versioned v7 output/intermediate already exists: " + str(path))
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for info in old.infolist():
            if base.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in prepared:
                new.writestr(copy.copy(info), prepared[info.filename])
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
    unchanged = verify(candidate, prepared)
    report = {
        "status": "controlled_emulator_diagnostic_static_validation_only",
        "source": base.record(SOURCE),
        "diagnosticApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                          "sha256": base.sha256(candidate)},
        "minimumSdkAndOriginalUiPreserved": True,
        "channelGroup": 25,
        "chatCanSeeLevel": {"before": 15, "after": 1},
        "chatSpeakLevel": {"before": 20, "after": 1},
        "changedPayloadMembers": sorted(CHANGED),
        "verifiedUnchangedPayloadMembers": unchanged,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "chatEndToEndTested": False,
        "publicUseAllowed": False,
        "diagnosticOnly": True,
        "securityLimit": "Android loopback TCP is reachable by other apps until same-UID proof is added",
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
    prepared = prepare()
    if args.check:
        print(json.dumps({"status": "in_memory_check_ok", "source": str(SOURCE),
                          "changedPayloadMembers": sorted(CHANGED), "apkCreated": False},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build(prepared), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
