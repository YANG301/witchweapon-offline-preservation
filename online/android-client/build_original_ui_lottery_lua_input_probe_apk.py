"""Build an isolated original-UI APK with a read-only Unity/Lua input probe."""

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
import patch_lottery_input_probe


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-lottery-touch-probe.apk"
SOURCE_SHA256 = "b15f0b617ac0a7021d2cf326b3febd8319d07a9df647452f7ebf2d0d2a06cf68"
RESULT = HERE / "build/witchweapon-online-original-ui-lottery-lua-input-probe-v5.apk"
REPORT = HERE / "build/抽卡Unity输入隔离诊断包v5验收.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-lottery-lua-probe-v5"
BUNDLE = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")
PACKAGE = "com.codex.witchweapon.online.originalui.test"
LAUNCHER = "com.shuiqinling.ww.android.LingGameActivity"


def check() -> dict[str, bytes]:
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned lottery touch probe source missing or changed")
    for path in (JAVA, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar",
                 TOOLS / "aapt.exe", KEY):
        if not path.is_file():
            raise ValueError("Portable build dependency missing: " + str(path))
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or BUNDLE not in names or INDEX not in names:
            raise ValueError("Unexpected source APK members")
        patched = patch_lottery_input_probe.patch(source.read(BUNDLE))
        index = patch_index(source.read(INDEX), {"/lua/lua.ab": patched})
    return {BUNDLE: patched, INDEX: index}


def cert_digest(output: str) -> str:
    match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", output, re.I)
    if not match:
        raise ValueError("Missing signer digest")
    return match.group(1).lower()


def verify_payload(replacements: dict[str, bytes]) -> int:
    checked = 0
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(RESULT) as built:
        old = {x for x in source.namelist() if not SIGNATURE.fullmatch(x)}
        new = {x for x in built.namelist() if not SIGNATURE.fullmatch(x)}
        if old != new:
            raise ValueError("APK payload member set changed")
        for name in old:
            if name in replacements:
                if built.read(name) != replacements[name]:
                    raise ValueError("Replacement differs: " + name)
            else:
                a, b = source.getinfo(name), built.getinfo(name)
                if (a.file_size, a.CRC, a.compress_size) != (b.file_size, b.CRC, b.compress_size):
                    raise ValueError("Unrelated member metadata changed: " + name)
                checked += 1
    return checked


def build(replacements: dict[str, bytes]) -> None:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned diagnostic output already exists")
    TEMP_PARENT.mkdir(parents=True, exist_ok=True)
    TEMP.mkdir(parents=True, exist_ok=False)
    try:
        unsigned = TEMP / "unsigned.apk"
        aligned = TEMP / "aligned.apk"
        signed = TEMP / "signed.apk"
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
             "--out", signed, aligned], env)
        source_cert = cert_digest(run([*signer, "verify", "--print-certs", SOURCE], env))
        test_cert = cert_digest(run([*signer, "verify", "--print-certs", signed], env))
        if source_cert != test_cert:
            raise ValueError("Diagnostic signer differs from installed APK")
        run([TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
        badging = run([TOOLS / "aapt.exe", "dump", "badging", signed])
        if ("package: name='" + PACKAGE + "'") not in badging or \
                ("launchable-activity: name='" + LAUNCHER + "'") not in badging:
            raise ValueError("Package or original Unity launcher changed")
        os.replace(signed, RESULT)
        sidecar = Path(str(signed) + ".idsig")
        if sidecar.is_file():
            os.replace(sidecar, Path(str(RESULT) + ".idsig"))
        unchanged = verify_payload(replacements)
        if sha256(SOURCE) != SOURCE_SHA256:
            raise ValueError("Pinned source changed during build")
        report = {
            "status": "signed_static_validation_only",
            "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256},
            "testApk": {"path": str(RESULT), "sha256": sha256(RESULT),
                        "bytes": RESULT.stat().st_size},
            "changedPayloadMembers": [BUNDLE, INDEX],
            "unchangedPayloadMembersCheckedByMetadata": unchanged,
            "signerCertificateSha256": test_cert,
            "preservedOriginalUiLauncher": LAUNCHER,
            "runtimeValidated": False,
            "recordsSensitiveFields": False,
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("LOTTERY_LUA_INPUT_PROBE_APK_READY", report["testApk"]["sha256"], RESULT)
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or resolved.name != "witch-online-lottery-lua-probe-v5":
                raise ValueError("Refusing unsafe temporary cleanup")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    replacements = check()
    if args.check:
        print("LOTTERY_LUA_INPUT_PROBE_INPUTS_OK", len(replacements), "payload members")
    else:
        build(replacements)


if __name__ == "__main__":
    main()
