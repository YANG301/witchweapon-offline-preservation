"""Fold the preserved Stardust 19-21 resource candidate into a full APK."""

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
import build_stardust_story_v104_apk as previous
import build_updater_apk as updater


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SOURCE = previous.OUTPUT
SOURCE_SHA256 = "ab79f49e33df8a12ae9b87ed8955b431001f471bb7724d5bef24606e011b9367"
CANDIDATE = PROJECT / "docs/星尘降临原版19-21资源候选.json"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
OUTPUT = HERE / "build/witchweapon-original-stardust-v105-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-stardust-original-v105")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
INDEX = "assets/m.assets_list.txt"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v105 output or temporary build directory already exists")
    if digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed v104 APK changed")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    details = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    if (details["sourceApkSha256"] != SOURCE_SHA256 or
            details["missingOriginalAssets"] or len(details["assets"]) != 65 or
            details["blackScreenAdaptation"]["coverNode"] != 105):
        raise ValueError("Preserved original story inventory changed")
    replacements = {}
    for path, info in details["assets"].items():
        blob = BLOBS / info["sha256"]
        if not path.startswith("assetbundle/") or (
                digest(blob) != info["sha256"] or blob.stat().st_size != info["bytes"]):
            raise ValueError("Story candidate blob changed: " + path)
        replacements["assets/" + path] = blob.read_bytes()
    index_info = details["apkAssetIndex"]
    index_blob = BLOBS / index_info["sha256"]
    if digest(index_blob) != index_info["sha256"]:
        raise ValueError("Story candidate index changed")
    replacements[INDEX] = index_blob.read_bytes()
    with zipfile.ZipFile(SOURCE) as old:
        original_names = old.namelist()
        if len(original_names) != len(set(original_names)):
            raise ValueError("Duplicate source APK members")
        new_members = set(replacements) - set(original_names)
        expected_new = {
            "assets/assetbundle/config/lesson/sentence_30319.ab",
            "assets/assetbundle/assets/resources/ui/uiimage/guide/bg_stardust_sickroom.ab",
        }
        if new_members != expected_new:
            raise ValueError("Unexpected new original resource paths: " + repr(new_members))
        replacements["AndroidManifest.xml"] = previous.previous.base.patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043104, new_code=20043105,
            old_name="2.0.1.20043104", new_name="2.0.1.20043105")
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
        for member in sorted(new_members):
            entry = zipfile.ZipInfo(member, date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_STORED
            entry.external_attr = 0o644 << 16
            new.writestr(entry, replacements[member])
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
        if set(result) != set(original) | new_members:
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
        "androidVersionCode": 20043105,
        "changedPayload": sorted(replacements), "addedBundles": sorted(new_members),
        "signingCertificateSha256": match.group(1),
        "deviceValidated": False,
    }
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != summary:
        raise ValueError("v105 report did not round-trip")
    print("SIGNED_ORIGINAL_STARDUST_V105_OK", summary["resultSha256"])
    return summary


if __name__ == "__main__":
    build()
