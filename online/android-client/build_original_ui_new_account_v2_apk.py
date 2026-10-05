"""Rebuild only the Android adapter DEX on top of the pinned new-account v1 APK.

This is for a reviewed registration-parser fix. Unity assets, native libraries,
the original launcher, account endpoint and all other APK payloads stay intact.
The source APK is never modified or replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile
import zlib

from build_original_ui_xinfengzhou_apk import copy_compressed_entry, sha256


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-new-account-v1-test.apk"
SOURCE_SHA256 = "604a82f619731888b2ed477ca543a92ce97305611ac3b9f5a1d657e410446fbb"
SOURCE_DEX_SHA256 = "58e62fcd90460bc8a28bec1ffe75b5921b0d6a3bdd468d767decd33cfd4ae154"
RESULT = HERE / "build/witchweapon-online-original-ui-new-account-v2-register-fix.apk"
REPORT = HERE / "build/新账号注册修复候选包验收-v2.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-new-account-v2")
AUTHOR = Path(r"D:\Project\魔女兵器工程恢复\作者单机版源码")
JAVAC = Path(r"D:\Environment\Java\jdk8\bin\javac.exe")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
ANDROID = Path(r"D:\Environment\Android\platforms\android-28\android.jar")
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")
PACKAGE = "com.codex.witchweapon.online.originalui.test"
LAUNCHER = "com.shuiqinling.ww.android.LingGameActivity"
DEX = "classes2.dex"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
ADAPTER = (
    "OfflineApplication.java", "OnlineEndpoint.java", "ChatWebSocketRelay.java",
    "OnlineLoginActivity.java", "OnlineAuthTokens.java", "OnlineSessionStore.java",
    "LegacyStateMirror.java", "OriginalUiAuthBridge.java",
    "OriginalUiRoleSummary.java", "OriginalUiAuthDiagnostic.java",
)
AUTHOR_HELPERS = ("LocalSave.java", "LocalEconomy.java", "ProtoWire.java")


def run(command: list[Path | str], env: dict[str, str] | None = None) -> str:
    result = subprocess.run([str(part) for part in command], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env, timeout=900)
    output = result.stdout.decode("utf-8", errors="replace").strip()
    if result.returncode:
        raise RuntimeError("Build tool failed: " + str(command[0]) + "\n" + output[-3000:])
    return output


def dex_classes(raw: bytes) -> set[str]:
    if raw[:4] != b"dex\n" or struct.unpack_from("<I", raw, 32)[0] != len(raw):
        raise ValueError("Invalid DEX header")
    if raw[12:32] != hashlib.sha1(raw[32:]).digest() \
            or struct.unpack_from("<I", raw, 8)[0] != zlib.adler32(raw[12:]) & 0xffffffff:
        raise ValueError("Invalid DEX checksum")
    strings, string_offset, types, type_offset = struct.unpack_from("<4I", raw, 56)
    classes, class_offset = struct.unpack_from("<2I", raw, 96)

    def get_string(index: int) -> str:
        if index >= strings:
            raise ValueError("Invalid DEX string index")
        offset = struct.unpack_from("<I", raw, string_offset + index * 4)[0]
        for _ in range(5):
            digit = raw[offset]
            offset += 1
            if digit < 128:
                break
        return raw[offset:raw.index(b"\0", offset)].decode("ascii")

    found: set[str] = set()
    for index in range(classes):
        type_index = struct.unpack_from("<I", raw, class_offset + index * 32)[0]
        if type_index >= types:
            raise ValueError("Invalid DEX type index")
        string_index = struct.unpack_from("<I", raw, type_offset + type_index * 4)[0]
        name = get_string(string_index)
        if name in found:
            raise ValueError("Duplicate DEX class descriptor")
        found.add(name)
    return found


def inspect_inputs() -> set[str]:
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned new-account v1 APK is missing or changed")
    required = [JAVAC, JAVA, ANDROID, TOOLS / "lib/d8.jar",
                TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar",
                TOOLS / "aapt.exe", KEY]
    sources = [HERE / "src/com/codex/witchweapon" / name for name in ADAPTER]
    sources += [AUTHOR / name for name in AUTHOR_HELPERS]
    for item in required + sources:
        if not item.is_file():
            raise ValueError("Missing build input: " + str(item))
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or DEX not in names:
            raise ValueError("Invalid v1 APK member set")
        old = apk.read(DEX)
        if hashlib.sha256(old).hexdigest() != SOURCE_DEX_SHA256:
            raise ValueError("Pinned v1 DEX changed")
        if apk.read("assets/original_ui_auth.txt") != b"original-ui-v1\n" \
                or apk.read("assets/original_ui_role_summary.txt") != b"role-summary-v1\n":
            raise ValueError("Original UI account/role mode changed")
    return dex_classes(old)


def compile_adapter(old_classes: set[str]) -> bytes:
    classes_dir, dex_dir = TEMP / "classes", TEMP / "dex"
    if classes_dir.exists() or dex_dir.exists():
        raise ValueError("Unique v2 compiler directories already exist")
    classes_dir.mkdir(parents=True)
    dex_dir.mkdir()
    sources = [HERE / "src/com/codex/witchweapon" / name for name in ADAPTER]
    sources += [AUTHOR / name for name in AUTHOR_HELPERS]
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    run([JAVAC, "-encoding", "UTF-8", "-source", "8", "-target", "8",
         "-classpath", ANDROID, "-d", classes_dir, *sources], env)
    class_files = sorted(classes_dir.rglob("*.class"))
    if not class_files:
        raise ValueError("javac produced no classes")
    run([JAVA, "-cp", TOOLS / "lib/d8.jar", "com.android.tools.r8.D8",
         "--min-api", "21", "--lib", ANDROID, "--output", dex_dir,
         *class_files], env)
    output = dex_dir / "classes.dex"
    if sorted(dex_dir.glob("*.dex")) != [output]:
        raise ValueError("D8 produced an unexpected DEX set")
    raw = output.read_bytes()
    current = dex_classes(raw)
    if not old_classes.issubset(current):
        raise ValueError("Recompiled DEX lost existing adapter classes")
    if hashlib.sha256(raw).hexdigest() == SOURCE_DEX_SHA256:
        raise ValueError("Recompiled DEX did not change; registration fix is absent")
    return raw


def digest(stream) -> bytes:
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.digest()


def verify_payload(candidate: Path, new_dex: bytes, old_classes: set[str]) -> int:
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(candidate) as new:
        old_names = {name for name in old.namelist() if not SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Signed APK member set changed")
        if new.read(DEX) != new_dex or not old_classes.issubset(dex_classes(new_dex)):
            raise ValueError("Signed DEX differs or lost an existing class")
        checked = 0
        for name in sorted(old_names - {DEX}):
            a, b = old.getinfo(name), new.getinfo(name)
            if (a.file_size, a.CRC, a.compress_size, a.compress_type) \
                    != (b.file_size, b.CRC, b.compress_size, b.compress_type):
                raise ValueError("Unrelated APK member metadata changed: " + name)
            with old.open(a) as left, new.open(b) as right:
                if digest(left) != digest(right):
                    raise ValueError("Unrelated APK member payload changed: " + name)
            checked += 1
    return checked


def cert_digest(verification: str) -> str:
    match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", verification, re.I)
    if match is None:
        raise ValueError("APK signer certificate digest missing")
    return match.group(1).lower()


def build(new_dex: bytes, old_classes: set[str]) -> dict[str, object]:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned v2 output already exists")
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    if any(path.exists() for path in (unsigned, aligned, signed)):
        raise ValueError("Unique v2 APK intermediates already exist")
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as target:
        for info in old.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == DEX:
                target.writestr(info, new_dex)
            else:
                copy_compressed_entry(old, target, info)
    run([TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    env["WITCH_TEST_KEYPASS"] = "local-stage1"  # Existing project-local test key.
    signer = [JAVA, "-jar", TOOLS / "lib/apksigner.jar"]
    run([*signer, "sign", "--ks", KEY, "--ks-key-alias", "local",
         "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
         "--out", signed, aligned], env)
    source_signature = run([*signer, "verify", "--verbose", "--print-certs", SOURCE], env)
    candidate_signature = run([*signer, "verify", "--verbose", "--print-certs", signed], env)
    if cert_digest(source_signature) != cert_digest(candidate_signature):
        raise ValueError("Candidate signer differs from installed v1")
    run([TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    badging = run([TOOLS / "aapt.exe", "dump", "badging", signed])
    if ("package: name='" + PACKAGE + "'") not in badging \
            or ("launchable-activity: name='" + LAUNCHER + "'") not in badging:
        raise ValueError("Original package or Unity launcher changed")
    checked = verify_payload(signed, new_dex, old_classes)
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned v1 APK changed during build")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    os.replace(signed, RESULT)
    sidecar = Path(str(signed) + ".idsig")
    if sidecar.is_file():
        os.replace(sidecar, Path(str(RESULT) + ".idsig"))
    for intermediate in (unsigned, aligned):
        intermediate.unlink()
    report = {
        "status": "signed_static_validation_only",
        "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256},
        "testApk": {"path": str(RESULT), "sha256": sha256(RESULT),
                    "bytes": RESULT.stat().st_size},
        "changedPayloadMembers": [DEX],
        "unchangedPayloadMembersCheckedBySha256": checked,
        "dexClassCount": len(dex_classes(new_dex)),
        "preservedOriginalUiLauncher": LAUNCHER,
        "signerCertificateSha256": cert_digest(candidate_signature),
        "runtimeValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    old_classes = inspect_inputs()
    if args.check:
        print("NEW_ACCOUNT_V2_INPUTS_OK", len(old_classes), "existing DEX classes")
        return
    TEMP.mkdir(parents=True, exist_ok=True)
    new_dex = compile_adapter(old_classes)
    result = build(new_dex, old_classes)
    print("NEW_ACCOUNT_V2_APK_READY", result["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
