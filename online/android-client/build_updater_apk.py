"""Build signed in-place upgrade APKs with a verified AssetBundle updater.

production: preserve the public v11 Android bridge, integrate reviewed v21
Unity assets, and use the independent public update origin.
staging-probe: retain local v20 assets so an isolated update can install the
v21 Lua bundle. This APK must never be distributed to players.

The build is deliberately source/hash pinned. It never edits the source APK,
the live services, or installed Android applications.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import ssl
import struct
import zipfile
from urllib.parse import urlsplit

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_original_ui_lottery_touch_probe_apk as touch
import build_priced_draw_apk as draw
import patch_update_manifest as manifest_patch


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
DESKTOP = Path(r"D:\Project\魔女兵器在线版\更新版")
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
BASELINE = HERE / "baseline_sources"
PUBLIC_KEY = Path(r"D:\Project\魔女兵器在线版\.local\热更新密钥\签名公钥.der")
TEST_CERT = Path(r"D:\Project\魔女兵器在线版\测试服\HTTPS代理\cert-v2.pem")
PUBLIC_KEY_SHA256 = "8dccb4392be5ecf93317da2dd6e5cb5bfcbd6e1053b3c63ed45e9bda2f4f0bb2"
TEST_CERT_DER_SHA256 = "d0a0838496895271ff4e7d3c278d9a872bbccfad665e55b1f4278de79c8c7b13"
SIGNER_CERT_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
BASELINE_APP_SHA256 = "0da03b2780bf9a915a078b5f0f9908c19f8bd6ae0eaf20b1f903b3f9643a4fb8"
BASELINE_ENDPOINT_SHA256 = "5c0adf8bd9194103a5462bfe6770ee5bf2400043b8cc88b0d3c83c909898740a"
SOURCE_DEX_SHA256 = "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9"
UPDATER_SOURCE_SHA256 = {
    "AssetUpdateManager.java": "7cbbf68d5f5f6fcf07ac276a9e81934f63a16d0ec4909d59ae8ddebfe7cd1a05",
    "UpdateBootstrapActivity.java": "31fcd3430111788385b897169b9a1099448038f04e72e105cce8bf6f57ed6f51",
    "OfflineApplication.java": "5803d1f8f8fe6f00e60b3f91b2e49559ea4bb1182f0eb024871c5da2363fa9c7",
    "OnlineEndpoint.java": "9d8eb2b52f6b60051d1f64445f4acc14c2609b0c65026b5978a9819c9f14cc27",
}

PROD_V11 = BUILD / "witchweapon-online-activity-long-preflight-v11-test.apk"
PROD_V11_SHA256 = "71c80b6394a0abbf298967ff2a16058c8a1bf3008416046748f9583e091977b9"
STAGE_V11 = BUILD / "witchweapon-online-local-staging-activity-long-preflight-v11.apk"
STAGE_V11_SHA256 = "82da77fbdc13c47ecab700f4e6d42fc58bc7f11e8bc6a68702c6bdd587047b83"
STAGE_V20 = BUILD / "witchweapon-online-local-staging-shop-runtime-v20.apk"
STAGE_V20_SHA256 = "e8bf22264944c3bf487b0ca3e680aaa9e8313498b9232b262b661e11327eb825"
STAGE_V21 = BUILD / "witchweapon-online-local-staging-shop-runtime-v21.apk"
STAGE_V21_SHA256 = "d5716d7f7ca5902710f7809d64121ce45de18632edf521ccc240aa929a237625"

CHANGED_BUNDLES = {
    "assets/assetbundle/assets/resources/ui/prefab/vip/vippanel.ab",
    "assets/assetbundle/config/clientexel/dictionary.ab",
    "assets/assetbundle/config/clientexel/goods.ab",
    "assets/assetbundle/config/clientexel/shop.ab",
    "assets/assetbundle/config/clientexel/shopbigset.ab",
    "assets/assetbundle/config/clientexel/shopset.ab",
    "assets/assetbundle/config/clientexel/shopstructure.ab",
    "assets/assetbundle/lua/lua.ab",
    "assets/assetbundle/lua/lua_projx_patch.ab",
}
CHANGED_METADATA = {"assets/m.assets_list.txt", "assets/m.version", "assets/offline_responses.json"}
ASSET_DELTA = CHANGED_BUNDLES | CHANGED_METADATA
ADDED_PUBLIC = {"assets/update_endpoint.txt", "assets/update_public_key.der"}
ADDED_TEST = ADDED_PUBLIC | {"assets/update_test_cert.der"}
REPLACED_CORE = {"AndroidManifest.xml", "classes2.dex"}
PROD_API = b"https://212.192.15.11:18443\n"
STAGE_API = b"https://127.0.0.1:19443\n"
VERSION_21 = b"2.0.1.20043082\r\n"
VERSION_20 = b"2.0.1.20043081\r\n"
VERSION_ROUTES = ("/getversion", "/m.version", "//getversion")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require_file(path: Path, digest: str) -> None:
    if not path.is_file() or sha256_file(path) != digest:
        raise ValueError(f"Missing or changed pinned input: {path}")


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Java source anchor missing or ambiguous: " + old[:80])
    return source.replace(old, new, 1)


def normalize_origin(value: str) -> str:
    if value != value.strip() or any(c in value for c in "\r\n?#@\\"):
        raise ValueError("Update endpoint must be one HTTPS origin")
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise ValueError("Update endpoint must be one HTTPS origin")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname):
        raise ValueError("Unsupported update endpoint hostname")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid update endpoint port")
    return "https://" + parsed.netloc.lower()


def _members(apk: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    infos = apk.infolist()
    if len(infos) != len({entry.filename for entry in infos}):
        raise ValueError("Duplicate APK ZIP member")
    return {entry.filename: entry for entry in infos}


def _payload(infos: dict[str, zipfile.ZipInfo]) -> dict[str, zipfile.ZipInfo]:
    return {name: info for name, info in infos.items()
            if not signer.SIGNATURE.fullmatch(name)}


def _different(left: dict[str, zipfile.ZipInfo], right: dict[str, zipfile.ZipInfo]) -> set[str]:
    return {name for name in left.keys() | right.keys()
            if name not in left or name not in right
            or (left[name].CRC, left[name].file_size) != (right[name].CRC, right[name].file_size)}


def verify_asset_index(apk: zipfile.ZipFile) -> None:
    lines = apk.read("assets/m.assets_list.txt").decode("utf-8").splitlines()
    for member in sorted(CHANGED_BUNDLES):
        raw = apk.read(member)
        name = "/" + member.removeprefix("assets/assetbundle/")
        expected = hashlib.md5(raw).hexdigest() + "=" + name + ":" + str(len(raw))
        if lines.count(expected) != 1:
            raise ValueError("Bundle MD5/length missing from asset index: " + member)


def verify_version(apk: zipfile.ZipFile, expected: bytes) -> None:
    if apk.read("assets/m.version") != expected:
        raise ValueError("Embedded Unity asset version differs")
    fixtures = json.loads(apk.read("assets/offline_responses.json"))
    for route in VERSION_ROUTES:
        if fixtures[route]["body"] != expected.decode("ascii"):
            raise ValueError("Legacy version route is out of sync: " + route)


def inspect_inputs(mode: str) -> tuple[Path, dict[str, bytes], dict[str, object]]:
    for path, digest in ((PROD_V11, PROD_V11_SHA256), (STAGE_V11, STAGE_V11_SHA256),
                         (STAGE_V21, STAGE_V21_SHA256)):
        require_file(path, digest)
    if mode == "staging-probe":
        require_file(STAGE_V20, STAGE_V20_SHA256)
    require_file(PUBLIC_KEY, PUBLIC_KEY_SHA256)
    for name, digest in UPDATER_SOURCE_SHA256.items():
        require_file(HERE / "src/com/codex/witchweapon" / name, digest)
    source_path = PROD_V11 if mode == "production" else STAGE_V20
    with (zipfile.ZipFile(PROD_V11) as public_v11,
          zipfile.ZipFile(STAGE_V11) as local_v11,
          zipfile.ZipFile(STAGE_V21) as local_v21,
          zipfile.ZipFile(source_path) as source):
        public_members = _payload(_members(public_v11))
        local_members = _payload(_members(local_v11))
        v21_members = _payload(_members(local_v21))
        source_members = _payload(_members(source))
        if set(public_members) != set(local_members) or set(local_members) != set(v21_members):
            raise ValueError("Reviewed APK ZIP member inventory changed")
        if _different(public_members, local_members) != {"classes2.dex", "assets/online_endpoint.txt"}:
            raise ValueError("Public and local v11 have unexpected differences")
        if _different(local_members, v21_members) != ASSET_DELTA:
            raise ValueError("Local v21 resource delta is no longer the reviewed set")
        if source.read("assets/online_endpoint.txt") != (PROD_API if mode == "production" else STAGE_API):
            raise ValueError("Source APK points to an unexpected gameplay API")
        if sha256_bytes(public_v11.read("classes2.dex")) != SOURCE_DEX_SHA256:
            raise ValueError("Public v11 Android bridge changed")
        verify_asset_index(local_v21)
        verify_version(local_v21, VERSION_21)
        replacements: dict[str, bytes] = {
            "AndroidManifest.xml": manifest_patch.patch(source.read("AndroidManifest.xml")),
            "assets/update_public_key.der": PUBLIC_KEY.read_bytes(),
        }
        if mode == "production":
            if source.read("assets/m.version") != b"2.0.1.20043076\r\n":
                raise ValueError("Public v11 Unity version changed")
            verify_version(public_v11, b"2.0.1.20043076\r\n")
            replacements.update({name: local_v21.read(name) for name in ASSET_DELTA})
            target_version = VERSION_21.decode("ascii").strip()
        else:
            verify_version(source, VERSION_20)
            pem = TEST_CERT.read_text(encoding="ascii")
            if pem.count("-----BEGIN CERTIFICATE-----") != 1:
                raise ValueError("Unexpected local TLS certificate PEM")
            cert_der = ssl.PEM_cert_to_DER_cert(pem)
            if sha256_bytes(cert_der) != TEST_CERT_DER_SHA256:
                raise ValueError("Local TLS test certificate changed")
            replacements["assets/update_test_cert.der"] = cert_der
            target_version = VERSION_20.decode("ascii").strip()
        old_dex = source.read("classes2.dex")
        old_classes = set(adapter.dex_classes(old_dex))
        return source_path, replacements, {
            "mode": mode,
            "sourceSha256": PROD_V11_SHA256 if mode == "production" else STAGE_V20_SHA256,
            "sourceDexSha256": sha256_bytes(old_dex),
            "sourceDexClasses": old_classes,
            "embeddedAssetVersion": target_version,
            "resourceDeltaMembers": sorted(ASSET_DELTA if mode == "production" else set()),
        }


def inherited_application(source: str) -> str:
    """Reapply the two Android hooks already compiled into public v11."""
    if "LotteryTouchTrace.attach" in source or "DrawRequestIdempotency.append" in source:
        raise ValueError("Inherited Android hooks were already added to Java source")
    source = replace_once(source, touch.ANCHOR, touch.INJECTION)
    source = replace_once(
        source,
        "                        byte[] forwardedBody = appendBattleEnergy(path, contentType, body);",
        "                        byte[] forwardedBody = DrawRequestIdempotency.append(path, contentType, "
        "appendBattleEnergy(path, contentType, body));",
    )
    source = replace_once(
        source,
        '                    if (status >= 200 && status < 300 && "POST".equals(method)) refreshMirrorAsync();',
        '                    if (status >= 200 && status < 300 && "POST".equals(method)) {\n'
        '                        DrawRequestIdempotency.confirm(path, body);\n'
        '                        refreshMirrorAsync();\n'
        '                    }',
    )
    return source


def staging_endpoint(source: str) -> str:
    """Trust only the bundled loopback cert for the isolated probe's two ports."""
    source = replace_once(
        source,
        '            if ("update_endpoint.txt".equals(assetName))\n'
        '                testFactory = optionalUpdateTestFactory(context);',
        '            if ("update_endpoint.txt".equals(assetName)\n'
        '                    || "online_endpoint.txt".equals(assetName))\n'
        '                testFactory = optionalUpdateTestFactory(context);',
    )
    source = replace_once(
        source,
        '            SSLSocket tls = (SSLSocket) ((SSLSocketFactory) SSLSocketFactory.getDefault())\n'
        '                    .createSocket(tcp, host, port, true);',
        '            SSLSocketFactory sockets = updateTestFactory == null\n'
        '                    ? (SSLSocketFactory) SSLSocketFactory.getDefault() : updateTestFactory;\n'
        '            SSLSocket tls = (SSLSocket) sockets.createSocket(tcp, host, port, true);',
    )
    return source


