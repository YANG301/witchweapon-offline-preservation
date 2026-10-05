"""Build v111 from the reviewed v110 APK and signed preserved-stage release.

The signed snapshot is folded into the APK, including new resource members and
the Unity asset index. Publishing, installing and device tests are separate.
The only native change is the already deployed quantity-77 batch purchase fix.
Temporary APKs are retained until the caller validates and explicitly cleans
their three literal paths; no recursive deletion is performed by this builder.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
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
OUTPUT = Path(r"D:\Project\魔女兵器在线版\构建\原始关卡候选\魔女兵器-在线本地双区服-v111-测试.apk")
REPORT = OUTPUT.with_suffix(".json")
TEMP = Path(r"D:\Environment\Android\temp\witch-preserved-v111")
ROOT = ONLINE.parent / "热更新测试" / "主线热更候选"
DEFAULT_RELEASE = "121-54bd72d245c2a929e880632a61c53a41075d2cf1b38d51a73cf80986eea41da2"
SOURCE_VERSION_CODE = 20043110
TARGET_VERSION_CODE = 20043111
SETTLEMENT = "assets/assetbundle/assets/resources/ui/prefab/settlement.ab"
LUA = "assets/assetbundle/lua/lua.ab"
PRESERVED_MANIFEST = "assetbundle/config/preserved_stage_manifest.ab"
INDEX = "assets/m.assets_list.txt"
NATIVE = "lib/arm64-v8a/libil2cpp.so"
SIGNATURE = re.compile(r"META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))", re.I)
SOURCE_SETTLEMENT_SHA = "d92a20aee6f8635eb4c47f9072699e0cf68712a6dec7374201a5cd9b9b8ca147"
PATCHED_SETTLEMENT_SHA = "2481bcb680cc40a9027aaf1f2fa4a486ff2d52e6a56c1959b35390fb5e041669"
CACHE_WARNING = (
    "assets/m.version 保持 2.0.1.20043082 以兼容现有更新协议。"
    "外部已激活的旧 119 缓存仍可能覆盖内置 121 资源；"
    "正式更新 121 应先发布，再安装并确认资源版本。"
)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def existing_ancestor(path: Path) -> Path:
    while not path.exists():
        path = path.parent
    return path


def compressed_sha(archive: zipfile.ZipFile, entry: zipfile.ZipInfo) -> str:
    """Check copied payload bytes directly, without decompressing 1.7 GB."""
    stream = archive.fp
    stream.seek(entry.header_offset)
    header = stream.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise ValueError("Invalid ZIP local header: " + entry.filename)
    name_size, extra_size = struct.unpack_from("<HH", header, 26)
    stream.seek(name_size + extra_size, 1)
    remaining = entry.compress_size
    digest = hashlib.sha256()
    while remaining:
        part = stream.read(min(remaining, 1024 * 1024))
        if not part:
            raise ValueError("Truncated ZIP payload: " + entry.filename)
        digest.update(part)
        remaining -= len(part)
    return digest.hexdigest()


def verify_index(raw: bytes, resources: dict[str, bytes]) -> None:
    rows = raw.decode("utf-8").splitlines()
    paths = [row.split("=", 1)[1].rsplit(":", 1)[0] for row in rows]
    if len(paths) != len(set(paths)):
        raise ValueError("Duplicate resource index paths")
    for name, payload in resources.items():
        logical = "/" + name.removeprefix(index_helper.PREFIX)
        expected = f"{hashlib.md5(payload).hexdigest()}={logical}:{len(payload)}"
        if rows.count(expected) != 1:
            raise ValueError("Missing or incorrect resource index: " + logical)


def build(release_name: str = DEFAULT_RELEASE, check_only: bool = False,
          extra_members: dict[str, bytes] | None = None,
          extra_fixture_routes: frozenset[str] = frozenset({'/combat/role/info'}),
          helper_dex: bytes | None = None) -> dict:
    if OUTPUT.exists() or REPORT.exists() or TEMP.exists():
        raise FileExistsError("v111 output, report or temporary build already exists")
    if file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError("Reviewed v110 source APK changed")
    if shutil.disk_usage(existing_ancestor(TEMP.parent)).free < 4 * SOURCE.stat().st_size:
        raise OSError("Android portable build volume needs four APK sizes free")
    if shutil.disk_usage(existing_ancestor(OUTPUT.parent)).free < SOURCE.stat().st_size + 64 * 1024 * 1024:
        raise OSError("Project volume lacks room for the final APK")

    release_dir = ROOT / "releases" / release_name
    manifest_raw = (release_dir / "manifest.json").read_bytes()
    if sha(manifest_raw) != release_name.split("-", 1)[1]:
        raise ValueError("Selected release manifest is corrupt")
    manifest = json.loads(manifest_raw)
    if (manifest["targetAppVersion"] != "2.0.1.20043082"
            or manifest["releaseSequence"] != int(release_name.split("-", 1)[0])
            or manifest["packageId"] != "com.codex.witchweapon.online.originalui.test"):
        raise ValueError("Selected release is incompatible with reviewed v110")
    listed = {item["path"]: item for item in manifest["assets"]}
    if len(listed) != len(manifest["assets"]):
        raise ValueError("Duplicate signed resource path")
    if release_name == DEFAULT_RELEASE and len(listed) != 116:
        raise ValueError("Reviewed release 121 must contain all 116 assets")
    if PRESERVED_MANIFEST not in listed or listed.get(SETTLEMENT.removeprefix("assets/"), {}).get("sha256") != PATCHED_SETTLEMENT_SHA:
        raise ValueError("Release lacks original stage manifest or retained settlement fix")
    resources: dict[str, bytes] = {}
    for logical, resource in listed.items():
        if (not logical.startswith("assetbundle/") or not logical.endswith(".ab")
                or ".." in Path(logical).parts or "\\" in logical):
            raise ValueError("Unsafe signed resource path: " + logical)
        payload = (ROOT / "blobs" / resource["sha256"]).read_bytes()
        if sha(payload) != resource["sha256"] or len(payload) != resource["size"]:
            raise ValueError("Signed resource differs: " + logical)
        resources["assets/" + logical] = payload
    lua_environment = UnityPy.load(resources[LUA])
    init_scripts = [obj.read_typetree()["m_Script"] for obj in lua_environment.objects
                    if obj.type.name == "TextAsset" and obj.read_typetree().get("m_Name") == "init.lua"]
    if (len(init_scripts) != 1 or "ONLINE_SETTLEMENT_EFFECT_ORDER" in init_scripts[0]
            or "WWR_PRESERVED_STAGE_MANIFEST_READY" not in init_scripts[0]
            or "bundled-apk" not in init_scripts[0]):
        raise ValueError("Release Lua lacks reviewed APK manifest fallback")

    with zipfile.ZipFile(SOURCE) as old:
        if old.read("assets/m.version").decode("ascii").strip() != manifest["targetAppVersion"]:
            raise ValueError("APK Unity resource version differs from signed release")
        sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        public = serialization.load_der_public_key(old.read("assets/update_public_key.der"))
        public.verify(base64.b64decode((release_dir / "manifest.sig").read_bytes()),
                      manifest_raw, padding.PKCS1v15(), hashes.SHA256())
        if sha(old.read(SETTLEMENT)) != SOURCE_SETTLEMENT_SHA:
            raise ValueError("v110 settlement bundle changed")
        inventory = set(old.namelist())
        if len(inventory) != len(old.infolist()):
            raise ValueError("Duplicate source APK members")
        additions = sorted(set(resources) - inventory)
        replacements = {name: payload for name, payload in resources.items()
                        if name not in inventory or sha(old.read(name)) != sha(payload)}
        index = index_helper.patch_index(old.read(INDEX), resources)
        verify_index(index, resources)
        android_manifest = patch_android_manifest(
            old.read("AndroidManifest.xml"), old_code=SOURCE_VERSION_CODE, new_code=TARGET_VERSION_CODE,
            old_name="2.0.1."+str(SOURCE_VERSION_CODE), new_name="2.0.1."+str(TARGET_VERSION_CODE))
        native_before = old.read(NATIVE)
        native_after = restore_batch_native(native_before)
        extra_members = extra_members or {}
        if (not set(extra_members).issubset({"assets/offline_responses.json"})
                or any(name not in inventory for name in extra_members)):
            raise ValueError("Only the existing reviewed offline fixture may be supplied")
        for name, payload in extra_members.items():
            previous_fixture = json.loads(old.read(name))
            new_fixture = json.loads(payload)
            if (set(previous_fixture) != set(new_fixture)
                    or {p for p in previous_fixture if previous_fixture[p] != new_fixture[p]}
                    != extra_fixture_routes):
                raise ValueError("Offline fixture changes exceed the explicitly reviewed routes")
        changes = {**replacements, **extra_members, INDEX: index, "AndroidManifest.xml": android_manifest}
        if helper_dex is not None:
            old_classes = set(adapter.dex_classes(old.read("classes2.dex")))
            new_classes = set(adapter.dex_classes(helper_dex))
            if new_classes - old_classes != {'Lcom/codex/witchweapon/SignedAssetReuse;'} or old_classes - new_classes:
                raise ValueError("Unexpected embedded updater DEX class changes")
            changes['classes2.dex'] = helper_dex
        if native_after != native_before:
            changes[NATIVE] = native_after
        resource_template = copy.copy(old.getinfo(LUA))
    if check_only:
        result = {"release": release_name, "signedAssetsVerified": len(resources),
                  "addedAssetMembers": len(additions), "changedResources": len(replacements),
                  "previousQuantity77NativeFixIncluded": native_after != native_before}
        print("PRESERVED_APK_INPUTS_VERIFIED", json.dumps(result, ensure_ascii=False), flush=True)
        return result

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
        for name in additions:
            entry = copy.copy(resource_template)
            entry.filename = entry.orig_filename = name
            new.writestr(entry, resources[name])
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
    print("PRESERVED_V111_SIGNED_CHECKING_PAYLOAD", flush=True)

    unchanged_count = 0
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(signed) as new:
        old_files = {entry.filename: entry for entry in old.infolist()
                     if not SIGNATURE.fullmatch(entry.filename)}
        new_files = {entry.filename: entry for entry in new.infolist()
                     if not SIGNATURE.fullmatch(entry.filename)}
        if len(new_files) != len([e for e in new.infolist() if not SIGNATURE.fullmatch(e.filename)]):
            raise ValueError("Duplicate final APK members")
        if set(new_files) != set(old_files) | set(additions):
            raise ValueError("Unexpected APK payload inventory")
        for name, previous in old_files.items():
            current = new_files[name]
            if name in changes:
                if new.read(name) != changes[name]:
                    raise ValueError("Signed APK differs from prepared member: " + name)
            else:
                if ((previous.CRC, previous.file_size, previous.compress_size) !=
                        (current.CRC, current.file_size, current.compress_size)
                        or compressed_sha(old, previous) != compressed_sha(new, current)):
                    raise ValueError("Unrelated APK member changed: " + name)
                unchanged_count += 1
        for logical, resource in listed.items():
            payload = new.read("assets/" + logical)
            if sha(payload) != resource["sha256"] or len(payload) != resource["size"]:
                raise ValueError("Bundled signed snapshot mismatch: " + logical)
        verify_index(new.read(INDEX), resources)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(signed, OUTPUT)
    if file_sha(SOURCE) != SOURCE_SHA:
        raise ValueError("Source APK unexpectedly changed during build")
    report = {
        "source": str(SOURCE), "sourceSha256": SOURCE_SHA,
        "result": str(OUTPUT), "resultSize": OUTPUT.stat().st_size,
        "resultSha256": file_sha(OUTPUT), "androidVersionCode": TARGET_VERSION_CODE,
        "androidVersionName": "2.0.1."+str(TARGET_VERSION_CODE), "unityResourceVersion": "2.0.1.20043082",
        "bundledSignedRelease": release_name, "signedAssetsVerified": len(resources),
        "changedPayload": sorted(changes), "addedAssetMembers": additions,
        "unchangedPayloadMembersCompressedSha256Checked": unchanged_count,
        "signingCertificateSha256": match.group(1),
        "previousQuantity77NativeFix": {
            "included": native_after != native_before, "path": NATIVE,
            "beforeSha256": sha(native_before), "afterSha256": sha(native_after),
            "note": "此前已部署的 quantity 77 批量购买修复，独立于本次关卡恢复。"},
        "externalCacheWarning": CACHE_WARNING,
        "temporaryApkPaths": [str(unsigned), str(aligned), str(signed)],
        "installed": False, "physicalDeviceValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("UTF-8 build report round-trip failed")
    print("SIGNED_PRESERVED_V111_READY", report["resultSha256"],
          report["resultSize"], "assets", len(resources), "added", len(additions), flush=True)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", nargs="?", default=DEFAULT_RELEASE)
    parser.add_argument("--check", action="store_true", help="Verify inputs without creating a large APK")
    options = parser.parse_args()
    build(options.release, options.check)
