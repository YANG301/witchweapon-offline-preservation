"""Mirror the guild-refresh Lua hotfix in a complete signed Android APK."""

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
import build_updater_apk as updater
from build_visible_hotupdate_v8_apk import patch_android_manifest


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-hide-guide-envelope-v92-test.apk"
SOURCE_SHA256 = "b77d722ffad01337eb1ec2b5ab6d130a480a5279c7b1074d65a33709bff4c55e"
LUA_SHA256 = "b05e31437acd6055178da7057dbda118239af29222c9988c877b31267282aeaf"
LUA = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs") / LUA_SHA256
BUNDLE = "assets/assetbundle/lua/lua_projx_patch.ab"
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
OUTPUT = HERE / "build/witchweapon-guild-refresh-v93-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-guild-refresh-v93")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
CHANGED = {MANIFEST, INDEX, BUNDLE}


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> None:
    if sha_file(SOURCE) != SOURCE_SHA256 or sha_file(LUA) != LUA_SHA256:
        raise ValueError("Reviewed v92 APK or signed guild Lua blob changed")
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("Guild v93 output or build intermediate already exists")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    for path in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not path.is_file():
            raise FileNotFoundError(path)
    with zipfile.ZipFile(SOURCE) as old:
        members = old.namelist()
        if len(members) != len(set(members)) or not CHANGED.issubset(members):
            raise ValueError("Unexpected v92 APK member inventory")
        lua = LUA.read_bytes()
        replacements = {
            MANIFEST: patch_android_manifest(
                old.read(MANIFEST), old_code=20043092, new_code=20043093,
                old_name="2.0.1.20043092", new_name="2.0.1.20043093"),
            BUNDLE: lua,
            INDEX: apk_tools.patch_index(old.read(INDEX),
                                         {"/lua/lua_projx_patch.ab": lua}),
        }
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
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], environment)
    verified = signer.run([*command, "verify", "--verbose", "--print-certs", signed], environment)
    cert = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", verified)
    if not cert or cert.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("APK signing certificate changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        a = {entry.filename: entry for entry in old.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        b = {entry.filename: entry for entry in new.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        if set(a) != set(b):
            raise ValueError("APK member inventory changed")
        for name in a:
            if name in replacements:
                if new.read(name) != replacements[name]:
                    raise ValueError("Patched APK member differs: " + name)
            elif (a[name].CRC, a[name].file_size, a[name].compress_size) != (
                    b[name].CRC, b[name].file_size, b[name].compress_size):
                raise ValueError("Unrelated APK member changed: " + name)
        for name in ("assets/m.version", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/online_endpoint.txt",
                     "assets/offline_responses.json", "classes2.dex"):
            if old.read(name) != new.read(name):
                raise ValueError("Critical client member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    report = {"source": str(SOURCE), "sourceSha256": SOURCE_SHA256,
              "result": str(OUTPUT), "resultSha256": sha_file(OUTPUT),
              "androidVersionCode": 20043093,
              "changedPayload": sorted(CHANGED), "luaSha256": LUA_SHA256,
              "signingCertificateSha256": cert.group(1), "deviceValidated": False}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report did not round-trip")
    print("GUILD_REFRESH_V93_APK_OK", report["resultSha256"])


if __name__ == "__main__":
    build()
