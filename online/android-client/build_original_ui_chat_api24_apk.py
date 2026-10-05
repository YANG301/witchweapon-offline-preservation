"""Set the signed original-UI chat relay candidate's true minimum to API 24.

This makes a separate v6 APK; v2-v5 packages and all game assets remain as-is.
"""

import argparse
import copy
import json
import os
from pathlib import Path
import struct
import zipfile

import build_original_ui_xinfengzhou_apk as base
import patch_manifest as axml


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "build"
SOURCE = OUTPUT / "witchweapon-online-original-ui-chat-relay-v5-test.apk"
SOURCE_SHA256 = "ad2265ae911a2937a3a1d10e8fa7e3a0361f9ca5ffcfb17eb9624c4a8688f1ed"
RESULT = OUTPUT / "witchweapon-online-original-ui-chat-relay-api24-v6-test.apk"
REPORT = OUTPUT / "原版聊天API24候选包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-chat-api24-v6")
MANIFEST = "AndroidManifest.xml"
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


def sdk_values(raw):
    chunks = axml.split_chunks(raw)
    strings, _ = axml.string_pool(chunks[0])
    values = []
    for chunk in chunks:
        if axml.start_tag(chunk, strings) != "uses-sdk":
            continue
        attrs = axml.attributes(chunk, strings)
        if "minSdkVersion" not in attrs or "targetSdkVersion" not in attrs:
            raise ValueError("Manifest uses-sdk attributes missing")
        entry = {}
        for name in ("minSdkVersion", "targetSdkVersion"):
            at = attrs[name]
            if chunk[at + 15] != 0x10 or axml.u32(chunk, at + 8) != axml.NONE:
                raise ValueError("Unexpected typed uses-sdk attribute")
            entry[name] = axml.u32(chunk, at + 16)
        values.append(entry)
    if len(values) != 1:
        raise ValueError("Expected one uses-sdk tag")
    return values[0]


def patch_minimum(raw):
    if sdk_values(raw) != {"minSdkVersion": 14, "targetSdkVersion": 29}:
        raise ValueError("Pinned v5 SDK values differ")
    chunks = axml.split_chunks(raw)
    strings, _ = axml.string_pool(chunks[0])
    updated = 0
    for chunk in chunks:
        if axml.start_tag(chunk, strings) == "uses-sdk":
            at = axml.attributes(chunk, strings)["minSdkVersion"]
            struct.pack_into("<I", chunk, at + 16, 24)
            updated += 1
    if updated != 1:
        raise ValueError("Did not update exactly one minSdkVersion")
    body = b"".join(bytes(chunk) for chunk in chunks)
    result = struct.pack("<HHI", 3, 8, len(body) + 8) + body
    if sdk_values(result) != {"minSdkVersion": 24, "targetSdkVersion": 29}:
        raise ValueError("Patched manifest SDK readback failed")
    differences = [index for index, (before, after) in enumerate(zip(raw, result))
                   if before != after]
    if len(raw) != len(result) or len(differences) != 1 or raw[differences[0]] != 14 \
            or result[differences[0]] != 24:
        raise ValueError("Unexpected manifest bytes changed")
    return result


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v5 APK is missing or changed")
    for path in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Portable APK build dependency missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())) or MANIFEST not in apk.namelist():
            raise ValueError("Pinned v5 APK member set invalid")
        raw = apk.read(MANIFEST)
    modified = patch_minimum(raw)
    if modified == raw:
        raise ValueError("Minimum SDK was not changed")
    return modified


def verify(path, manifest):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Unexpected signed APK member set")
        if new.read(MANIFEST) != manifest:
            raise ValueError("Signed APK lost manifest replacement")
        unchanged = 0
        for name in sorted(old_names - {MANIFEST}):
            with old.open(name) as before, new.open(name) as after:
                if base.stream_digest(before) != base.stream_digest(after):
                    raise ValueError("Unrelated APK member changed: " + name)
            unchanged += 1
    if base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v5 APK changed during build")
    return unchanged


def build(manifest):
    unsigned = OUTPUT / "chat-api24-v6-unsigned.apk"
    aligned = OUTPUT / "chat-api24-v6-aligned.apk"
    candidate = OUTPUT / "chat-api24-v6-candidate.next.apk"
    staged_report = OUTPUT / "chat-api24-v6-report.next.json"
    sidecar = Path(str(candidate) + ".idsig")
    for path in (RESULT, REPORT, unsigned, aligned, candidate, staged_report, sidecar):
        if path.exists():
            raise ValueError("Versioned v6 output/intermediate already exists: " + str(path))
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for info in old.infolist():
            if base.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == MANIFEST:
                new.writestr(copy.copy(info), manifest)
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
    unchanged = verify(candidate, manifest)
    report = {
        "status": "signed_static_validation_only",
        "source": base.record(SOURCE),
        "testApk": {"path": str(RESULT), "bytes": candidate.stat().st_size,
                    "sha256": base.sha256(candidate)},
        "minimumSdkBefore": 14,
        "minimumSdkAfter": 24,
        "targetSdkPreserved": 29,
        "originalPackageLauncherAssetsAndDexPreserved": True,
        "changedPayloadMembers": [MANIFEST],
        "verifiedUnchangedPayloadMembers": unchanged,
        "signatureVerification": signature,
        "alignmentVerification": alignment,
        "notInstalled": True,
        "chatEndToEndTested": False,
        "publicUseAllowed": False,
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
    manifest = prepare()
    if args.check:
        print(json.dumps({"status": "in_memory_check_ok", "source": str(SOURCE),
                          "sdkBefore": {"min": 14, "target": 29},
                          "sdkAfter": {"min": 24, "target": 29},
                          "changedPayloadMembers": [MANIFEST], "apkCreated": False},
                         ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build(manifest), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