def _compile_sources(temp: Path, *, baseline: bool, mode: str) -> list[Path]:
    source_root = HERE / "src/com/codex/witchweapon"
    old_app = BASELINE / "OfflineApplication.java"
    old_endpoint = BASELINE / "OnlineEndpoint.java"
    require_file(old_app, BASELINE_APP_SHA256)
    require_file(old_endpoint, BASELINE_ENDPOINT_SHA256)
    app_source = (old_app if baseline else source_root / "OfflineApplication.java").read_text(encoding="utf-8")
    endpoint_source = (old_endpoint if baseline else source_root / "OnlineEndpoint.java").read_text(encoding="utf-8")
    if not baseline and mode == "staging-probe":
        endpoint_source = staging_endpoint(endpoint_source)
    copied = temp / ("baseline-java" if baseline else "updater-java") / "com/codex/witchweapon"
    copied.mkdir(parents=True, exist_ok=False)
    app_path = copied / "OfflineApplication.java"
    endpoint_path = copied / "OnlineEndpoint.java"
    app_path.write_text(inherited_application(app_source), encoding="utf-8")
    endpoint_path.write_text(endpoint_source, encoding="utf-8")
    # Keep the exact source order used by build_bugfix_v4_apk.py so D8 can
    # reproduce its original public DEX byte-for-byte before we add an updater.
    sources = [app_path, touch.TRACE]
    sources.extend(endpoint_path if name == "OnlineEndpoint.java" else source_root / name
                   for name in adapter.ADAPTER if name != "OfflineApplication.java")
    sources.extend(adapter.AUTHOR / name for name in adapter.AUTHOR_HELPERS)
    sources.append(draw.BRIDGE)
    if not baseline:
        sources.extend((source_root / "AssetUpdateManager.java",
                        source_root / "UpdateBootstrapActivity.java"))
    if len(sources) != len(set(sources)) or not all(path.is_file() for path in sources):
        raise ValueError("Android Java source set is missing or duplicated")
    return sources


