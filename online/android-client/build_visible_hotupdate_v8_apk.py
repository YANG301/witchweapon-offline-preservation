"""Sync the sequence-8 visible Lua update into a future full APK.

The already installed 20043085 APK remains unchanged. This signed full APK
contains the exact AssetBundle to be published through the update service.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zipfile

from build_online_apk import patch_index
from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run
import build_original_ui_quest_refresh_v6_apk as signer
import patch_manifest as axml
import patch_visible_hotupdate_v8 as visible


SOURCE = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-online.apk")
SOURCE_SHA256 = "39f6285818fe2d7076f4b99803d18d1d20ad41659955359b5df100b355f65a92"
OUTPUT = Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-热更8同步版.apk")
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-visible-hotupdate-v8")
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
PACKAGE = "com.codex.witchweapon.online.originalui.test"
OLD_CODE = 20043085
NEW_CODE = 20043086
OLD_NAME = "2.0.1.20043085"
NEW_NAME = "2.0.1.20043086"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
SIGNER_CERT_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
VISIBLE_CHANGE = "Email → Email · 热更8"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def patch_android_manifest(raw: bytes, *,
                           old_code: int | None = None,
                           new_code: int | None = None,
                           old_name: str | None = None,
                           new_name: str | None = None) -> bytes:
    old_code = OLD_CODE if old_code is None else old_code
    new_code = NEW_CODE if new_code is None else new_code
    old_name = OLD_NAME if old_name is None else old_name
    new_name = NEW_NAME if new_name is None else new_name
    chunks = axml.split_chunks(raw)
    strings, info = axml.string_pool(chunks[0])
    root = next(chunk for chunk in chunks if axml.start_tag(chunk, strings) == "manifest")
    attrs = axml.attributes(root, strings)
    if axml.attribute_value(root, attrs["package"], strings) != PACKAGE:
        raise ValueError("Unexpected Android package")
    if axml.attribute_value(root, attrs["versionName"], strings) != old_name:
        raise ValueError("Unexpected Android version name")
    position = attrs["versionCode"]
    if root[position + 15] != 0x10 or axml.u32(root, position + 16) != old_code:
        raise ValueError("Unexpected Android version code")
    struct.pack_into("<I", root, position + 16, new_code)
    axml.assign_string(root, attrs["versionName"], new_name, strings)
    body = axml.serialize_pool(chunks[0], strings, info)
    body += b"".join(bytes(chunk) for chunk in chunks[1:])
    result = struct.pack("<HHI", 3, 8, len(body) + 8) + body
    checked = axml.split_chunks(result)
    values, _ = axml.string_pool(checked[0])
    root = next(chunk for chunk in checked if axml.start_tag(chunk, values) == "manifest")
    attrs = axml.attributes(root, values)
    if axml.u32(root, attrs["versionCode"] + 16) != new_code:
        raise ValueError("Updated Android version code did not round-trip")
    if axml.attribute_value(root, attrs["versionName"], values) != new_name:
        raise ValueError("Updated Android version name did not round-trip")
    return result


def replacements() -> dict[str, bytes]:
    if not SOURCE.is_file() or sha_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Installed source APK differs from reviewed 20043085")
    for dependency in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                       signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not dependency.is_file():
            raise FileNotFoundError(dependency)
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Source APK has duplicate ZIP members")
        if apk.read("assets/m.version") != b"2.0.1.20043082\r\n":
            raise ValueError("Unexpected Unity resource version")
        if apk.read("assets/update_endpoint.txt") != b"https://212.192.15.11:18445\n":
            raise ValueError("Unexpected signed update origin")
        bundle = visible.patch(apk.read(visible.MEMBER))
        index = patch_index(apk.read(INDEX), {"/lua/lua_projx_patch.ab": bundle})
        manifest = patch_android_manifest(apk.read(MANIFEST))
    return {visible.MEMBER: bundle, INDEX: index, MANIFEST: manifest}


def verify_payload(candidate: Path, changes: dict[str, bytes]) -> int:
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(candidate) as new:
        before = {item.filename: item for item in old.infolist()
                  if not SIGNATURE.fullmatch(item.filename)}
        after = {item.filename: item for item in new.infolist()
                 if not SIGNATURE.fullmatch(item.filename)}
        if set(before) != set(after) or len(after) != len([
            item for item in new.infolist() if not SIGNATURE.fullmatch(item.filename)
        ]):
            raise ValueError("Full APK payload inventory changed")
        for name, value in changes.items():
            if new.read(name) != value:
                raise ValueError("Signed APK differs at " + name)
        for name in set(before) - set(changes):
            left, right = before[name], after[name]
            if (left.file_size, left.CRC, left.compress_size) != (
                right.file_size, right.CRC, right.compress_size
            ):
                raise ValueError("Unrelated APK payload differs at " + name)
        return len(before) - len(changes)


def build(changes: dict[str, bytes]) -> None:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("Final output or build directory already exists")
    if TEMP.resolve().parent != Path(r"D:\Environment\Android\temp").resolve():
        raise ValueError("Unexpected portable build directory")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume is low")
    if shutil.disk_usage(OUTPUT.parent).free < SOURCE.stat().st_size + (256 << 20):
        raise OSError("Desktop output volume is low")
    TEMP.mkdir(parents=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(
        unsigned, "x", allowZip64=False
    ) as new:
        for item in old.infolist():
            if SIGNATURE.fullmatch(item.filename):
                continue
            if item.filename in changes:
                new.writestr(copy.copy(item), changes[item.filename])
            else:
                copy_compressed_entry(old, new, item)
    run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    signing = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    environment["TEMP"] = environment["TMP"] = str(TEMP)
    run([*signing, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
         "--ks-pass", "env:WITCH_TEST_KEYPASS",
         "--key-pass", "env:WITCH_TEST_KEYPASS", "--v4-signing-enabled", "false",
         "--out", signed, aligned], environment)
    signature = run([*signing, "verify", "--verbose", "--print-certs", signed],
                    environment)
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})",
                      signature)
    if not match or match.group(1) != SIGNER_CERT_SHA256:
        raise ValueError("APK signing identity changed")
    run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    unchanged = verify_payload(signed, changes)
    if sha_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Source APK changed during build")
    shutil.copyfile(signed, OUTPUT)
    if sha_file(OUTPUT) != sha_file(signed):
        raise ValueError("Desktop APK copy differs from signed candidate")
    result = {
        "sourceApk": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "resultApk": str(OUTPUT), "resultSha256": sha_file(OUTPUT),
        "androidVersionCode": NEW_CODE,
        "embeddedAssetVersion": "2.0.1.20043082",
        "changedPayload": sorted(changes),
        "unchangedPayloadCount": unchanged,
        "luaBundleSha256": sha(changes[visible.MEMBER]),
        "visibleChange": VISIBLE_CHANGE,
        "signingCertificateSha256": match.group(1),
        "runtimeValidated": False,
    }
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise ValueError("Build report did not round-trip")
    print("VISIBLE_HOTUPDATE_FULL_APK_OK", result["resultSha256"], OUTPUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--build", action="store_true")
    arguments = parser.parse_args()
    changes = replacements()
    if arguments.check:
        print("VISIBLE_HOTUPDATE_INPUT_OK", sha(changes[visible.MEMBER]),
              len(changes[INDEX]), len(changes[MANIFEST]))
    else:
        build(changes)


if __name__ == "__main__":
    main()
