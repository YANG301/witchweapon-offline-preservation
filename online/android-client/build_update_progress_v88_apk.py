"""Build the one-time Android progress bridge over the signed v87 APK.

The result keeps gameplay endpoints, player data and Unity resources fixed,
except for the small sequence-10 Lua bundle that removes test-only markers.
"""

from __future__ import annotations

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
import build_visible_hotupdate_v8_apk as manifest_patch
import patch_update_progress_release_v10 as lua_patch


HERE = Path(__file__).resolve().parent
SOURCE = Path(r"D:\Project\魔女兵器在线版\android-client\build\历史发布包\魔女兵器-新丰洲-热更9同步版.apk")
SOURCE_SHA256 = "a9ed4cfd3ae042fb988d34dfddbfc026a91f71a4a22a635e175a538e3a22fb30"
OUTPUT = HERE / "build/witchweapon-update-progress-v88-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-loader-progress-v88")
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
DEX = "classes2.dex"
CHANGED = {MANIFEST, DEX, INDEX, lua_patch.BUNDLE}
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
SOURCE_HASHES = {
    "OfflineApplication.java": "62802891ebcf26c7238415d4362ad914572256b06792b9e72646df9c23c860ef",
    "AssetUpdateManager.java": "5bb42d2216b5f90c4866b1dcbeb4ae50bd0fea134ecd9df00d807065e1d6053a",
    "UpdateProgressOverlay.java": "df8084f4384e789686f56ab83dfaa604063c7397b8545a81cdbf029634589aee",
}
EXPECTED_BUNDLE_SHA256 = "43c02447e2202d9cf7945b094f8e59e35f5f2104ed6577dae472bcd272968c9f"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare() -> tuple[dict[str, bytes], list[str]]:
    if not SOURCE.is_file() or sha_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Reviewed v87 source APK is missing or changed")
    if TEMP.exists() or OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("Build directory or APK output already exists")
    if TEMP.resolve().parent != Path(r"D:\Environment\Android\temp").resolve():
        raise ValueError("Unexpected portable build directory")
    for name, digest in SOURCE_HASHES.items():
        java = HERE / "src/com/codex/witchweapon" / name
        if not java.is_file() or sha_file(java) != digest:
            raise ValueError("Reviewed Java input is missing or changed: " + name)
    for tool in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not tool.is_file():
            raise FileNotFoundError(tool)
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume is low")
    TEMP.mkdir(parents=True)
    with zipfile.ZipFile(SOURCE) as old:
        if len(old.namelist()) != len(set(old.namelist())) or not CHANGED.issubset(old.namelist()):
            raise ValueError("Unexpected source APK inventory")
        old_dex = old.read(DEX)
        old_classes = set(adapter.dex_classes(old_dex))
        adapter.TEMP = TEMP
        sources = updater._compile_sources(TEMP, baseline=False, mode="production")
        sources.append(HERE / "src/com/codex/witchweapon/UpdateProgressOverlay.java")
        new_dex, classes = adapter.compile_dex(sources, sorted(old_classes))
        additions = set(classes) - old_classes
        if not old_classes.issubset(classes) or not additions or any(
            not name.startswith(("Lcom/codex/witchweapon/UpdateProgressOverlay",
                                 "Lcom/codex/witchweapon/OfflineApplication$",
                                 "Lcom/codex/witchweapon/AssetUpdateManager$"))
            for name in additions
        ):
            raise ValueError("Unexpected DEX class changes")
        bundle = lua_patch.patch(old.read(lua_patch.BUNDLE))
        if sha(bundle) != EXPECTED_BUNDLE_SHA256:
            raise ValueError("Sequence-10 Lua bundle differs")
        index = adapter.patch_index(old.read(INDEX), {"/lua/lua_projx_patch.ab": bundle})
        manifest = manifest_patch.patch_android_manifest(
            old.read(MANIFEST), old_code=20043087, new_code=20043088,
            old_name="2.0.1.20043087", new_name="2.0.1.20043088")
        return ({DEX: new_dex, lua_patch.BUNDLE: bundle, INDEX: index,
                 MANIFEST: manifest}, sorted(additions))


def verify(result: Path, replacements: dict[str, bytes]) -> int:
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(result) as new:
        before = {item.filename: item for item in old.infolist()
                  if not SIGNATURE.fullmatch(item.filename)}
        after = {item.filename: item for item in new.infolist()
                 if not SIGNATURE.fullmatch(item.filename)}
        if set(before) != set(after) or len(after) != len([
            item for item in new.infolist() if not SIGNATURE.fullmatch(item.filename)
        ]):
            raise ValueError("Signed APK payload inventory changed")
        if set(replacements) != CHANGED:
            raise ValueError("Unexpected patch scope")
        for name, content in replacements.items():
            if new.read(name) != content:
                raise ValueError("Signed replacement differs: " + name)
        for name in set(before) - CHANGED:
            left, right = before[name], after[name]
            if (left.file_size, left.CRC, left.compress_size) != (
                right.file_size, right.CRC, right.compress_size
            ):
                raise ValueError("Unrelated APK payload differs: " + name)
        for name in ("assets/online_endpoint.txt", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/m.version",
                     "assets/offline_responses.json", "classes.dex"):
            if old.read(name) != new.read(name):
                raise ValueError("Critical APK payload changed: " + name)
        return len(before) - len(CHANGED)


def main() -> None:
    replacements, added_classes = prepare()
    unsigned, aligned, signed = (TEMP / filename for filename in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(unsigned, "x", allowZip64=False) as new:
        for item in old.infolist():
            if SIGNATURE.fullmatch(item.filename):
                continue
            if item.filename in replacements:
                new.writestr(copy.copy(item), replacements[item.filename])
            else:
                adapter.copy_compressed_entry(old, new, item)
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    signing = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    environment = signer.signer_env()
    environment["TEMP"] = environment["TMP"] = str(TEMP)
    signer.run([*signing, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], environment)
    certificate = signer.run([*signing, "verify", "--verbose", "--print-certs", signed],
                             environment)
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", certificate)
    if not match or match.group(1) != manifest_patch.SIGNER_CERT_SHA256:
        raise ValueError("APK signing identity changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    unchanged = verify(signed, replacements)
    if sha_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Source APK changed during build")
    shutil.copyfile(signed, OUTPUT)
    if sha_file(OUTPUT) != sha_file(signed):
        raise ValueError("Signed APK copy differs")
    report = {
        "sourceApk": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "resultApk": str(OUTPUT), "resultSha256": sha_file(OUTPUT),
        "androidVersionCode": 20043088,
        "embeddedAssetVersion": "2.0.1.20043082",
        "changedPayload": sorted(CHANGED),
        "unchangedPayloadCount": unchanged,
        "luaBundleSha256": EXPECTED_BUNDLE_SHA256,
        "newDexClasses": added_classes,
        "signingCertificateSha256": match.group(1),
        "runtimeValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report did not round-trip")
    print("UPDATE_PROGRESS_APK_OK", report["resultSha256"], OUTPUT)


if __name__ == "__main__":
    main()
