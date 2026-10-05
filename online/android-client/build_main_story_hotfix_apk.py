"""Merge the signed StoryQuest Lua hotfix into a future full APK.

The existing distributed updater APK is immutable. The APK built here has the
same patch bytes that the update server will deliver to that installed base.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import struct
import zipfile

from build_online_apk import patch_index
from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run, sha256
import build_original_ui_quest_refresh_v6_apk as signer
import patch_main_story_task_counter as lua_patch
import patch_manifest as axml


SOURCE = Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-可更新版.apk")
SOURCE_SHA256 = "4a1a8ce44d2745b9d16932dca31bc05612a7595144832cb808b11cde3b8e8568"
OUTPUT = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-新丰洲-主线同步版.apk")
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-main-story-hotfix")
BUNDLE = lua_patch.MEMBER
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
PACKAGE = "com.codex.witchweapon.online.originalui.test"
OLD_CODE = 20043083
NEW_CODE = 20043084
NEW_NAME = "2.0.1.20043084"


def patch_android_manifest(raw: bytes) -> bytes:
    chunks = axml.split_chunks(raw)
    strings, info = axml.string_pool(chunks[0])
    manifest = next((chunk for chunk in chunks
                     if axml.start_tag(chunk, strings) == "manifest"), None)
    if manifest is None:
        raise ValueError("Android manifest start tag missing")
    attrs = axml.attributes(manifest, strings)
    if axml.attribute_value(manifest, attrs["package"], strings) != PACKAGE:
        raise ValueError("Unexpected Android package")
    old_name = axml.attribute_value(manifest, attrs["versionName"], strings)
    if old_name != "2.0.1.20043083":
        raise ValueError("Unexpected Android version name")
    code_at = attrs["versionCode"]
    if manifest[code_at + 15] != 0x10 or axml.u32(manifest, code_at + 16) != OLD_CODE:
        raise ValueError("Unexpected Android version code")
    struct.pack_into("<I", manifest, code_at + 16, NEW_CODE)
    axml.assign_string(manifest, attrs["versionName"], NEW_NAME, strings)
    data = axml.serialize_pool(chunks[0], strings, info)
    data += b"".join(bytes(chunk) for chunk in chunks[1:])
    result = struct.pack("<HHI", 3, 8, len(data) + 8) + data
    check = axml.split_chunks(result)
    values, _ = axml.string_pool(check[0])
    found = next(chunk for chunk in check if axml.start_tag(chunk, values) == "manifest")
    verified = axml.attributes(found, values)
    if (axml.u32(found, verified["versionCode"] + 16) != NEW_CODE or
            axml.attribute_value(found, verified["versionName"], values) != NEW_NAME):
        raise ValueError("Android version did not round-trip")
    return result


def replacements() -> dict[str, bytes]:
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Distributed updater APK differs from reviewed base")
    for dependency in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                       signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not dependency.is_file():
            raise FileNotFoundError(dependency)
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate APK entries")
        if apk.read("assets/m.version") != b"2.0.1.20043082\r\n":
            raise ValueError("Unexpected embedded updater asset version")
        lua = lua_patch.patch(apk.read(BUNDLE))
        index = patch_index(apk.read(INDEX), {"/lua/lua_projx_patch.ab": lua})
        android = patch_android_manifest(apk.read(MANIFEST))
    return {BUNDLE: lua, INDEX: index, MANIFEST: android}


def verify(apk_path: Path, changed: dict[str, bytes]) -> int:
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(apk_path) as new:
        original = {name for name in old.namelist() if not SIGNATURE.fullmatch(name)}
        current = {name for name in new.namelist() if not SIGNATURE.fullmatch(name)}
        if original != current or len(new.namelist()) != len(set(new.namelist())):
            raise ValueError("Full APK member set differs")
        for name, value in changed.items():
            if new.read(name) != value:
                raise ValueError("Merged full APK payload differs: " + name)
        for name in original - set(changed):
            before, after = old.getinfo(name), new.getinfo(name)
            if (before.file_size, before.CRC, before.compress_size) != (
                after.file_size, after.CRC, after.compress_size
            ):
                raise ValueError("Unrelated APK member changed: " + name)
        return len(original) - len(changed)


def build(changed: dict[str, bytes]) -> None:
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("Output already exists; do not overwrite a release")
    TEMP.mkdir(parents=True, exist_ok=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    if any(path.exists() for path in (unsigned, aligned, signed)):
        raise FileExistsError("Stale build intermediate must be reviewed")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(
        unsigned, "x", allowZip64=False
    ) as target:
        for info in source.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in changed:
                target.writestr(copy.copy(info), changed[info.filename])
            else:
                copy_compressed_entry(source, target, info)
    run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    command = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    environment["TEMP"] = environment["TMP"] = str(TEMP)
    run([*command, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
         "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
         "--out", signed, aligned], environment)
    signature = run([*command, "verify", "--verbose", "--print-certs", signed], environment)
    alignment = run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    unchanged = verify(signed, changed)
    if shutil.disk_usage(OUTPUT.parent).free < signed.stat().st_size + 256 * 1024 * 1024:
        raise OSError("Desktop volume lacks space for merged APK")
    shutil.copyfile(signed, OUTPUT)
    if sha256(OUTPUT) != sha256(signed):
        raise ValueError("Copied merged APK differs")
    report = {
        "baseApk": str(SOURCE), "baseSha256": SOURCE_SHA256,
        "mergedApk": str(OUTPUT), "mergedSha256": sha256(OUTPUT),
        "androidVersionCode": NEW_CODE, "androidVersionName": NEW_NAME,
        "embeddedAssetVersion": "2.0.1.20043082",
        "changedPayload": sorted(changed), "unchangedPayloadCount": unchanged,
        "luaBundleSha256": sha256_bytes(changed[BUNDLE]),
        "signatureCertificateSha256": re.search(
            r"Signer #1 certificate SHA-256 digest: ([a-f0-9]+)", signature
        ).group(1),
        "zipAlignment": alignment,
        "runtimeValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("MAIN_STORY_FULL_APK_OK", report["mergedSha256"], OUTPUT)


def sha256_bytes(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    payload = replacements()
    if args.check:
        print("MAIN_STORY_FULL_APK_CHECK_OK", sha256_bytes(payload[BUNDLE]),
              len(payload[INDEX]), len(payload[MANIFEST]))
    else:
        build(payload)