def compile_and_prove(source_apk: Path, mode: str, temp: Path) -> tuple[bytes, list[str]]:
    with zipfile.ZipFile(PROD_V11) as apk:
        public_dex = apk.read("classes2.dex")
    old_classes = set(adapter.dex_classes(public_dex))
    adapter.TEMP = temp
    baseline_sources = _compile_sources(temp, baseline=True, mode=mode)
    rebuilt, rebuilt_classes = adapter.compile_dex(baseline_sources, old_classes)
    if (sha256_bytes(rebuilt) != SOURCE_DEX_SHA256
            or rebuilt != public_dex or set(rebuilt_classes) != old_classes):
        raise ValueError("Current pinned Java inputs do not reproduce public v11 DEX")

    updated_sources = _compile_sources(temp, baseline=False, mode=mode)
    updated, updated_classes = adapter.compile_dex(updated_sources, old_classes)
    new_classes = set(updated_classes) - old_classes
    if not old_classes.issubset(updated_classes):
        raise ValueError("Updater compilation removed a legacy Android class")
    required = {
        "Lcom/codex/witchweapon/AssetUpdateManager;",
        "Lcom/codex/witchweapon/UpdateBootstrapActivity;",
    }
    if not required.issubset(updated_classes):
        raise ValueError("Updater DEX lacks required bootstrap classes")
    allowed_prefixes = (
        "Lcom/codex/witchweapon/AssetUpdateManager",
        "Lcom/codex/witchweapon/UpdateBootstrapActivity",
        "Lcom/codex/witchweapon/OfflineApplication$",
        "Lcom/codex/witchweapon/OnlineEndpoint$",
    )
    if any(not name.startswith(allowed_prefixes) for name in new_classes):
        raise ValueError("Unexpected new Android DEX class: " + repr(sorted(new_classes)))
    if source_apk == PROD_V11 and updated == public_dex:
        raise ValueError("Updater DEX is unchanged")
    return updated, sorted(new_classes)


