"""Build a separate guest-local APK from the reviewed v106 online client.

The online source APK, Java sources, API origin and signed update origin are
read-only inputs. This candidate is for a clean, isolated Android install.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile


HERE = Path(__file__).resolve().parent
ONLINE = HERE.parent.parent / "魔女兵器在线版" / "android-client"
sys.path.insert(0, str(ONLINE))

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_updater_apk as updater
from build_visible_hotupdate_v8_apk import patch_android_manifest
import patch_local_mode_bridge as bridge
import patch_local_mode_login_label as label
import patch_local_mode_update as update_guard


SOURCE = ONLINE / "build/witchweapon-stardust-skip-v106-test.apk"
SOURCE_SHA256 = "81a609fc57fd68db934cfb58d672e0716fb8eb86a6fe22d62744a9c485f08271"
SOURCE_DEX_SHA256 = "3831efadb2828c273eeff706efda69b30c8397fd05cd15a4e32660ab5dd6e82c"
TEMP = Path(r"D:\Environment\Android\temp\witch-local-mode-v108")
OUTPUT_DIR = Path(r"E:\Desktop\魔女兵器本地模式")
OUTPUT = OUTPUT_DIR / "魔女兵器-本地模式-v108-测试.apk"
REPORT = OUTPUT_DIR / "本地模式-v108-构建验收.json"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
ONLINE_ORIGIN = b"https://212.192.15.11:18443\n"
UPDATE_ORIGIN = b"https://212.192.15.11:18445\n"
EMBEDDED_VERSION = b"2.0.1.20043082\r\n"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def compile_bridge(source_dex: bytes) -> tuple[bytes, set[str]]:
    """Prove source parity with v106 before adding the isolated guest route."""
    old_classes = set(adapter.dex_classes(source_dex))
    adapter.TEMP = TEMP
    sources = updater._compile_sources(TEMP, baseline=False, mode="production")
    baseline, baseline_classes = adapter.compile_dex(sources, old_classes)
    if baseline != source_dex or digest(baseline) != SOURCE_DEX_SHA256 \
            or set(baseline_classes) != old_classes:
        raise ValueError("Online Java inputs no longer reproduce the v106 DEX")

    app_copy = sources[0]
    if app_copy.name != "OfflineApplication.java":
        raise ValueError("Unexpected updater Java source order")
    patched_online_source = bridge.patch(bridge.ONLINE_APPLICATION.read_bytes()).decode("utf-8")
    app_copy.write_text(updater.inherited_application(patched_online_source), encoding="utf-8")
    update_source = update_guard.ONLINE_UPDATER
    if sources.count(update_source) != 1:
        raise ValueError("Unexpected signed-updater source inventory")
    local_update = app_copy.with_name("AssetUpdateManager.java")
    local_update.write_text(update_guard.patch(update_source.read_bytes()).decode("utf-8"),
                            encoding="utf-8")
    sources[sources.index(update_source)] = local_update
    sources.append(bridge.LOCAL_BRIDGE)
    candidate, classes = adapter.compile_dex(sources, old_classes)
    added = set(classes) - old_classes
    if not old_classes.issubset(classes) or not added or any(
            not name.startswith("Lcom/codex/witchweapon/LocalModeBridge") for name in added):
        raise ValueError("Local-mode compilation changed unexpected DEX classes")
    if candidate == source_dex:
        raise ValueError("Local-mode DEX did not change")
    return candidate, added


def prepare() -> dict[str, bytes]:
    if SOURCE != label.SOURCE_APK or not SOURCE.is_file() \
            or file_digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("The reviewed v106 source APK is absent or changed")
    if bridge.check()["sourceUnchanged"] is not True:
        raise ValueError("Online Java source unexpectedly changed")
    if update_guard.check()["sourceUnchanged"] is not True:
        raise ValueError("Online signed-updater source unexpectedly changed")
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate APK members")
        if source.read("assets/online_endpoint.txt") != ONLINE_ORIGIN \
                or source.read("assets/update_endpoint.txt") != UPDATE_ORIGIN \
                or source.read("assets/m.version") != EMBEDDED_VERSION:
            raise ValueError("Online API, updater or embedded asset version changed")
        original_dex = source.read("classes2.dex")
        if digest(original_dex) != SOURCE_DEX_SHA256:
            raise ValueError("Unexpected v106 Android bridge")
        manifest = patch_android_manifest(
            source.read("AndroidManifest.xml"),
            old_code=20043106, new_code=20043108,
            old_name="2.0.1.20043106", new_name="2.0.1.20043108")
    ui_source = label.read_reviewed_assets(SOURCE)
    changes = label.patch_login_assets(ui_source)
    if set(changes) != {label.LOGIN_PREFAB, label.LOGIN_SCENE,
                        "assets/m.assets_list.txt"}:
        raise ValueError("Unexpected login asset patch inventory")
    changed_dex, added_classes = compile_bridge(original_dex)
    changes.update({"AndroidManifest.xml": manifest, "classes2.dex": changed_dex})
    print("LOCAL_MODE_PREPARED", len(changes), len(added_classes), flush=True)
    return changes


def build(changes: dict[str, bytes]) -> dict[str, object]:
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("Local-mode output already exists")
    if shutil.disk_usage(TEMP).free < SOURCE.stat().st_size * 4:
        raise OSError("Portable Android build volume needs four APK sizes free")
    if shutil.disk_usage(OUTPUT_DIR.parent).free < SOURCE.stat().st_size + 64 * 1024 * 1024:
        raise OSError("Desktop lacks room for the final APK")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    unsigned, aligned, signed = (TEMP / name for name in
                                 ("unsigned.apk", "aligned.apk", "signed.apk"))
    if any(path.exists() for path in (unsigned, aligned, signed)):
        raise FileExistsError("Stale local-mode signing files require review")
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
    signing_env = signer.signer_env()
    signing_env["TEMP"] = signing_env["TMP"] = str(TEMP)
    signer.run([*command, "sign", "--ks", signer.KEY,
                "--ks-key-alias", "local", "--ks-pass", "env:WITCH_TEST_KEYPASS",
                "--key-pass", "env:WITCH_TEST_KEYPASS", "--v4-signing-enabled", "false",
                "--out", signed, aligned], signing_env)
    verified = signer.run([*command, "verify", "--verbose", "--print-certs", signed],
                          signing_env)
    certificate = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})",
                            verified)
    if not certificate or certificate.group(1) != updater.SIGNER_CERT_SHA256:
        raise ValueError("Local-mode signer differs from the reviewed test certificate")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])

    unchanged = 0
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        old_payload = {entry.filename: entry for entry in old.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        new_payload = {entry.filename: entry for entry in new.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        if set(old_payload) != set(new_payload):
            raise ValueError("Local-mode APK payload inventory changed")
        for name, previous in old_payload.items():
            current = new_payload[name]
            if name in changes:
                if new.read(name) != changes[name]:
                    raise ValueError("Signed APK differs from prepared member: " + name)
            else:
                if (previous.CRC, previous.file_size, previous.compress_size) != (
                        current.CRC, current.file_size, current.compress_size):
                    raise ValueError("Unrelated APK payload changed: " + name)
                unchanged += 1
        for name in ("assets/online_endpoint.txt", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/m.version",
                     "assets/offline_responses.json", "classes.dex"):
            if old.read(name) != new.read(name):
                raise ValueError("Online client boundary changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    if file_digest(OUTPUT) != file_digest(signed) or file_digest(SOURCE) != SOURCE_SHA256:
        raise ValueError("Final APK or source changed after signing")
    report = {
        "source": str(SOURCE), "sourceSha256": SOURCE_SHA256,
        "result": str(OUTPUT), "resultSha256": file_digest(OUTPUT),
        "androidVersionCode": 20043108,
        "changedPayload": sorted(changes),
        "changedPayloadSha256": {name: digest(raw) for name, raw in sorted(changes.items())},
        "unchangedPayloadMembersChecked": unchanged,
        "onlineApiOrigin": ONLINE_ORIGIN.decode("ascii").strip(),
        "onlineUpdateOrigin": UPDATE_ORIGIN.decode("ascii").strip(),
        "embeddedAssetVersion": EMBEDDED_VERSION.decode("ascii").strip(),
        "localService": "http://127.0.0.1:19876",
        "protectedLoginBundles": [label.LOGIN_PREFAB, label.LOGIN_SCENE],
        "signingCertificateSha256": certificate.group(1),
        "runtimeValidated": False,
        "requiresCleanTestInstall": True,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Report UTF-8 round trip failed")
    print("SIGNED_LOCAL_MODE_V108_OK", report["resultSha256"], flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", required=True)
    args = parser.parse_args()
    if not args.build:
        parser.error("Use --build")
    if TEMP.exists():
        raise FileExistsError("Existing local-mode build directory requires review")
    if SOURCE != label.SOURCE_APK:
        raise ValueError("UI patcher uses a different APK")
    TEMP.mkdir(parents=True)
    build(prepare())


if __name__ == "__main__":
    main()
