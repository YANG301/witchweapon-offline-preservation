"""Build two signed v7 APKs with original mainline sweep parameters.

Sources are the reviewed v6 production candidate and loopback-only test APK.
Only InstanceMobList and its index entry change; no install/deploy occurs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
from patch_simple_campaign import CHAPTER16_IDS, MAINLINE_IDS, _csv_tree
from patch_sweep_bonus import patch_sweep_bonus_bundle, _original_bonus_values


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel\instancemoblist.ab")
ORIGINAL_SHA256 = "e0d3f63b2764db408798ecf09a3ec330937acfd2771c1806c22138793f79bb5c"
MEMBER = "assets/assetbundle/config/clientexel/instancemoblist.ab"
INDEX = "assets/m.assets_list.txt"
EXPECTED_SOURCE_BUNDLE_SHA256 = "293505c6e95ea5d12b50149578b80868774ca36205308421dd3fe3a5adbc5412"
EXPECTED_SOURCE_INDEX_SHA256 = "8ef2af7fd68c48d03cb1a35a8362239d1e37d4643a8eb063cc7ed9faa35d25e4"
EXPECTED_LUA_SHA256 = "24e3df491e43154e0164c6e4e174d89c3936318c891b69950145028aa0535aa3"
EXPECTED_DICTIONARY_SHA256 = "18eec79e84eb14d4d8d2282eb65dccac7eedd6bc2e7699d0a7070b97f62bde1a"
EXPECTED_LOGIN_SHA256 = "10dafba6fe685e317ab55ed956a714bb2a8f2db3b1d89645bf50ae4940cbfd79"
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-task-reflection-v6-test.apk",
        "sha256": "0ddf633d4197c0932a476dc1a4af8f6083d7b776a94b33dfef452468ea97007a",
        "endpoint": "https://212.192.15.11:18443",
        "result": BUILD / "witchweapon-online-sweep-param-v7-test.apk",
        "report": BUILD / "扫荡参数修复候选包验收-v7.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-task-reflection-v6.apk",
        "sha256": "47a93160097c26c124b49ccb352fd7e1b33de8a12555fcee104834d00a14514c",
        "endpoint": "https://127.0.0.1:19443",
        "result": BUILD / "witchweapon-online-local-staging-sweep-param-v7.apk",
        "report": BUILD / "本地测试服扫荡参数修复验收-v7.json",
    },
}
PRESERVED = {
    "assets/assetbundle/lua/lua_projx_patch.ab": EXPECTED_LUA_SHA256,
    "assets/assetbundle/config/clientexel/dictionarystatic.ab": EXPECTED_DICTIONARY_SHA256,
    "assets/assetbundle/scene/loginfromal.ab": EXPECTED_LOGIN_SHA256,
}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    hashed = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            hashed.update(block)
    return hashed.hexdigest()


def validate_table(before: bytes, after: bytes, reference: bytes) -> dict[str, int]:
    original_text = _csv_tree(reference, "InstanceMobList")[3]
    expected = _original_bonus_values(original_text)
    old_text = _csv_tree(before, "InstanceMobList")[3]
    new_text = _csv_tree(after, "InstanceMobList")[3]
    old_lines, new_lines = old_text.splitlines(), new_text.splitlines()
    if len(old_lines) != len(new_lines) or old_lines[0] != new_lines[0]:
        raise ValueError("MobList rows/header changed")
    seen, type_changes, param_changes = set(), 0, 0
    for old, new in zip(old_lines[1:], new_lines[1:]):
        a, b = old.split(","), new.split(",")
        identity = a[0]
        if len(a) != len(b) or a[0] != b[0]:
            raise ValueError("MobList row alignment changed")
        if identity not in MAINLINE_IDS or identity in CHAPTER16_IDS:
            if old != new:
                raise ValueError("Non-original stage row changed: " + identity)
            continue
        if identity in seen or identity not in expected:
            raise ValueError("Duplicate/unexpected mainline row: " + identity)
        seen.add(identity)
        if a[:3] + a[5:] != b[:3] + b[5:]:
            raise ValueError("Mainline row changed beyond sweep type/param: " + identity)
        if (b[3], b[4]) != expected[identity]:
            raise ValueError("Sweep type/param differs from original: " + identity)
        type_changes += a[3] != b[3]
        param_changes += a[4] != b[4]
    if seen != MAINLINE_IDS - CHAPTER16_IDS or type_changes != 0 or param_changes != 213:
        raise ValueError("Unexpected original MobList sweep parameter coverage")
    if expected["3110001002"] != ("2", "0.5"):
        raise ValueError("Stage 1-2 original sweep conditions changed")
    return {"originalStagesRestored": len(seen), "typeChanges": type_changes,
            "parameterChanges": param_changes, "temporaryChapter16RowsPreserved": len(CHAPTER16_IDS)}


def prepare(kind: str, reference: bytes) -> tuple[dict[str, bytes], dict[str, object]]:
    entry = SOURCE[kind]
    if sha256_file(entry["apk"]) != entry["sha256"]:
        raise ValueError("Reviewed v6 APK changed: " + kind)
    with zipfile.ZipFile(entry["apk"]) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read("assets/online_endpoint.txt") != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected source endpoint: " + kind)
        for name, expected_sha in PRESERVED.items():
            if digest(apk.read(name)) != expected_sha:
                raise ValueError("Expected v6 login/task patch missing: " + name)
        before = apk.read(MEMBER)
        index = apk.read(INDEX)
    if digest(before) != EXPECTED_SOURCE_BUNDLE_SHA256 or \
            digest(index) != EXPECTED_SOURCE_INDEX_SHA256:
        raise ValueError("Unreviewed v6 MobList or bundle index")
    after = patch_sweep_bonus_bundle(before, reference)
    coverage = validate_table(before, after, reference)
    new_index = patch_index(index, {"/config/clientexel/instancemoblist.ab": after})
    return {MEMBER: after, INDEX: new_index}, {
        "originalReferenceSha256": ORIGINAL_SHA256,
        "sourceEndpoint": entry["endpoint"],
        "instanceMobListSha256": digest(after),
        "bundleIndexSha256": digest(new_index),
        "sweepTable": coverage,
    }


def build_one(kind: str, replacements: dict[str, bytes], detail: dict[str, object]) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-sweep-param-v7-" + kind)
    if temp.exists():
        raise ValueError("Stale sweep parameter build temp: " + str(temp))
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
            raise ValueError("APK signer changed")
        with zipfile.ZipFile(entry["apk"]) as old, zipfile.ZipFile(entry["result"]) as new:
            for name in (*PRESERVED, "AndroidManifest.xml", "classes.dex",
                         "classes2.dex", "assets/online_endpoint.txt"):
                if old.read(name) != new.read(name):
                    raise ValueError("Unrelated payload member changed: " + name)
            for name, data in replacements.items():
                if new.read(name) != data:
                    raise ValueError("Signed sweep payload differs: " + name)
        report.update(detail)
        report["signerCertificateSha256"] = result_cert
        report["runtimeValidated"] = False
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        entry["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        sidecar = Path(str(entry["result"]) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(entry["result"]) != report["testApk"]["sha256"]:
            raise ValueError("Final signed APK differs from validation record")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-sweep-param-v7-" + kind:
                raise ValueError("Unsafe sweep parameter temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign both v7 APKs")
    args = parser.parse_args()
    if sha256_file(ORIGINAL) != ORIGINAL_SHA256:
        raise ValueError("Original MobList reference changed")
    reference = ORIGINAL.read_bytes()
    prepared = {kind: prepare(kind, reference) for kind in SOURCE}
    for name in (MEMBER, INDEX):
        if prepared["candidate"][0][name] != prepared["staging"][0][name]:
            raise ValueError("Production/test sweep payload diverged: " + name)
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_SWEEP_PARAM_V7_READY", report["testApk"]["sha256"])
    else:
        print("SWEEP_PARAM_V7_STATIC_OK", json.dumps(prepared["candidate"][1], sort_keys=True))


if __name__ == "__main__":
    main()
