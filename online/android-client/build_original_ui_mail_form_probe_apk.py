"""Build a signed, test-only APK that logs mail form field names and lengths.

The production Android Java source is not modified. This builder first proves
that rebuilding it reproduces the pinned v5 DEX byte-for-byte, then compiles a
temporary copy with one mail-route-only diagnostic. It never installs an APK.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

import build_online_apk as adapter
from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run, sha256


HERE = Path(__file__).resolve().parent
SOURCE = Path(r"D:\Project\魔女兵器在线版\构建\witchweapon-online-original-ui-task-refresh-v5-test.apk")
SOURCE_SHA256 = "846cb1b73e9ce91c44a446fe9bf983071847146f76d3b61110d98637141876e1"
SOURCE_DEX_SHA256 = "58e62fcd90460bc8a28bec1ffe75b5921b0d6a3bdd468d767decd33cfd4ae154"
JAVA_SOURCE = HERE / "src/com/codex/witchweapon/OfflineApplication.java"
JAVA_SOURCE_SHA256 = "0da03b2780bf9a915a078b5f0f9908c19f8bd6ae0eaf20b1f903b3f9643a4fb8"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-mail-form-probe")
RESULT = Path(r"D:\Project\魔女兵器在线版\构建\witchweapon-online-original-ui-mail-form-probe-v1-test.apk")
REPORT = Path(r"D:\Project\魔女兵器在线版\构建\原版邮件表单诊断包验收.json")
DEX = "classes2.dex"
TOOLS = Path(r"D:\Environment\Android\build-tools\35.0.0")
JAVA = Path(r"D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe")
KEY = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks")


PROBE_METHOD = '''
    // Test-only diagnostic: never logs values, mail IDs, account IDs, or Bearers.
    private static void logMailStateFormShape(String method, String contentType, byte[] body) {
        final String tag = "WWMailFormProbe";
        if (body.length > 4096) {
            android.util.Log.i(tag, "route=updateMailState oversizedBody=" + body.length);
            return;
        }
        String raw = new String(body, StandardCharsets.ISO_8859_1);
        String[] pairs = raw.isEmpty() ? new String[0] : raw.split("&", -1);
        StringBuilder fields = new StringBuilder();
        Map<String,Integer> seen = new HashMap<>();
        int duplicates = 0;
        for (String pair : pairs) {
            int equal = pair.indexOf('=');
            String key;
            try {
                key = java.net.URLDecoder.decode(equal < 0 ? pair : pair.substring(0, equal), "UTF-8");
            } catch (Exception invalidKey) {
                key = "?";
            }
            if (!key.matches("[A-Za-z][A-Za-z0-9_]{0,31}")) key = "?";
            Integer count = seen.get(key);
            if (count != null) duplicates++;
            seen.put(key, count == null ? 1 : count + 1);
            if (fields.length() > 0) fields.append(',');
            fields.append(key).append(':').append(equal < 0 ? -1 : pair.length() - equal - 1);
        }
        boolean isForm = contentType != null
                && contentType.toLowerCase(Locale.ROOT).startsWith("application/x-www-form-urlencoded");
        android.util.Log.i(tag, "route=updateMailState method=" + method + " form=" + isForm
                + " bodyBytes=" + body.length + " fields=" + fields + " duplicates=" + duplicates);
    }

'''


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Pinned Java source anchor changed")
    return source.replace(before, after, 1)


def diagnostic_source() -> bytes:
    if sha256(JAVA_SOURCE) != JAVA_SOURCE_SHA256:
        raise ValueError("Production Android adapter source changed")
    source = JAVA_SOURCE.read_text(encoding="utf-8")
    source = replace_once(source, "    private Reply route(String method, String target, String contentType, byte[] body) {",
                          PROBE_METHOD + "    private Reply route(String method, String target, String contentType, byte[] body) {")
    source = replace_once(source,
                          "        String path = query < 0 ? target : target.substring(0, query);",
                          "        String path = query < 0 ? target : target.substring(0, query);\n"
                          "        if (\"/mail/updateMailState\".equals(path))\n"
                          "            logMailStateFormShape(method, contentType, body);")
    source = replace_once(source,
                          "                    int status = upstream.getResponseCode();",
                          "                    int status = upstream.getResponseCode();\n"
                          "                    if (\"/mail/updateMailState\".equals(path))\n"
                          "                        android.util.Log.i(\"WWMailFormProbe\",\n"
                          "                                \"route=updateMailState upstreamStatus=\" + status);")
    if source.count("WWMailFormProbe") != 2 or source.count("logMailStateFormShape") != 2:
        raise ValueError("Mail diagnostic did not stay limited to one route")
    return source.encode("utf-8")


def prepare() -> tuple[bytes, bytes, int]:
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned signed v5 APK missing or changed")
    for needed in (JAVA, KEY, TOOLS / "zipalign.exe", TOOLS / "lib/apksigner.jar"):
        if not needed.is_file():
            raise ValueError("Portable build dependency missing: " + str(needed))
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or DEX not in names:
            raise ValueError("Unexpected signed v5 APK members")
        old_dex = source.read(DEX)
    if hashlib.sha256(old_dex).hexdigest() != SOURCE_DEX_SHA256:
        raise ValueError("Pinned v5 Android bridge DEX changed")
    old_classes = adapter.dex_classes(old_dex)
    source_files = [HERE / "src/com/codex/witchweapon" / name for name in adapter.ADAPTER]
    source_files += [adapter.AUTHOR / name for name in adapter.AUTHOR_HELPERS]
    adapter.TEMP = TEMP
    baseline, baseline_classes = adapter.compile_dex(source_files, old_classes)
    if baseline != old_dex or set(baseline_classes) != set(old_classes):
        raise ValueError("Current production Java source does not reproduce v5 DEX")
    copy_path = TEMP / "diagnostic-source/com/codex/witchweapon/OfflineApplication.java"
    copy_path.parent.mkdir(parents=True, exist_ok=True)
    copy_path.write_bytes(diagnostic_source())
    source_files = [copy_path if path == JAVA_SOURCE else path for path in source_files]
    if copy_path not in source_files:
        raise ValueError("Diagnostic copy did not replace the intended Java source")
    probe_dex, probe_classes = adapter.compile_dex(source_files, old_classes)
    if probe_dex == old_dex or set(probe_classes) != set(old_classes):
        raise ValueError("Diagnostic DEX changed unrelated Android class inventory")
    if sha256(JAVA_SOURCE) != JAVA_SOURCE_SHA256:
        raise ValueError("Production Android Java source changed during diagnostic build")
    return old_dex, probe_dex, len(probe_classes)


def verify_payload(path: Path, diagnostic_dex: bytes) -> int:
    with zipfile.ZipFile(SOURCE) as before, zipfile.ZipFile(path) as after:
        originals = {name for name in before.namelist() if not adapter.SIGNATURE.fullmatch(name)}
        built = {name for name in after.namelist() if not adapter.SIGNATURE.fullmatch(name)}
        if originals != built or len(after.namelist()) != len(set(after.namelist())):
            raise ValueError("APK members changed outside signatures")
        if after.read(DEX) != diagnostic_dex:
            raise ValueError("Signed DEX differs from compiled diagnostic")
        unchanged = 0
        for name in originals - {DEX}:
            left, right = before.getinfo(name), after.getinfo(name)
            if (left.file_size, left.CRC, left.compress_size) != (right.file_size, right.CRC, right.compress_size):
                raise ValueError("Unrelated APK payload metadata changed: " + name)
            unchanged += 1
    return unchanged


def build(diagnostic_dex: bytes, classes: int) -> None:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned diagnostic output already exists")
    TEMP.mkdir(parents=True, exist_ok=True)
    unsigned, aligned, signed = (TEMP / name for name in ("unsigned.apk", "aligned.apk", "signed.apk"))
    if any(path.exists() for path in (unsigned, aligned, signed)):
        raise ValueError("Stale diagnostic packaging intermediate exists")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(unsigned, "x", allowZip64=False) as target:
        for info in source.infolist():
            if adapter.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == DEX:
                target.writestr(copy.copy(info), diagnostic_dex)
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
    signature = run([*signer, "verify", "--verbose", signed], env)
    alignment = run([TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    unchanged = verify_payload(signed, diagnostic_dex)
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Source APK changed during packaging")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(signed, RESULT)
    sidecar = Path(str(signed) + ".idsig")
    if sidecar.is_file():
        shutil.copyfile(sidecar, Path(str(RESULT) + ".idsig"))
    if sha256(RESULT) != sha256(signed):
        raise ValueError("Desktop diagnostic APK copy failed checksum")
    report = {
        "status": "signed_static_validation_only",
        "source": {"path": str(SOURCE), "sha256": SOURCE_SHA256},
        "testApk": {"path": str(RESULT), "sha256": sha256(RESULT), "bytes": RESULT.stat().st_size},
        "changedPayloadMembers": [DEX], "unchangedPayloadMembersChecked": unchanged,
        "adapterClassCount": classes, "mailProbeRoute": "/mail/updateMailState",
        "mailProbeFields": ["method", "form", "bodyBytes", "fieldNames", "fieldValueLengths", "duplicateCount", "upstreamStatus"],
        "valuesLogged": False, "installed": False,
        "signatureVerification": signature, "alignmentVerification": alignment,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MAIL_FORM_PROBE_APK_BUILT", report["testApk"]["sha256"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compile and compare DEX, do not package")
    parser.add_argument("--build", action="store_true", help="build a signed APK without installing it")
    args = parser.parse_args()
    if args.check == args.build:
        parser.error("specify exactly one of --check or --build")
    _, diagnostic_dex, classes = prepare()
    if args.check:
        print("MAIL_FORM_PROBE_STATIC_CHECK_OK", hashlib.sha256(diagnostic_dex).hexdigest(), classes)
    else:
        build(diagnostic_dex, classes)


if __name__ == "__main__":
    main()
