"""Build a test APK that uses the original Unity resource progress bar."""

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
from build_visible_hotupdate_v8_apk import patch_android_manifest


HERE = Path(__file__).resolve().parent
SOURCE = Path(r"D:\Project\魔女兵器在线版\更新版\魔女兵器-新丰洲-更新进度版.apk")
SOURCE_HASH = "a8b0285c3c87e4d2de9e2a4c45232b43cc20a67fd99e62e68d629d38670161f7"
OUTPUT = HERE / "build/witchweapon-original-unity-progress-v91-test.apk"
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-original-unity-progress-v91")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
CHANGED = {"AndroidManifest.xml", "classes2.dex"}


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build() -> None:
    if not SOURCE.is_file() or sha(SOURCE) != SOURCE_HASH:
        raise ValueError("Source APK has changed")
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("Test output already exists")
    if shutil.disk_usage(TEMP.parent).free < SOURCE.stat().st_size * 4:
        raise OSError("Android portable build volume is low")
    for path in (signer.JAVA, signer.TOOLS / "zipalign.exe",
                 signer.TOOLS / "lib/apksigner.jar", signer.KEY):
        if not path.is_file():
            raise FileNotFoundError(path)
    TEMP.mkdir(parents=True)
    with zipfile.ZipFile(SOURCE) as source:
        members = source.namelist()
        if len(members) != len(set(members)) or not CHANGED.issubset(members):
            raise ValueError("Unexpected source APK contents")
        old_classes = set(adapter.dex_classes(source.read("classes2.dex")))
        old_overlay = {name for name in old_classes
                       if name.startswith("Lcom/codex/witchweapon/UpdateProgressOverlay")}
        if len(old_overlay) != 6:
            raise ValueError("Expected custom progress layer is absent")
        adapter.TEMP = TEMP
        sources = updater._compile_sources(TEMP, baseline=False, mode="production")
        new_dex, new_classes = adapter.compile_dex(sources, old_classes - old_overlay)
        if old_classes - set(new_classes) != old_overlay:
            raise ValueError("Unexpected Java class removal")
        if any(name.startswith("Lcom/codex/witchweapon/UpdateProgressOverlay")
               for name in new_classes):
            raise ValueError("Custom progress layer remains in APK")
        manifest = patch_android_manifest(
            source.read("AndroidManifest.xml"), old_code=20043089, new_code=20043091,
            old_name="2.0.1.20043089", new_name="2.0.1.20043091")
        replacements = {"AndroidManifest.xml": manifest, "classes2.dex": new_dex}
        unsigned, aligned, signed = (TEMP / name for name in
                                     ("unsigned.apk", "aligned.apk", "signed.apk"))
        with zipfile.ZipFile(unsigned, "x", allowZip64=False) as result:
            for entry in source.infolist():
                if SIGNATURE.fullmatch(entry.filename):
                    continue
                if entry.filename in replacements:
                    result.writestr(copy.copy(entry), replacements[entry.filename])
                else:
                    adapter.copy_compressed_entry(source, result, entry)
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    command = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    env = signer.signer_env()
    env["TEMP"] = env["TMP"] = str(TEMP)
    signer.run([*command, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", signed, aligned], env)
    verification = signer.run([*command, "verify", "--verbose", "--print-certs", signed], env)
    certificate = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})",
                            verification)
    if not certificate or certificate.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("Test APK signer changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(signed) as result:
        a = {entry.filename: entry for entry in source.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        b = {entry.filename: entry for entry in result.infolist()
             if not SIGNATURE.fullmatch(entry.filename)}
        if set(a) != set(b) or len(b) != sum(1 for entry in result.infolist()
                                            if not SIGNATURE.fullmatch(entry.filename)):
            raise ValueError("APK payload inventory changed")
        for name in a:
            if name in replacements:
                if result.read(name) != replacements[name]:
                    raise ValueError("Modified payload differs: " + name)
            elif (a[name].CRC, a[name].file_size, a[name].compress_size) != (
                    b[name].CRC, b[name].file_size, b[name].compress_size):
                raise ValueError("Unrelated APK payload changed: " + name)
        for name in ("assets/m.version", "assets/m.assets_list.txt",
                     "assets/online_endpoint.txt", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/offline_responses.json"):
            if source.read(name) != result.read(name):
                raise ValueError("Critical bundled resource changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    if sha(OUTPUT) != sha(signed):
        raise ValueError("Test APK differs from signed output")
    report = {"source": str(SOURCE), "sourceSha256": SOURCE_HASH,
              "result": str(OUTPUT), "resultSha256": sha(OUTPUT),
              "androidVersionCode": 20043091,
              "changedPayload": sorted(CHANGED),
              "removedCustomProgressClasses": sorted(old_overlay),
              "signingCertificateSha256": certificate.group(1),
              "originalUnityProgressRuntimeValidated": False}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report did not round-trip")
    print("ORIGINAL_UNITY_PROGRESS_APK_OK", report["resultSha256"])


if __name__ == "__main__":
    build()
