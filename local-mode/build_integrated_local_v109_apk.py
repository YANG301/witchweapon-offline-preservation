"""Integrate the verified release 43 with the isolated local guest APK.

The signed public release and v108 APK are immutable inputs.  Only the Lua
bundle, its index row, Android manifest and local-mode DEX are changed.
"""

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


SOURCE = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-本地模式-v108-测试.apk")
SOURCE_SHA = "c93c7a291e03b41d6239f1dda66c43bf1cca0198052c0911a0d1de121ca87168"
SOURCE_DEX_SHA = "7e4738cd081b6159e2cae65af8966ebcdf912e6edff0bb78ce6955166adb3ad6"
RELEASE = (HERE.parent.parent / "魔女兵器在线版" / "热更新测试" /
           "主线热更候选" / "releases" /
           "43-2cc5f626dbbb12a7cf53a264c65125112346e489425fbe2b9b8cad7ce945f1b0" /
           "manifest.json")
BLOBS = HERE.parent.parent / "魔女兵器在线版" / "热更新测试" / "主线热更候选" / "blobs"
LUA = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
LUA_SHA = "f7117414a673375030415cbf7d032eb0d442279472a8ae9b60606ea9c1f774e8"
OLD_LUA_SHA = "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94"
INDEX_SHA = "0d92ee1ccd3286e09681616dd37f3b2da4aa43bec3bcbb2823cda4962b54eed3"
NEW_INDEX_SHA = "ed29e437f7633ce5b5e2c7dceb2236e9779716c3985fdd68f3b008fde2b2bf50"
TEMP = Path(r"D:\Environment\Android\temp\witch-integrated-local-v109")
OUTPUT = SOURCE.with_name("魔女兵器-在线本地整合-v109-测试.apk")
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
    """Refresh the local Lua mirror on guest entry and successful game POSTs."""
    text = bridge.patch(source).decode("utf-8")
    old = "                clearOnlineStateForLocalMode();\n                localMode = true;\n"
    new = ("                clearOnlineStateForLocalMode();\n"
           "                syncLocalMirror();\n"
           "                localMode = true;\n")
    if text.count(old) != 2:
        raise ValueError("Expected both guest account entry points")
    text = text.replace(old, new)
    text = replace_once(text,
        "                    return new Reply(local.status, local.contentType, local.body);\n",
        """                    if (\"POST\".equals(method) && local.status >= 200 && local.status < 300) {
                        try { syncLocalMirror(); }
                        catch (IOException unavailable) {
                            // Preserve the successful business response; the next
                            // local request can refresh the read-only UI mirror.
                        }
                    }
                    return new Reply(local.status, local.contentType, local.body);
""")
    text = replace_once(text,
        "    private static Reply localAccountUnavailable() {\n",
        """    private void syncLocalMirror() throws IOException {
        LocalModeBridge.Reply state = LocalModeBridge.requestGame(
                \"GET\", \"/__state\", null, null);
        if (state.status != 200 || !state.contentType.toLowerCase(Locale.ROOT)
                .startsWith(\"application/json\"))
            throw new IOException(\"Local state mirror unavailable\");
        LegacyStateMirror.write(getFilesDir(), state.body);
    }

    private static Reply localAccountUnavailable() {
""")
    return text.encode("utf-8")


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


def compile_integrated_dex(reviewed_v108: bytes) -> bytes:
    with zipfile.ZipFile(local_builder.SOURCE) as original:
        v106_dex = original.read("classes2.dex")
    old_classes = set(adapter.dex_classes(v106_dex))
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
    if set(classes) != set(adapter.dex_classes(reviewed_v108)):
        raise ValueError("Integrated DEX class inventory changed")
    if dex == reviewed_v108:
        raise ValueError("Integrated DEX did not change")
    return dex


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError("Reviewed v108 APK is missing or changed")
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
    lua_file = BLOBS / LUA_SHA
    if file_sha(lua_file) != LUA_SHA:
        raise ValueError("Signed release 43 Lua blob changed")
    lua = lua_file.read_bytes()
    with zipfile.ZipFile(SOURCE) as old:
        if len(old.namelist()) != len(set(old.namelist())):
            raise ValueError("Duplicate source APK members")
        if (sha(old.read("classes2.dex")) != SOURCE_DEX_SHA or
                sha(old.read(LUA)) != OLD_LUA_SHA or
                sha(old.read(INDEX)) != INDEX_SHA):
            raise ValueError("Reviewed v108 payload changed")
        for name, item in listed.items():
            if name != LUA and (name not in old.namelist() or
                    sha(old.read(name)) != item["sha256"]):
                raise ValueError("APK missing a release 43 resource: " + name)
        index = index_helper.patch_index(old.read(INDEX), {LUA: lua})
        if sha(index) != NEW_INDEX_SHA:
            raise ValueError("Integrated asset index changed unexpectedly")
        original_dex = old.read("classes2.dex")
        apk_manifest = patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=20043108, new_code=20043109,
            old_name="2.0.1.20043108", new_name="2.0.1.20043109")
    dex = compile_integrated_dex(original_dex)
    return {LUA: lua, INDEX: index, "classes2.dex": dex,
            "AndroidManifest.xml": apk_manifest}


def build() -> None:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v109 output or temporary build directory already exists")
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
                     "assets/offline_responses.json", "classes.dex",
                     "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab",
                     "assets/assetbundle/scene/loginfromal.ab"):
            if old.read(name) != new.read(name):
                raise ValueError("Protected client member changed: " + name)
    shutil.copyfile(signed, OUTPUT)
    report = {"source": str(SOURCE), "sourceSha256": SOURCE_SHA,
              "result": str(OUTPUT), "resultSha256": file_sha(OUTPUT),
              "androidVersionCode": 20043109,
              "signedReleaseSequenceEmbedded": 43,
              "changedPayload": sorted(changes),
              "unchangedPayloadMembersChecked": len(old_payload) - len(changes),
              "signingCertificateSha256": match.group(1),
              "onlineApiAndUpdateOriginPreserved": True,
              "localModeMirrorSyncAdded": True,
              "physicalDeviceValidated": False}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Build report UTF-8 round trip failed")
    print("SIGNED_INTEGRATED_LOCAL_V109_OK", report["resultSha256"], flush=True)


if __name__ == "__main__":
    build()
