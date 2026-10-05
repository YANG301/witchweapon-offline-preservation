"""Fold the XP particle visibility fix and newest reviewed Lua into v110 APK.

This is the next full-package build path. The normal signed resource update is
published independently, so players do not need a new APK for this visual fix.
"""

from __future__ import annotations

import copy
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile
import UnityPy

HERE = Path(__file__).resolve().parent
ONLINE = HERE.parent.parent / "魔女兵器在线版" / "android-client"
sys.path.insert(0, str(ONLINE))

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_updater_apk as updater
from build_visible_hotupdate_v8_apk import patch_android_manifest
import restore_stardust_20_21 as index_helper
from patch_shop_batch_native import patch as restore_batch_native


SOURCE = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地双区服-v110-测试.apk")
SOURCE_SHA = "c9cd2b5d22be186a8509c44b0ec6fcfee5d68842407a926371fd480572d74cbb"
OUTPUT = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地双区服-v111-测试.apk")
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-settlement-v111")
ROOT = ONLINE.parent / "热更新测试" / "主线热更候选"
OVERRIDE = ONLINE / "resources-overrides" / "settlement-levelup-hidden.ab"
SETTLEMENT = "assets/assetbundle/assets/resources/ui/prefab/settlement.ab"
LUA = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
SOURCE_BUNDLE_SHA = "d92a20aee6f8635eb4c47f9072699e0cf68712a6dec7374201a5cd9b9b8ca147"
PATCHED_BUNDLE_SHA = "2481bcb680cc40a9027aaf1f2fa4a486ff2d52e6a56c1959b35390fb5e041669"
DEFAULT_RELEASE = "119-b238404543a1718a7090e2e00d116d42ca98dcca071449510620983ae708c899"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(release_name: str, check_only: bool = False) -> None:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v111 output, report or temporary build already exists")
    if file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError("Reviewed v110 source APK changed")
    if shutil.disk_usage(TEMP.parent).free < 4 * SOURCE.stat().st_size:
        raise OSError("Android portable build volume needs four APK sizes free")
    if shutil.disk_usage(OUTPUT.parent).free < SOURCE.stat().st_size + 64 * 1024 * 1024:
        raise OSError("Desktop lacks room for the final APK")
    release_dir = ROOT / "releases" / release_name
    manifest_raw = (release_dir / "manifest.json").read_bytes()
    if sha(manifest_raw) != release_name.split("-", 1)[1]:
        raise ValueError("Selected release manifest is corrupt")
    manifest = json.loads(manifest_raw)
    if (manifest["targetAppVersion"] != "2.0.1.20043082"
            or manifest["releaseSequence"] != int(release_name.split("-", 1)[0])
            or manifest["releaseSequence"] < 55):
        raise ValueError("Selected release is incompatible with v110")
    listed = {item["path"]: item for item in manifest["assets"]}
    lua_item = listed.get("assetbundle/lua/lua.ab")
    settlement_item = listed.get("assetbundle/assets/resources/ui/prefab/settlement.ab")
    if lua_item is None or settlement_item is None or settlement_item["sha256"] != PATCHED_BUNDLE_SHA:
        raise ValueError("Signed release does not contain the reviewed level-up repair")
    lua = (ROOT / "blobs" / lua_item["sha256"]).read_bytes()
    patched = OVERRIDE.read_bytes()
    if sha(lua) != lua_item["sha256"] or sha(patched) != PATCHED_BUNDLE_SHA:
        raise ValueError("Reviewed resource blob or APK override changed")
    lua_environment = UnityPy.load(lua)
    init_scripts = [obj.read_typetree()["m_Script"] for obj in lua_environment.objects
                    if obj.type.name == "TextAsset" and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(init_scripts) != 1 or "ONLINE_SETTLEMENT_EFFECT_ORDER" in init_scripts[0]:
        raise ValueError("Selected release still includes the retired draw-order experiment")
    with zipfile.ZipFile(SOURCE) as old:
        if old.read("assets/m.version").decode("ascii").strip() != manifest["targetAppVersion"]:
            raise ValueError("APK Unity resource version differs from signed release")
        sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        public = serialization.load_der_public_key(old.read("assets/update_public_key.der"))
        public.verify(base64.b64decode((release_dir / "manifest.sig").read_bytes()),
                      manifest_raw, padding.PKCS1v15(), hashes.SHA256())
        if sha(old.read(SETTLEMENT)) != SOURCE_BUNDLE_SHA:
            raise ValueError("v110 settlement bundle changed")
        # Bundle every resource from the selected signed snapshot. New full
        # APKs must not regress previous hotfixes when installed offline.
        bundled_resources = {}
        for logical, resource in listed.items():
            payload = (ROOT / "blobs" / resource["sha256"]).read_bytes()
            if sha(payload) != resource["sha256"] or len(payload) != resource["size"]:
                raise ValueError("Signed resource differs: " + logical)
            member = "assets/" + logical
            if member not in old.namelist():
                raise ValueError("Resource is absent from v110 APK: " + member)
            if sha(old.read(member)) != resource["sha256"]:
                bundled_resources[member] = payload
        index = index_helper.patch_index(old.read(INDEX), bundled_resources)
        android_manifest = patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043110, new_code=20043111,
            old_name="2.0.1.20043110", new_name="2.0.1.20043111")
        native_member = 'lib/arm64-v8a/libil2cpp.so'
        restored_native = restore_batch_native(old.read(native_member))
    changes = {**bundled_resources, INDEX: index, "AndroidManifest.xml": android_manifest,
               native_member: restored_native}
    if check_only:
        print("SETTLEMENT_APK_INPUTS_VERIFIED", manifest["releaseSequence"],
              lua_item["sha256"], PATCHED_BUNDLE_SHA, flush=True)
        return
    TEMP.mkdir(parents=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for entry in old.infolist():
            if SIGNATURE.fullmatch(entry.filename):
                continue
            if entry.filename in changes:
                new.writestr(copy.copy(entry), changes[entry.filename])
            else:
                adapter.copy_compressed_entry(old, new, entry)
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    command = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    environment["TEMP"] = environment["TMP"] = str(TEMP)
    signer.run([*command, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], environment)
    verified = signer.run([*command, "verify", "--verbose", "--print-certs", signed], environment)
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", verified)
    if not match or match.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("APK signer changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        old_files = {entry.filename: entry for entry in old.infolist()
                     if not SIGNATURE.fullmatch(entry.filename)}
        new_files = {entry.filename: entry for entry in new.infolist()
                     if not SIGNATURE.fullmatch(entry.filename)}
        if set(old_files) != set(new_files):
            raise ValueError("Unexpected APK payload inventory")
        for name, previous in old_files.items():
            current = new_files[name]
            if name in changes:
                if new.read(name) != changes[name]:
                    raise ValueError("Signed APK differs from prepared member: " + name)
            elif (previous.CRC, previous.file_size, previous.compress_size) != (
                    current.CRC, current.file_size, current.compress_size):
                raise ValueError("Unrelated APK member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    report = {"source": str(SOURCE), "result": str(OUTPUT),
              "resultSha256": file_sha(OUTPUT), "androidVersionCode": 20043111,
              "bundledSignedReleaseSequence": manifest["releaseSequence"],
              "changedPayload": sorted(changes), "unchangedPayloadMembersChecked": len(old_files) - len(changes),
              "signingCertificateSha256": match.group(1), "physicalDeviceValidated": False}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("UTF-8 build report round-trip failed")
    print("SIGNED_SETTLEMENT_V111_READY", report["resultSha256"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", nargs="?", default=DEFAULT_RELEASE)
    parser.add_argument("--check", action="store_true", help="Verify inputs without creating a large APK")
    options = parser.parse_args()
    build(options.release, options.check)
