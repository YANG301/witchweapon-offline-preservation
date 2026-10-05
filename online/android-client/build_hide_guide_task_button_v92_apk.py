"""Synchronize the guide-envelope resource hotfix into a complete test APK."""

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
import patch_hide_guide_task_button as guide


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-original-unity-progress-v91-test.apk"
SOURCE_SHA256 = "8f4ae90581bea9aa6861c8c43c9eafe9a20ec9ce952025bfc60fa1dac7a0fbe6"
CURRENT_LUA = Path(r"D:\Project\魔女兵器在线版\热更新测试\主线热更候选\blobs"
                   r"\82ffcd50e67a7ad9806b10d1ffd051dbfc36fe57aaefca4f1056b2c3e30928c1")
CURRENT_LUA_SHA256 = "82ffcd50e67a7ad9806b10d1ffd051dbfc36fe57aaefca4f1056b2c3e30928c1"
LUA_MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
LUA_INDEX_KEY = "/lua/lua_projx_patch.ab"
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
OUTPUT = HERE / "build/witchweapon-hide-guide-envelope-v92-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-hide-guide-envelope-v92")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
CHANGED = {MANIFEST, INDEX, guide.MEMBER, LUA_MEMBER}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> None:
    if not SOURCE.is_file() or sha_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned original-progress APK changed")
    if not CURRENT_LUA.is_file() or sha_file(CURRENT_LUA) != CURRENT_LUA_SHA256:
        raise ValueError("Signed sequence-11 Lua bundle changed")
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("Guide-envelope build output already exists")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume has insufficient free space")
    for path in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not path.is_file():
            raise FileNotFoundError(path)
    with zipfile.ZipFile(SOURCE) as source:
        members = source.namelist()
        if len(members) != len(set(members)) or not CHANGED.issubset(members):
            raise ValueError("Unexpected APK member inventory")
        prefab = guide.patch(source.read(guide.MEMBER))
        lua = CURRENT_LUA.read_bytes()
        replacements = {
            MANIFEST: patch_android_manifest(
                source.read(MANIFEST), old_code=20043091, new_code=20043092,
                old_name="2.0.1.20043091", new_name="2.0.1.20043092"),
            guide.MEMBER: prefab,
            LUA_MEMBER: lua,
            INDEX: apk_tools.patch_index(source.read(INDEX), {
                guide.INDEX_KEY: prefab, LUA_INDEX_KEY: lua,
            }),
        }

    TEMP.mkdir(parents=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(unsigned, "x", allowZip64=False) as target:
        for entry in source.infolist():
            if SIGNATURE.fullmatch(entry.filename):
                continue
            if entry.filename in replacements:
                target.writestr(copy.copy(entry), replacements[entry.filename])
            else:
                apk_tools.copy_compressed_entry(source, target, entry)
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
        raise ValueError("Test APK signing certificate changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])

    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(signed) as result:
        a = {entry.filename: entry for entry in source.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        b = {entry.filename: entry for entry in result.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        if set(a) != set(b):
            raise ValueError("Unrelated APK member was added or removed")
        for name in a:
            if name in replacements:
                if result.read(name) != replacements[name]:
                    raise ValueError("Patched APK member differs: " + name)
            elif (a[name].CRC, a[name].file_size, a[name].compress_size) != (
                    b[name].CRC, b[name].file_size, b[name].compress_size):
                raise ValueError("Unrelated APK member changed: " + name)
        for name in ("assets/m.version", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/online_endpoint.txt",
                     "assets/offline_responses.json", "classes2.dex"):
            if source.read(name) != result.read(name):
                raise ValueError("Critical client member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    report = {
        "source": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "result": str(OUTPUT), "resultSha256": sha_file(OUTPUT),
        "androidVersionCode": 20043092,
        "changedPayload": sorted(CHANGED),
        "prefabSha256": sha(prefab), "luaSha256": sha(lua),
        "signingCertificateSha256": cert.group(1),
        "deviceValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report did not round-trip")
    print("GUIDE_ENVELOPE_V92_APK_OK", report["resultSha256"])


if __name__ == "__main__":
    build()
