"""Merge episodes 20/21 and the signed-update payload into a full v103 APK.

Existing APK entries are copied without recompression.  Only AndroidManifest,
the asset index, two existing CSV bundles, and the twenty new story/background
bundles may change.  The installed signing identity is verified after signing.
"""

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
import build_unlimited_stock_v102_apk as previous
import build_updater_apk as updater


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
base = previous.base
SOURCE = HERE / "build/witchweapon-unlimited-stock-v102-test.apk"
SOURCE_SHA256 = "9b2cba23a8f8130015ffe4502cce00f705b927ad81bd4de865520cb9ff596e31"
REPORT_SOURCE = PROJECT / "docs/星尘降临20-21资源构建.json"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
OUTPUT = HERE / "build/witchweapon-stardust-story-v103-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-stardust-story-v103")
MANIFEST = "AndroidManifest.xml"
INDEX = "assets/m.assets_list.txt"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inputs() -> tuple[dict[str, bytes], dict]:
    if digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Unreviewed v102 APK")
    details = json.loads(REPORT_SOURCE.read_text(encoding="utf-8"))
    if details["sourceApkSha256"] != SOURCE_SHA256 or len(details["assets"]) != 22:
        raise ValueError("Unreviewed story resource report")
    assets = {}
    for path, info in details["assets"].items():
        member = "assets/" + path
        blob = BLOBS / info["sha256"]
        if not member.startswith("assets/assetbundle/") or digest(blob) != info["sha256"]:
            raise ValueError("Story blob changed: " + path)
        assets[member] = blob.read_bytes()
    index_info = details["apkAssetIndex"]
    index_blob = BLOBS / index_info["sha256"]
    if digest(index_blob) != index_info["sha256"]:
        raise ValueError("Story asset index changed")
    assets[INDEX] = index_blob.read_bytes()
    return assets, details


def build() -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v103 output or temporary directory already exists")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    for path in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not path.is_file():
            raise FileNotFoundError(path)
    assets, details = inputs()
    with zipfile.ZipFile(SOURCE) as old:
        names = old.namelist()
        if len(names) != len(set(names)) or not {MANIFEST, INDEX}.issubset(names):
            raise ValueError("Unreviewed APK member inventory")
        if old.read(INDEX) == assets[INDEX]:
            raise ValueError("Story asset index was not changed")
        manifest = base.patch_android_manifest(
            old.read(MANIFEST), old_code=20043102, new_code=20043103,
            old_name="2.0.1.20043102", new_name="2.0.1.20043103")
        replacements = {MANIFEST: manifest, **assets}
        new_members = set(replacements) - set(names)
        expected_new = set(assets) - {
            INDEX, "assets/assetbundle/config/clientexel/story.ab",
            "assets/assetbundle/config/clientexel/dictionary.ab"}
        if new_members != expected_new or len(new_members) != 20:
            raise ValueError("Unexpected new story bundle inventory")
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
        raise ValueError("APK signing certificate changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        original = {entry.filename: entry for entry in old.infolist()
                    if not SIGNATURE.fullmatch(entry.filename)}
        result = {entry.filename: entry for entry in new.infolist()
                  if not SIGNATURE.fullmatch(entry.filename)}
        if set(result) != set(original) | new_members:
            raise ValueError("Full APK member inventory mismatch")
        for name in result:
            if name in replacements:
                if new.read(name) != replacements[name]:
                    raise ValueError("Patched APK member differs: " + name)
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
        "androidVersionCode": 20043103,
        "changedPayload": sorted(replacements),
        "addedBundles": sorted(new_members),
        "storySentences": {key: value["sentences"] for key, value in details["chapters"].items()},
        "signingCertificateSha256": match.group(1),
        "deviceValidated": False,
    }
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != summary:
        raise ValueError("APK build report did not round-trip")
    print("SIGNED_STARDUST_STORY_APK_OK", summary["androidVersionCode"],
          summary["resultSha256"])
    return summary


if __name__ == "__main__":
    build()
