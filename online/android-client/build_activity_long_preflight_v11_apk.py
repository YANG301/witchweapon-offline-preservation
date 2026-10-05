"""Sign v11 APKs from v10 with the activity shop C# long preflight fix."""

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
import patch_activity_shop_long_preflight as activity


HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
INDEX = "assets/m.assets_list.txt"
ENDPOINT = "assets/online_endpoint.txt"
DEX = "classes2.dex"
EXPECTED_INDEX_SHA256 = "9b98e511e924610558a3dd0ca90a16ad7858a3e75bf69ea0f085a339021e2a87"
EXPECTED_PATCH_SHA256 = "737fd385749dd3fcc2033ebbfacc531b9579587072ff3a24cbdf4c529618ae70"
EXPECTED_SIGNER_SHA256 = "cddd2e10d32647d55a92df15d38b3b41675414f7c41bc3c50874989bdc34d218"
SOURCE = {
    "candidate": {
        "apk": BUILD / "witchweapon-online-activity-payment-v10-test.apk",
        "sha256": "49f8cb6bb2923b408a3c4565db928f93e5aeba72c5c9ea5d9909564cd495fa8c",
        "endpoint": "https://212.192.15.11:18443",
        "dexSha256": "21707cf87f9a41f9685c64f1494be0aafc3e2e18af5d23c8929762f69f2aa8b9",
        "result": BUILD / "witchweapon-online-activity-long-preflight-v11-test.apk",
        "report": BUILD / "活动商店时间预检候选包验收-v11.json",
    },
    "staging": {
        "apk": BUILD / "witchweapon-online-local-staging-activity-payment-v10.apk",
        "sha256": "0391560909568f1486b661f763cd9f6e0a7acf6aede594910d2a5235be524faf",
        "endpoint": "https://127.0.0.1:19443",
        "dexSha256": "024ac5e3c3bebed9e2a0b2eb5258696daef7a2c5811bddf8c080f7058f4e3a56",
        "result": BUILD / "witchweapon-online-local-staging-activity-long-preflight-v11.apk",
        "report": BUILD / "本地测试服活动商店时间预检验收-v11.json",
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


def prepare(kind: str) -> tuple[dict[str, bytes], dict]:
    entry = SOURCE[kind]
    if sha256_file(entry["apk"]) != entry["sha256"]:
        raise ValueError("Reviewed v10 source APK changed: " + kind)
    with zipfile.ZipFile(entry["apk"]) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        if apk.read(ENDPOINT) != (entry["endpoint"] + "\n").encode("ascii"):
            raise ValueError("Unexpected endpoint: " + kind)
        if digest(apk.read(DEX)) != entry["dexSha256"]:
            raise ValueError("Network DEX changed: " + kind)
        index_before = apk.read(INDEX)
        if digest(index_before) != EXPECTED_INDEX_SHA256:
            raise ValueError("Unreviewed v10 bundle index")
        lua_before = apk.read(activity.MEMBER)
    lua_after = activity.patch_bundle(lua_before)
    if lua_after == lua_before:
        raise ValueError("Activity Lua bundle unchanged")
    index_after = patch_index(index_before, {"/lua/lua_projx_ui.ab": lua_after})
    if index_after == index_before:
        raise ValueError("Bundle index unchanged")
    return {activity.MEMBER: lua_after, INDEX: index_after}, {
        "sourceApkSha256": entry["sha256"],
        "sourceEndpoint": entry["endpoint"],
        "networkDexSha256": entry["dexSha256"],
        "patchedLuaBundleSha256": digest(lua_after),
        "bundleIndexSha256": digest(index_after),
        "change": "UIActivities.lua accepts C# long StopTime values in special-shop preflight",
        "runtimeValidated": False,
    }


def build_one(kind: str, replacements: dict[str, bytes], detail: dict) -> dict:
    entry = SOURCE[kind]
    temp = TEMP_PARENT / ("witch-online-activity-long-preflight-v11-" + kind)
    if temp.exists():
        raise ValueError("Stale v11 temp: " + str(temp))
    try:
        signer.SOURCE = entry["apk"]
        signer.SOURCE_SHA256 = entry["sha256"]
        signer.TEMP = temp
        report = signer.build(replacements, entry["result"], entry["report"])
        verify = [signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                  "verify", "--print-certs"]
        before_cert = cert_digest(signer.run([*verify, entry["apk"]], signer.signer_env()))
        after_cert = cert_digest(signer.run([*verify, entry["result"]], signer.signer_env()))
        if before_cert != EXPECTED_SIGNER_SHA256 or after_cert != before_cert:
            raise ValueError("APK signer changed")
        with zipfile.ZipFile(entry["apk"]) as old, zipfile.ZipFile(entry["result"]) as new:
            for name in ("AndroidManifest.xml", "classes.dex", DEX, ENDPOINT):
                if old.read(name) != new.read(name):
                    raise ValueError("Core APK member changed: " + name)
            if any(new.read(name) != data for name, data in replacements.items()):
                raise ValueError("Signed target member differs")
        report.update(detail)
        report["signerCertificateSha256"] = after_cert
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        entry["report"].write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
        sidecar = Path(str(entry["result"]) + ".idsig")
        if sidecar.is_file():
            sidecar.unlink()
        if sha256_file(entry["result"]) != report["testApk"]["sha256"]:
            raise ValueError("Signed result hash differs")
        return report
    finally:
        if temp.exists():
            resolved = temp.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or \
                    resolved.name != "witch-online-activity-long-preflight-v11-" + kind:
                raise ValueError("Unsafe v11 temp cleanup target")
            shutil.rmtree(resolved)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Build two signed v11 APKs")
    args = parser.parse_args()
    if sha256_file(HERE / "patch_activity_shop_long_preflight.py") != EXPECTED_PATCH_SHA256:
        raise ValueError("Activity patch changed after review")
    prepared = {kind: prepare(kind) for kind in SOURCE}
    if prepared["candidate"][0] != prepared["staging"][0]:
        raise ValueError("Candidate/staging game assets differ")
    if args.build:
        for kind in SOURCE:
            report = build_one(kind, *prepared[kind])
            print(kind.upper() + "_ACTIVITY_LONG_PREFLIGHT_V11_READY",
                  report["testApk"]["sha256"])
    else:
        print("ACTIVITY_LONG_PREFLIGHT_V11_STATIC_OK",
              json.dumps(prepared["candidate"][1], sort_keys=True))


if __name__ == "__main__":
    main()
