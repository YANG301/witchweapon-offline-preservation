"""Put local mode in the original server list with independent game routing."""

from __future__ import annotations

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
import restore_stardust_20_21 as index_helper
import build_local_mode_apk as local_builder
import patch_local_mode_bridge as bridge
import patch_local_mode_update as update_guard
import patch_server_list_mode as server_list
import patch_server_list_assets as server_assets
import patch_local_mode_login_label as old_label


SOURCE = local_builder.SOURCE
SOURCE_SHA = local_builder.SOURCE_SHA256
SOURCE_DEX_SHA = local_builder.SOURCE_DEX_SHA256
FINAL_DEX_SHA = "381fb6ae07047b45c51b89323712aa6b9bf9150dfa5cd17d62cb3d3b5e037e52"
RELEASE = (HERE.parent.parent / "魔女兵器在线版" / "热更新测试" /
           "主线热更候选" / "releases" /
           "43-2cc5f626dbbb12a7cf53a264c65125112346e489425fbe2b9b8cad7ce945f1b0" /
           "manifest.json")
BLOBS = HERE.parent.parent / "魔女兵器在线版" / "热更新测试" / "主线热更候选" / "blobs"
LUA = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
LUA_SHA = "f7117414a673375030415cbf7d032eb0d442279472a8ae9b60606ea9c1f774e8"
INDEX_SHA = old_label.ASSET_INDEX_SHA256
TEMP = Path(r"D:\Environment\Android\temp\witch-server-list-v110-rebuild-confirm")
OUTPUT = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地双区服-v110-测试.apk")
REPORT = OUTPUT.with_suffix(".json")
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Java source anchor missing or ambiguous: " + old[:90])
    return source.replace(old, new, 1)


def integrated_app(source: bytes) -> bytes:
    return server_list.patch(source)


def integrated_updater(source: bytes) -> bytes:
    """Treat release 43 as the APK baseline when an older overlay remains."""
    text = update_guard.patch(source).decode("utf-8")
    text = replace_once(text,
        '            String recorded = state.optString("embeddedVersion", "");\n',
        '''            String recorded = state.optString("embeddedVersion", "");
            // This APK already embeds every resource from signed release 43.
            // An older same-version overlay must not replace its newer Lua.
            if (state.optLong("releaseSequence", 0) > 0
                    && state.optLong("releaseSequence", 0) < 43) {
                isolateActive(active, new File(root, INCOMPATIBLE));
                JSONObject reset = emptyState();
                reset.put("embeddedVersion", bundled);
                reset.put("highWater", Math.max(43, state.optLong("highWater", 0)));
                writeState(reset);
                state = reset;
                recorded = bundled;
            } else if (state.optLong("highWater", 0) < 43) {
                state.put("highWater", 43);
                writeState(state);
            }
''')
    return text.encode("utf-8")


def compile_integrated_dex(v106_dex: bytes) -> bytes:
    old_classes = set(adapter.dex_classes(v106_dex))
    # Adding the second listener shifts one generated anonymous class name.
    old_classes.remove("Lcom/codex/witchweapon/OfflineApplication$9$1;")
    adapter.TEMP = TEMP
    sources = updater._compile_sources(TEMP, baseline=False, mode="production")
    app = sources[0]
    source_root = ONLINE / "src/com/codex/witchweapon"
    app.write_text(updater.inherited_application(
        integrated_app(bridge.ONLINE_APPLICATION.read_bytes()).decode("utf-8")),
        encoding="utf-8")
    update_source = source_root / "AssetUpdateManager.java"
    if sources.count(update_source) != 1:
        raise ValueError("Unexpected signed updater source inventory")
    update_copy = app.with_name("AssetUpdateManager.java")
    update_copy.write_text(integrated_updater(update_source.read_bytes()).decode("utf-8"),
                           encoding="utf-8")
    sources[sources.index(update_source)] = update_copy
    sources.append(bridge.LOCAL_BRIDGE)
    dex, classes = adapter.compile_dex(sources, old_classes)
    current = set(classes)
    baseline = set(adapter.dex_classes(v106_dex))
    if baseline - current != {"Lcom/codex/witchweapon/OfflineApplication$9$1;"} or current - baseline != {
            "Lcom/codex/witchweapon/LocalModeBridge;",
            "Lcom/codex/witchweapon/LocalModeBridge$Reply;",
            "Lcom/codex/witchweapon/OfflineApplication$10;",
            "Lcom/codex/witchweapon/OfflineApplication$10$1;"}:
        raise ValueError("Unexpected two-zone DEX class inventory")
    if sha(dex) != FINAL_DEX_SHA:
        raise ValueError("Two-zone DEX is not reproducible from v106")
    return dex


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError("Reviewed v106 APK is missing or changed")
    manifest = json.loads(RELEASE.read_text(encoding="utf-8"))
    if (manifest["releaseSequence"] != 43 or
            manifest["targetAppVersion"] != "2.0.1.20043082" or
            len(manifest["assets"]) != 73):
        raise ValueError("Signed release 43 inventory changed")
    listed = {"assets/" + item["path"]: item for item in manifest["assets"]}
    if (listed[LUA]["sha256"] != LUA_SHA or
            any(name in listed for name in (
                "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab",
                "assets/assetbundle/scene/loginfromal.ab"))):
        raise ValueError("Signed release conflicts with local login")
    with zipfile.ZipFile(SOURCE) as old:
        if len(old.namelist()) != len(set(old.namelist())):
            raise ValueError("Duplicate source APK members")
        if (sha(old.read("classes2.dex")) != SOURCE_DEX_SHA or
                sha(old.read(LUA)) != "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94" or
                sha(old.read(INDEX)) != INDEX_SHA):
            raise ValueError("Reviewed v106 payload changed")
        for name, item in listed.items():
            if name != LUA and (name not in old.namelist()
                                or sha(old.read(name)) != item["sha256"]):
                raise ValueError("APK missing a release 43 resource: " + name)
        lua = (BLOBS / LUA_SHA).read_bytes()
        if sha(lua) != LUA_SHA:
            raise ValueError("Signed Lua blob changed")
        labelled = old_label.patch_login_resources({name: old.read(name)
                                                    for name in old_label.LOGIN_BUNDLES})
        bundles = server_assets.patch(labelled)
        index = old_label.patch_login_asset_index(old.read(INDEX), labelled)
        index = index_helper.patch_index(index, {LUA: lua})
        index = index_helper.patch_index(index, bundles)
        original_dex = old.read("classes2.dex")
        apk_manifest = patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043106, new_code=20043108,
            old_name="2.0.1.20043106", new_name="2.0.1.20043108")
        apk_manifest = patch_android_manifest(
            apk_manifest, old_code=20043108, new_code=20043109,
            old_name="2.0.1.20043108", new_name="2.0.1.20043109")
        apk_manifest = patch_android_manifest(
            apk_manifest, old_code=20043109, new_code=20043110,
            old_name="2.0.1.20043109", new_name="2.0.1.20043110")
    dex = compile_integrated_dex(original_dex)
    return {**bundles, LUA: lua, INDEX: index, "classes2.dex": dex,
            "AndroidManifest.xml": apk_manifest}


