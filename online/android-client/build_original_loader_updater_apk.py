"""Build an in-place APK that checks signed assets from the original Unity loading screen.

The distributed full APK is immutable. Only AndroidManifest.xml and
classes2.dex change; the latest mainline Lua fix and all player-facing assets
remain byte-identical to the already reviewed full APK.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_updater_apk as updater
import patch_original_loader_manifest as manifest_patch


SOURCE = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-新丰洲-主线同步版.apk")
SOURCE_SHA256 = "b2772c4d503265ce65b6b1a257839dd4e00e4ef2fc36ad09cc526123dbcece38"
OUTPUT = Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-原版资源检查版.apk")
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-original-loader-v1")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
CHANGED = frozenset(("AndroidManifest.xml", "classes2.dex"))
CRITICAL_UNCHANGED = (
    "classes.dex", "assets/m.version", "assets/m.assets_list.txt",
    "assets/update_endpoint.txt", "assets/update_public_key.der",
    "assets/online_endpoint.txt", "assets/offline_responses.json",
    "assets/assetbundle/lua/lua_projx_patch.ab",
)


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare() -> dict[str, bytes]:
    updater.require_file(SOURCE, SOURCE_SHA256)
    updater.require_file(updater.PROD_V11, updater.PROD_V11_SHA256)
    for path in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not path.is_file():
            raise FileNotFoundError(path)
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or not CHANGED.issubset(names):
            raise ValueError("Unexpected source APK inventory")
        if apk.read("assets/m.version") != b"2.0.1.20043082\r\n":
            raise ValueError("Unexpected Unity resource version")
        if apk.read("assets/update_endpoint.txt") != b"https://212.192.15.11:18445\n":
            raise ValueError("Unexpected signed update origin")
        if apk.read("assets/online_endpoint.txt") != b"https://212.192.15.11:18443\n":
            raise ValueError("Unexpected gameplay API origin")
        with zipfile.ZipFile(Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-可更新版.apk")) as older:
            if apk.read("classes2.dex") != older.read("classes2.dex"):
                raise ValueError("Latest full APK changed the native bridge unexpectedly")
        return {"AndroidManifest.xml": manifest_patch.patch(apk.read("AndroidManifest.xml"))}


def verify_payload(candidate: Path, replacements: dict[str, bytes]) -> int:
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(candidate) as built:
        old = {name: info for name, info in ((i.filename, i) for i in source.infolist())
               if not SIGNATURE.fullmatch(name)}
        new = {name: info for name, info in ((i.filename, i) for i in built.infolist())
               if not SIGNATURE.fullmatch(name)}
        if set(old) != set(new) or len(new) != len([i for i in built.infolist()
                                                  if not SIGNATURE.fullmatch(i.filename)]):
            raise ValueError("Signed APK payload inventory changed")
        if set(replacements) != CHANGED:
            raise ValueError("Unexpected patch scope")
        for name, value in replacements.items():
            if built.read(name) != value:
                raise ValueError("Signed replacement differs: " + name)
        for name in CRITICAL_UNCHANGED:
            if built.read(name) != source.read(name):
                raise ValueError("Critical unchanged payload differs: " + name)
        for name in set(old) - set(replacements):
            left, right = old[name], new[name]
            if (left.file_size, left.CRC, left.compress_size) != (
                    right.file_size, right.CRC, right.compress_size):
                raise ValueError("Unrelated payload differs: " + name)
        before_classes = set(adapter.dex_classes(source.read("classes2.dex")))
        after_classes = set(adapter.dex_classes(built.read("classes2.dex")))
        changed_classes = before_classes ^ after_classes
        allowed = ("Lcom/codex/witchweapon/UpdateBootstrapActivity$",
                   "Lcom/codex/witchweapon/OfflineApplication$",
                   "Lcom/codex/witchweapon/AssetUpdateManager$")
        if any(not name.startswith(allowed) for name in changed_classes):
            raise ValueError("Unexpected helper class inventory difference")
        return len(old) - len(replacements)


def build(replacements: dict[str, bytes]) -> None:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("Final output or build directory already exists")
    if TEMP.resolve().parent != Path(r"D:\Environment\Android\temp").resolve():
        raise ValueError("Unexpected portable Android build directory")
    if shutil.disk_usage(TEMP.parent).free < 4 * SOURCE.stat().st_size:
        raise OSError("Portable Android build volume has insufficient space")
    if shutil.disk_usage(OUTPUT.parent).free < SOURCE.stat().st_size + 256 * 1024 * 1024:
        raise OSError("Desktop volume has insufficient space")
    TEMP.mkdir(parents=True)
    new_dex, added_classes = updater.compile_and_prove(updater.PROD_V11, "production", TEMP)
    replacements["classes2.dex"] = new_dex
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(
            unsigned, "x", allowZip64=False) as target:
        for info in source.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in replacements:
                target.writestr(copy.copy(info), replacements[info.filename])
            else:
                adapter.copy_compressed_entry(source, target, info)
    signer.TEMP = TEMP
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    signer_cmd = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    signer.run([*signer_cmd, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], environment)
    signature = signer.run([*signer_cmd, "verify", "--verbose", "--print-certs", signed],
                           environment)
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", signature)
    if not match or match.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("Signing identity changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    unchanged = verify_payload(signed, replacements)
    shutil.copyfile(signed, OUTPUT)
    result = {
        "sourceApk": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "resultApk": str(OUTPUT), "resultSha256": sha256_file(OUTPUT),
        "bytes": OUTPUT.stat().st_size,
        "androidVersionCode": manifest_patch.NEW_VERSION_CODE,
        "embeddedAssetVersion": "2.0.1.20043082",
        "modifiedPayload": sorted(replacements),
        "unchangedPayloadCount": unchanged,
        "addedJavaClasses": added_classes,
        "signingCertificateSha256": match.group(1),
        "runtimeValidated": False,
    }
    if result["resultSha256"] != sha256_file(signed):
        raise ValueError("Desktop copy differs from verified signed APK")
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise ValueError("Build report did not round-trip")
    print("ORIGINAL_LOADER_UPDATER_APK_OK", result["resultSha256"], OUTPUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changes = prepare()
    if args.check:
        print("ORIGINAL_LOADER_UPDATER_INPUT_OK", SOURCE_SHA256,
              sha256_bytes(changes["AndroidManifest.xml"]))
    else:
        build(changes)


if __name__ == "__main__":
    main()
