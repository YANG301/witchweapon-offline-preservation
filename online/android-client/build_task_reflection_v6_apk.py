"""Build separate signed v6 APKs with the corrected original task-row refresh.

The sources are the reviewed password-copy v5 production candidate and local
staging APK. This builder changes only TaskItemPatch.lua's Unity bundle and its
bundle-index entry. It does not install an APK or touch a running server.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import ssl
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import patch_task_row_tolua_arity as task_patch


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
INDEX = "assets/m.assets_list.txt"
EXPECTED_INDEX_SHA256 = "bc76e60b15ea52f892bf8ab74248a3687c3f4a61ce8c0282a55f981e192f3659"
CERT_PEM = Path(r"D:\Project\魔女兵器在线版\测试服\HTTPS代理\cert-v2.pem")
EXPECTED_CERT_DER_SHA256 = "d0a0838496895271ff4e7d3c278d9a872bbccfad665e55b1f4278de79c8c7b13"
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
DEX = "classes2.dex"
ENDPOINT = "assets/online_endpoint.txt"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-password-copy-v5-test.apk",
        "sha256": "0ba4a2dd3561b04763dd39261946f846dae3c27fdc7ab241c6b4df19a89675d0",
        "dexSha256": "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9",
        "endpoint": "https://212.192.15.11:18443",
        "result": BUILD / "witchweapon-online-task-reflection-v6-test.apk",
        "report": BUILD / "每日任务反射修复候选包验收-v6.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-password-copy-v5.apk",
        "sha256": "6842c967d65389218d11026fa555ffb054ac206921dc061ea4447ce66cfdf80a",
        "dexSha256": "024ac5e3c3bebed9e2a0b2eb5258696daef7a2c5811bddf8c080f7058f4e3a56",
        "endpoint": "https://127.0.0.1:19443",
        "result": BUILD / "witchweapon-online-local-staging-task-reflection-v6.apk",
        "report": BUILD / "本地测试服每日任务反射修复验收-v6.json",
    },
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hashed.update(block)
    return hashed.hexdigest()


def local_cert_base64() -> bytes:
    pem = CERT_PEM.read_text(encoding="ascii")
    if pem.count("-----BEGIN CERTIFICATE-----") != 1:
        raise ValueError("Expected exactly one local test certificate")
    der = ssl.PEM_cert_to_DER_cert(pem)
    if digest(der) != EXPECTED_CERT_DER_SHA256:
        raise ValueError("Local test certificate fingerprint changed")
    return base64.b64encode(der)


def prepare(kind: str, pinned_cert: bytes) -> tuple[dict[str, bytes], dict[str, str]]:
    entry = SOURCE[kind]
    source = entry["apk"]
    if sha256_file(source) != entry["sha256"]:
        raise ValueError("Reviewed password-copy v5 APK changed: " + kind)
    with zipfile.ZipFile(source) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        endpoint = apk.read(ENDPOINT)
        if endpoint != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected endpoint: " + kind)
        dex = apk.read(DEX)
        if digest(dex) != entry["dexSha256"]:
            raise ValueError("Unexpected client network code: " + kind)
        if kind == "staging" and pinned_cert not in dex:
            raise ValueError("Local staging certificate pin missing")
        index = apk.read(INDEX)
        if digest(index) != EXPECTED_INDEX_SHA256:
            raise ValueError("Unreviewed Unity bundle index")
        raw_bundle = apk.read(task_patch.MEMBER)
    patched_bundle = task_patch.patch_bundle(raw_bundle)
    patched_index = patch_index(index, {"/lua/lua_projx_patch.ab": patched_bundle})
    replacements = {task_patch.MEMBER: patched_bundle, INDEX: patched_index}
    detail = {
        "sourceApkSha256": entry["sha256"],
        "sourceEndpoint": entry["endpoint"],
        "networkDexSha256": entry["dexSha256"],
        "luaBundleSha256": digest(patched_bundle),
        "luaTextAssetSha256": digest(task_patch.TASK_SOURCE.read_bytes()),
        "bundleIndexSha256": digest(patched_index),
        "changedUnityTextAsset": "TaskItemPatch.lua",
    }
    if kind == "staging":
        detail["pinnedCertificateDerSha256"] = EXPECTED_CERT_DER_SHA256
    return replacements, detail


def build_one(kind: str, replacements: dict[str, bytes], detail: dict[str, str]) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-task-reflection-v6-" + kind)
    if temp.exists():
        raise ValueError("Stale task-reflection build temp: " + str(temp))
    try:
        signer.SOURCE = entry["apk"]
        signer.SOURCE_SHA256 = entry["sha256"]
        signer.TEMP = temp
        report = signer.build(replacements, entry["result"], entry["report"])
        verify_cmd = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                      "verify", "--print-certs"]
        source_cert = cert_digest(signer.run([*verify_cmd, entry["apk"]], signer.signer_env()))
        result_cert = cert_digest(signer.run([*verify_cmd, entry["result"]], signer.signer_env()))
        if source_cert != EXPECTED_SIGNER_SHA256 or result_cert != source_cert:
            raise ValueError("APK signer certificate changed")
        with zipfile.ZipFile(entry["apk"]) as old, zipfile.ZipFile(entry["result"]) as new:
            for member in ("AndroidManifest.xml", "classes.dex", DEX, ENDPOINT,
                           "assets/assetbundle/config/clientexel/dictionarystatic.ab",
                           "assets/assetbundle/scene/loginfromal.ab"):
                if old.read(member) != new.read(member):
                    raise ValueError("Unrelated client member changed: " + member)
            if new.read(task_patch.MEMBER) != replacements[task_patch.MEMBER]:
                raise ValueError("Signed Lua bundle differs from prepared patch")
            if new.read(INDEX) != replacements[INDEX]:
                raise ValueError("Signed Unity bundle index differs")
        report.update(detail)
        report["signerCertificateSha256"] = result_cert
        report["runtimeValidated"] = False
        for stale in ("originalUnityTextAssetSha256", "preservesV4TaskItemPatch",
                      "nativeRefreshClass"):
            report.pop(stale, None)
        entry["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        sidecar = Path(str(entry["result"]) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(entry["result"]) != report["testApk"]["sha256"]:
            raise ValueError("Final signed APK differs from verification record")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-task-reflection-v6-" + kind:
                raise ValueError("Unsafe task-reflection temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign both v6 APKs")
    args = parser.parse_args()
    pinned_cert = local_cert_base64()
    prepared = {kind: prepare(kind, pinned_cert) for kind in SOURCE}
    for member in (task_patch.MEMBER, INDEX):
        if prepared["candidate"][0][member] != prepared["staging"][0][member]:
            raise ValueError("Production/test task Lua payload diverged: " + member)
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_TASK_REFLECTION_V6_READY", report["testApk"]["sha256"])
    else:
        print("TASK_REFLECTION_V6_STATIC_OK", json.dumps({
            "changedMembers": sorted(prepared["candidate"][0]),
            "luaBundleSha256": prepared["candidate"][1]["luaBundleSha256"],
            "bundleIndexSha256": prepared["candidate"][1]["bundleIndexSha256"],
        }))


if __name__ == "__main__":
    main()