def build() -> None:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v110 output or temporary build directory already exists")
    if shutil.disk_usage(TEMP.parent).free < 4 * SOURCE.stat().st_size:
        raise OSError("Portable Android build volume needs four APK sizes free")
    if shutil.disk_usage(OUTPUT.parent).free < SOURCE.stat().st_size + 64 * 1024 * 1024:
        raise OSError("Desktop lacks room for the final APK")
    TEMP.mkdir(parents=True)
    changes = prepare()
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
        raise ValueError("Integrated APK signer changed")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", signed])
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        old_payload = {entry.filename: entry for entry in old.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        new_payload = {entry.filename: entry for entry in new.infolist()
                       if not SIGNATURE.fullmatch(entry.filename)}
        if set(old_payload) != set(new_payload):
            raise ValueError("Unexpected APK payload inventory")
        for name, previous in old_payload.items():
            current = new_payload[name]
            if name in changes:
                if new.read(name) != changes[name]:
                    raise ValueError("Signed APK differs from prepared member: " + name)
            elif (previous.CRC, previous.file_size, previous.compress_size) != (
                    current.CRC, current.file_size, current.compress_size):
                raise ValueError("Unrelated APK member changed: " + name)
        for name in ("assets/online_endpoint.txt", "assets/update_endpoint.txt",
                     "assets/update_public_key.der", "assets/m.version",
                     "assets/offline_responses.json", "classes.dex", LUA):
            if old.read(name) != new.read(name):
                raise ValueError("Protected client member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    report = {"source": str(SOURCE), "sourceSha256": SOURCE_SHA,
              "result": str(OUTPUT), "resultSha256": file_sha(OUTPUT),
              "androidVersionCode": 20043110,
              "signedReleaseSequenceEmbedded": 43,
              "changedPayload": sorted(changes),
              "unchangedPayloadMembersChecked": len(old_payload) - len(changes),
              "signingCertificateSha256": match.group(1),
              "onlineApiAndUpdateOriginPreserved": True,
              "twoIndependentZoneEndpoints": True,
              "guestButtonHidden": True,
              "physicalDeviceValidated": False}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report UTF-8 round trip failed")
    print("SIGNED_SERVER_LIST_V110_OK", report["resultSha256"], flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--verify-source"]:
        if TEMP.exists():
            raise FileExistsError("Rebuild-check temporary directory already exists")
        TEMP.mkdir(parents=True)
        expected = prepare()
        with zipfile.ZipFile(OUTPUT) as apk:
            for name, content in expected.items():
                if apk.read(name) != content:
                    raise ValueError("v110 cannot be reproduced from v106: " + name)
        print("V110_REPRODUCIBLE_FROM_V106", sorted(expected), flush=True)
    elif len(sys.argv) == 1:
        build()
    else:
        raise SystemExit("Use --verify-source or no arguments")
