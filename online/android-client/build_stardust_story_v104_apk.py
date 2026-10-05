"""Fold the repaired chapter 20/21 lesson graphs into a full v104 APK."""

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
import build_stardust_story_v103_apk as previous
import build_updater_apk as updater


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SOURCE = previous.OUTPUT
SOURCE_SHA256 = "d3dc7db572170307ad1a12b8396397963aad0e7f877c06958e186b203b3e1f18"
REPORT_SOURCE = PROJECT / "docs/星尘降临20-21资源构建-v27.json"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
OUTPUT = HERE / "build/witchweapon-stardust-story-v104-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-stardust-story-v104")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
LESSONS = tuple("assets/assetbundle/assets/resources/guide/lesson/lesson303"
                + str(episode) + ".ab" for episode in (20, 21))
INDEX = "assets/m.assets_list.txt"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v104 output or build directory already exists")
    if digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed v103 APK changed")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    details = json.loads(REPORT_SOURCE.read_text(encoding="utf-8"))
    if details["sourceApkSha256"] != previous.SOURCE_SHA256:
        raise ValueError("Chapter repair was generated from another original APK")
    replacements = {}
    for member in LESSONS:
        info = details["assets"][member.removeprefix("assets/")]
        blob = BLOBS / info["sha256"]
        if digest(blob) != info["sha256"]:
            raise ValueError("Repaired chapter bundle changed: " + member)
        replacements[member] = blob.read_bytes()
    index_info = details["apkAssetIndex"]
    index_blob = BLOBS / index_info["sha256"]
    if digest(index_blob) != index_info["sha256"]:
        raise ValueError("Repaired chapter index changed")
    replacements[INDEX] = index_blob.read_bytes()
    with zipfile.ZipFile(SOURCE) as old:
        names = old.namelist()
        if len(names) != len(set(names)) or not set(replacements).issubset(names):
            raise ValueError("Source APK member inventory changed")
        replacements["AndroidManifest.xml"] = previous.base.patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043103, new_code=20043104,
            old_name="2.0.1.20043103", new_name="2.0.1.20043104")
        for member in LESSONS + (INDEX,):
            if old.read(member) == replacements[member]:
                raise ValueError("Expected repaired chapter member is unchanged: " + member)
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
        for name in result:
            if name in replacements:
                if new.read(name) != replacements[name]:
                    raise ValueError("Repaired APK member differs: " + name)
            elif (original[name].CRC, original[name].file_size,
                  original[name].compress_size) != (
                    result[name].CRC, result[name].file_size,
                    result[name].compress_size):
                raise ValueError("Unrelated APK member changed: " + name)
        for name in ("assets/m.version", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/online_endpoint.txt",
                     "assets/offline_responses.json", "classes2.dex"):
            if old.read(name) != new.read(name):
                raise ValueError("Critical client member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    summary = {
        "source": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "result": str(OUTPUT), "resultSha256": digest(OUTPUT),
        "androidVersionCode": 20043104,
        "changedPayload": sorted(replacements),
        "signingCertificateSha256": match.group(1),
        "deviceValidated": False,
    }
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != summary:
        raise ValueError("APK report did not round-trip")
    print("SIGNED_STARDUST_STORY_APK_OK", summary["androidVersionCode"],
          summary["resultSha256"])
    return summary


if __name__ == "__main__":
    build()