def _entry_sha(apk: zipfile.ZipFile, name: str) -> str:
    with apk.open(name) as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_signed(source_path: Path, result: Path,
                  replacements: dict[str, bytes]) -> dict[str, object]:
    changed: list[str] = []
    unchanged = 0
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(result) as signed:
        source_entries = _payload(_members(source))
        result_entries = _payload(_members(signed))
        added = set(replacements) - set(source_entries)
        if set(result_entries) != set(source_entries) | added:
            raise ValueError("Signed APK ZIP member inventory changed")
        for name in sorted(result_entries):
            actual = _entry_sha(signed, name)
            if name in replacements:
                if actual != sha256_bytes(replacements[name]):
                    raise ValueError("Signed replacement payload differs: " + name)
                changed.append(name)
            else:
                if actual != _entry_sha(source, name):
                    raise ValueError("Unreviewed signed payload changed: " + name)
                unchanged += 1
        if signed.read("assets/online_endpoint.txt") != source.read("assets/online_endpoint.txt"):
            raise ValueError("Gameplay API origin changed")
        if "assets/update_test_cert.der" in result_entries and source_path == PROD_V11:
            raise ValueError("Test TLS trust anchor leaked into public APK")
        version = VERSION_21 if source_path == PROD_V11 else VERSION_20
        verify_version(signed, version)
        if source_path == PROD_V11:
            verify_asset_index(signed)
        compiled = set(adapter.dex_classes(signed.read("classes2.dex")))
        old = set(adapter.dex_classes(source.read("classes2.dex")))
        if not old.issubset(compiled):
            raise ValueError("Signed DEX lost a legacy class")
    if set(changed) != set(replacements):
        raise ValueError("Some prepared replacement was not written")
    return {"changedPayloadMembers": changed,
            "changedPayloadSha256": {name: sha256_bytes(raw)
                                     for name, raw in sorted(replacements.items())},
            "unchangedPayloadMembersSha256Checked": unchanged}


