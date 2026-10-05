"""Build an isolated v3 APK to observe the old RTM protocol on adb reverse.

It keeps the original Unity UI and native chat code. It only redirects the CN
LeanCloud router/engine and fills the three previously empty conversation IDs.
This diagnostic build is deliberately loopback-only and must not be published.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import build_original_ui_xinfengzhou_apk as previous
import probe_original_chat_assets as probe


HERE = Path(__file__).resolve().parent
SOURCE = probe.APK
SOURCE_SHA256 = probe.APK_SHA256
OUTPUT = HERE / "build"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-rtm-probe-v3-test.apk"
REPORT = OUTPUT / "原版聊天RTM回环诊断包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-rtm-probe-v3")
ORIGIN = "http://127.0.0.1:18301"
IDS = {1: "xinfengzhou-world", 2: "xinfengzhou-system", 3: "xinfengzhou-notify"}
CHANGED = {probe.BUNDLE, probe.FIXTURES, probe.INDEX}
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")
PACKAGE = "com.codex.witchweapon.online.originalui.test"
LAUNCHER = "com.shuiqinling.ww.android.LingGameActivity"


def prepare():
    if not SOURCE.is_file() or previous.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v2 APK is missing or changed")
    probe.validate_origin(ORIGIN)
    if any(not path.is_file() for path in (JAVA, KEY, TOOLS / "zipalign.exe",
                                             TOOLS / "aapt.exe", TOOLS / "lib/apksigner.jar")):
        raise ValueError("Portable Android build/signing dependency missing")
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or not CHANGED.issubset(names):
            raise ValueError("Pinned APK has unexpected members")
        original = {name: apk.read(name) for name in CHANGED}
    bundle = probe.patch_bundle(original[probe.BUNDLE], ORIGIN)
    fixture = probe.patch_fixture(original[probe.FIXTURES], IDS)
    index = probe.base.patch_index(original[probe.INDEX],
                                   {"/config/clientexel/clientplatformconstant.ab": bundle})
    prepared = {probe.BUNDLE: bundle, probe.FIXTURES: fixture, probe.INDEX: index}
    if any(prepared[name] == original[name] for name in CHANGED):
        raise ValueError("One expected member did not change")
    return prepared


def verify_signed(path, prepared):
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(path) as candidate:
        old_names = {name for name in source.namelist()
                     if not previous.SIGNATURE.fullmatch(name)}
        new_names = {name for name in candidate.namelist()
                     if not previous.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(candidate.namelist()) != len(set(candidate.namelist())):
            raise ValueError("Signed APK member set changed")
        if any(candidate.read(name) != prepared[name] for name in CHANGED):
            raise ValueError("Signed APK lost a reviewed replacement")
        unchanged = 0
        for name in sorted(old_names - CHANGED):
            with source.open(name) as before, candidate.open(name) as after:
                if previous.stream_digest(before) != previous.stream_digest(after):
                    raise ValueError("Unrelated APK member changed: " + name)
            unchanged += 1
    if previous.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v2 APK changed during build")
    return unchanged


def build(prepared):
    unsigned = OUTPUT / "chat-rtm-probe-v3-unsigned.apk"
    aligned = OUTPUT / "chat-rtm-probe-v3-aligned.apk"
    candidate = OUTPUT / "chat-rtm-probe-v3-candidate.next.apk"
    staged_report = OUTPUT / "chat-rtm-probe-v3-report.next.json"
    alias = TEMP / "chat-rtm-probe-v3-aapt.apk"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, alias, sidecar):
        if path.exists():
            raise ValueError("Versioned diagnostic output/intermediate already exists: " + str(path))
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(
            unsigned, "x", allowZip64=False) as target:
        for info in source.infolist():
            if previous.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in prepared:
                target.writestr(copy.copy(info), prepared[info.filename])
            else:
                previous.copy_compressed_entry(source, target, info)
    previous.run([TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    previous.run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
                  "--ks-pass", "env:WITCH_TEST_KEYPASS",
                  "--key-pass", "env:WITCH_TEST_KEYPASS",
                  "--out", candidate, aligned], env)
    signature = previous.run([*signer, "verify", "--verbose", "--print-certs", candidate], env)
    alignment = previous.run([TOOLS / "zipalign.exe", "-c", "-p", "4", candidate])
    try:
        os.link(candidate, alias)
        badging = previous.run([TOOLS / "aapt.exe", "dump", "badging", alias])
        xml = previous.run([TOOLS / "aapt.exe", "dump", "xmltree", alias, "AndroidManifest.xml"])
    finally:
        if alias.exists():
            alias.unlink()
    if (("package: name='" + PACKAGE + "'") not in badging
            or ("launchable-activity: name='" + LAUNCHER + "'") not in badging
            or "android:exported(0x01010010)=(type 0x12)0x1" not in xml):
        raise ValueError("Original package or Unity launcher changed")
    unchanged = verify_signed(candidate, prepared)
    report = {
        "status": "signed_static_validation_only",
        "source": previous.record(SOURCE),
        "testApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                    "sha256": previous.sha256(candidate)},
        "package": PACKAGE,
        "launcher": LAUNCHER,
        "diagnosticRouterOrigin": ORIGIN,
        "conversationIds": IDS,
        "changedPayloadMembers": sorted(CHANGED),
        "verifiedUnchangedPayloadMembers": unchanged,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "rtmHandshakeTested": False,
        "publicUseAllowed": False,
        "securityLimit": "Original RTM session open has no game access Bearer or signature; loopback probe only",
    }
    staged_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate.rename(RESULT)
    staged_report.rename(REPORT)
    # The final APK and audit report remain; large unsigned/aligned copies are
    # only build intermediates and have no recovery purpose.
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
        return
    print(json.dumps(build(prepared), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
