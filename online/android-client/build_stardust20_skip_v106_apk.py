"""Fold the chapter-20 missing-background bypass into the next full APK."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

import build_online_apk as apk_tools
import build_original_ui_quest_refresh_v6_apk as signer
import build_original_stardust_v105_apk as previous
import build_updater_apk as updater


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SOURCE = previous.OUTPUT
SOURCE_SHA256 = "1a61cbd6bbd71c51906a6f56c7eb44c9de8b93fb333e6390038cadc207cc98e2"
CANDIDATE = PROJECT / "docs/星尘降临第20节缺图跳过候选.json"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
LESSON = "assets/assetbundle/assets/resources/guide/lesson/lesson30320.ab"
INDEX = "assets/m.assets_list.txt"
OUTPUT = HERE / "build/witchweapon-stardust-skip-v106-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-stardust-skip-v106")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v106 output or temporary directory already exists")
    if digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed v105 APK changed")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    details = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    info = details["assets"][LESSON.removeprefix("assets/")]
    if (details["sourceFullApkSha256"] != SOURCE_SHA256
            or details["missingBackgroundHandling"]["skippedNodeId"] != "744"
            or info["sha256"] != "f85d70be1a8d19f319383f560e9f24164a533113ac695c988330bbecfd046d75"):
        raise ValueError("Reviewed chapter-20 candidate changed")
    lesson_blob = BLOBS / info["sha256"]
    index_blob = BLOBS / details["apkAssetIndex"]["sha256"]
    if (digest(lesson_blob) != info["sha256"]
            or digest(index_blob) != details["apkAssetIndex"]["sha256"]):
        raise ValueError("Candidate blob changed")
    replacements = {LESSON: lesson_blob.read_bytes(), INDEX: index_blob.read_bytes()}
    with zipfile.ZipFile(SOURCE) as old:
        names = old.namelist()
        if len(names) != len(set(names)) or not set(replacements).issubset(names):
            raise ValueError("Source APK inventory changed")
        replacements["AndroidManifest.xml"] = previous.previous.previous.base.patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043105, new_code=20043106,
            old_name="2.0.1.20043105", new_name="2.0.1.20043106")
    TEMP.mkdir(parents=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for entry in old.infolist():
            if SIGNATURE.fullmatch(entry.filename):
                continue
            if entry.filename in replacements:
                new.writestr(copy.copy(entry), replacements[entry.filename])
            else:
                apk_tools.copy_compressed_entry(old, new, entry)
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    command = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    environment["TEMP"] = environment["TMP"] = str(TEMP)
    signer.run([*command, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS",
                "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], environment)
    verified = signer.run([*command, "verify", "--verbose", "--print-certs", signed], environment)
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", verified)
    if not match or match.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("APK signing identity changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        original = {entry.filename: entry for entry in old.infolist()
                    if not SIGNATURE.fullmatch(entry.filename)}
        result = {entry.filename: entry for entry in new.infolist()
                  if not SIGNATURE.fullmatch(entry.filename)}
        if set(result) != set(original):
            raise ValueError("Full APK member inventory changed")
        for member in result:
            if member in replacements:
                if new.read(member) != replacements[member]:
                    raise ValueError("Candidate APK member differs: " + member)
            elif (original[member].CRC, original[member].file_size,
                  original[member].compress_size) != (
                    result[member].CRC, result[member].file_size,
                    result[member].compress_size):
                raise ValueError("Unrelated APK member changed: " + member)
        for member in ("assets/m.version", "assets/update_endpoint.txt",
                       "assets/update_public_key.der", "assets/online_endpoint.txt",
                       "assets/offline_responses.json", "classes2.dex"):
            if old.read(member) != new.read(member):
                raise ValueError("Critical client member changed: " + member)
    signed.replace(OUTPUT)
    summary = {
        "source": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "result": str(OUTPUT), "resultSha256": digest(OUTPUT),
        "androidVersionCode": 20043106,
        "changedPayload": sorted(replacements),
        "signingCertificateSha256": match.group(1),
        "deviceValidated": False,
    }
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != summary:
        raise ValueError("v106 report did not round-trip")
    print("SIGNED_STARDUST_SKIP_V106_OK", summary["resultSha256"])
    return summary


if __name__ == "__main__":
    build()