def build_apk(source_path: Path, mode: str, temp: Path,
              replacements: dict[str, bytes], details: dict[str, object],
              output: Path, report: Path) -> dict[str, object]:
    if output.exists() or report.exists() or temp.exists():
        raise ValueError("Existing output or build directory requires explicit review")
    if output.parent.resolve() != DESKTOP.resolve():
        raise ValueError("Unexpected final APK directory")
    if temp.resolve().parent != TEMP_PARENT.resolve():
        raise ValueError("Unexpected portable Android temporary directory")
    if shutil.disk_usage(TEMP_PARENT).free < 4 * source_path.stat().st_size:
        raise OSError("Portable Android temp volume needs at least four APK sizes free")
    if shutil.disk_usage(DESKTOP).free < source_path.stat().st_size + 64 * 1024 * 1024:
        raise OSError("Desktop volume lacks space for the final APK")
    temp.mkdir(parents=True)
    updated_dex, new_classes = compile_and_prove(source_path, mode, temp)
    replacements["classes2.dex"] = updated_dex
    details["addedDexClasses"] = new_classes
    details["candidateDexSha256"] = sha256_bytes(updated_dex)
    unsigned, aligned, candidate = (temp / name for name in
                                    ("unsigned.apk", "aligned.apk", "signed.apk"))
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(unsigned, "x", allowZip64=False) as target:
        source_members = _members(source)
        additions = set(replacements) - set(source_members)
        if additions != (ADDED_PUBLIC if mode == "production" else ADDED_TEST):
            raise ValueError("Unexpected set of added APK assets")
        for info in source.infolist():
            if signer.SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename in replacements:
                target.writestr(copy.copy(info), replacements[info.filename])
            else:
                adapter.copy_compressed_entry(source, target, info)
        for name in sorted(additions):
            target.writestr(name, replacements[name], compress_type=zipfile.ZIP_DEFLATED)
    signer.TEMP = temp
    signer.run([signer.TOOLS / "zipalign.exe", "-p", "4", unsigned, aligned])
    signature_cmd = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar"]
    signer.run([*signature_cmd, "sign", "--ks", signer.KEY, "--ks-key-alias", "local",
                "--ks-pass", "env:WITCH_TEST_KEYPASS", "--key-pass", "env:WITCH_TEST_KEYPASS",
                "--v4-signing-enabled", "false", "--out", candidate, aligned], signer.signer_env())
    signature = signer.run([*signature_cmd, "verify", "--verbose", "--print-certs", candidate],
                           signer.signer_env())
    match = re.search(r"Signer #1 certificate SHA-256 digest:\s*([0-9a-f]{64})", signature)
    if not match or match.group(1) != SIGNER_CERT_SHA256:
        raise ValueError("Upgrade APK signing certificate differs from installed v3")
    signer.run([signer.TOOLS / "zipalign.exe", "-c", "-p", "4", candidate])
    checks = verify_signed(source_path, candidate, replacements)
    shutil.copyfile(candidate, output)
    digest = sha256_file(output)
    if digest != sha256_file(candidate):
        raise ValueError("Final desktop APK differs from verified candidate")
    result = {
        "status": "signed_static_validation_only",
        "mode": mode,
        "sourceApk": {"path": str(source_path), "sha256": details["sourceSha256"]},
        "resultApk": {"path": str(output), "sha256": digest, "bytes": output.stat().st_size},
        "androidVersionCode": manifest_patch.NEW_VERSION_CODE,
        "androidVersionName": manifest_patch.VERSION_NAME,
        "embeddedAssetVersion": details["embeddedAssetVersion"],
        "gameplayApi": "https://212.192.15.11:18443" if mode == "production" else "https://127.0.0.1:19443",
        "updateOrigin": replacements["assets/update_endpoint.txt"].decode("ascii").strip(),
        "publicKeySha256": PUBLIC_KEY_SHA256,
        "signerCertificateSha256": SIGNER_CERT_SHA256,
        "sourceDexSha256": details["sourceDexSha256"],
        "reproducedPublicV11DexSha256": SOURCE_DEX_SHA256,
        "candidateDexSha256": details["candidateDexSha256"],
        "updaterJavaSourceSha256": UPDATER_SOURCE_SHA256,
        "addedDexClasses": details["addedDexClasses"],
        "resourceDeltaMembers": details["resourceDeltaMembers"],
        "runtimeValidated": False,
        **checks,
    }
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(report.read_text(encoding="utf-8")) != result:
        raise ValueError("UTF-8 build report readback failed")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("production", "staging-probe"), required=True)
    parser.add_argument("--build", action="store_true", help="Compile, sign and verify an APK")
    args = parser.parse_args()
    mode = args.mode
    source, replacements, details = inspect_inputs(mode)
    origin = ("https://212.192.15.11:18445" if mode == "production"
              else "https://127.0.0.1:19444")
    replacements["assets/update_endpoint.txt"] = (normalize_origin(origin) + "\n").encode("ascii")
    if not args.build:
        print("UPDATER_APK_STATIC_OK", mode, json.dumps({
            "source": str(source), "embeddedAssetVersion": details["embeddedAssetVersion"],
            "assetDelta": details["resourceDeltaMembers"], "updateOrigin": origin,
            "preparedPayloadMembers": sorted(replacements)}, ensure_ascii=False))
        return
    DESKTOP.mkdir(parents=True, exist_ok=True)
    name = ("魔女兵器-新丰洲-可更新版" if mode == "production"
            else "魔女兵器-热更新隔离验证")
    output = DESKTOP / (name + ".apk")
    report = DESKTOP / (name + "-构建验收.json")
    temp = TEMP_PARENT / ("witch-online-updater-production-r3" if mode == "production"
                          else "witch-online-updater-staging-probe")
    result = build_apk(source, mode, temp, replacements, details, output, report)
    print("UPDATER_APK_SIGNED", mode, result["resultApk"]["sha256"], str(output))


if __name__ == "__main__":
    main()
