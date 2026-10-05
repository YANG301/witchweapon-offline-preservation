"""Include the guild recall Lua repair in the next complete signed APK."""

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
import build_stardust20_skip_v106_apk as previous
import build_updater_apk as updater
import restore_stardust_20_21 as index_helper


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
SOURCE = previous.OUTPUT
SOURCE_SHA = "81a609fc57fd68db934cfb58d672e0716fb8eb86a6fe22d62744a9c485f08271"
LUA_SHA = "8023bdee7eb770f1e5f24d3f60a0d85297dc4337859391e53b5e5835a87e1912"
OLD_LUA_SHA = "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94"
LUA = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
OUTPUT = HERE / "build/witchweapon-guild-recall-v107-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-guild-recall-v107")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v107 output or temporary directory already exists")
    if digest(SOURCE) != SOURCE_SHA:
        raise ValueError("Reviewed v106 APK changed")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient space")
    lua_blob = PROJECT / "热更新测试/主线热更候选/blobs" / LUA_SHA
    if digest(lua_blob) != LUA_SHA:
        raise ValueError("Signed release 35 Lua bundle changed")
    lua = lua_blob.read_bytes()
    with zipfile.ZipFile(SOURCE) as old:
        if hashlib.sha256(old.read(LUA)).hexdigest() != OLD_LUA_SHA:
            raise ValueError("v106 Lua is not the reviewed base bundle")
        replacements = {
            LUA: lua,
            INDEX: index_helper.patch_index(old.read(INDEX), {LUA: lua}),
            "AndroidManifest.xml": previous.previous.previous.previous.base.patch_android_manifest(
                old.read("AndroidManifest.xml"), old_code=20043106, new_code=20043107,
                old_name="2.0.1.20043106", new_name="2.0.1.20043107"),
        }
        names = old.namelist()
        if len(names) != len(set(names)) or not set(replacements).issubset(names):
            raise ValueError("v106 APK inventory changed")
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
        raise ValueError("APK signer changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        old_members = {entry.filename: entry for entry in old.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        new_members = {entry.filename: entry for entry in new.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        if set(old_members) != set(new_members):
            raise ValueError("Full APK member inventory changed")
        for member, entry in new_members.items():
            if member in replacements:
                if new.read(member) != replacements[member]:
                    raise ValueError("Modified APK member differs: " + member)
            elif (old_members[member].CRC, old_members[member].file_size,
                  old_members[member].compress_size) != (
                  entry.CRC, entry.file_size, entry.compress_size):
                raise ValueError("Unrelated APK member changed: " + member)
        for critical in ("assets/m.version", "assets/update_endpoint.txt",
                         "assets/update_public_key.der", "assets/online_endpoint.txt",
                         "assets/offline_responses.json", "classes2.dex"):
            if old.read(critical) != new.read(critical):
                raise ValueError("Critical client member changed: " + critical)
    signed.replace(OUTPUT)
    result = {"source": str(SOURCE), "sourceSha256": SOURCE_SHA,
              "result": str(OUTPUT), "resultSha256": digest(OUTPUT),
              "androidVersionCode": 20043107,
              "changedPayload": sorted(replacements),
              "signingCertificateSha256": match.group(1),
              "deviceValidated": False}
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise ValueError("v107 report did not round trip")
    print("SIGNED_GUILD_RECALL_V107_OK", result["resultSha256"])
    return result


if __name__ == "__main__":
    build()
