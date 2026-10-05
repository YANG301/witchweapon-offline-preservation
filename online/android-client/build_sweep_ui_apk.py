"""Build a same-package APK that restores only the native sweep-condition table."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_online_apk import patch_index
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from patch_sweep_bonus import patch_sweep_bonus_bundle


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-open-access-v1.apk"
SOURCE_SHA = "7a365e3c654d43157b0acbd0d8ed5b4fdb22fc8fbdfe21d033bd072332f3b536"
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel\instancemoblist.ab")
ORIGINAL_SHA = "e0d3f63b2764db408798ecf09a3ec330937acfd2771c1806c22138793f79bb5c"
MEMBER = "assets/assetbundle/config/clientexel/instancemoblist.ab"
INDEX = "assets/m.assets_list.txt"
RESULT = HERE / "build/witchweapon-online-original-ui-sweep-v1.apk"
REPORT = HERE / "build/原版扫荡入口验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-sweep-ui")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare():
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA:
        raise ValueError("Pinned open-access APK missing or changed")
    if not ORIGINAL.is_file() or base.sha256(ORIGINAL) != ORIGINAL_SHA:
        raise ValueError("Pinned original MobList asset missing or changed")
    original = ORIGINAL.read_bytes()
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or MEMBER not in names or INDEX not in names:
            raise ValueError("Unexpected open-access APK members")
        previous = source.read(MEMBER)
        patched = patch_sweep_bonus_bundle(previous, original)
        if patched == previous:
            raise ValueError("Original sweep UI condition was already restored")
        index = patch_index(source.read(INDEX), {
            "/config/clientexel/instancemoblist.ab": patched})
    return {MEMBER: patched, INDEX: index}, {
        "sourceResourceSha256": digest(previous),
        "targetResourceSha256": digest(patched),
        "targetResourceBytes": len(patched),
        "originalReferenceSha256": ORIGINAL_SHA,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Create and sign the APK")
    args = parser.parse_args()
    changes, resource = prepare()
    if not args.build:
        print("SWEEP_UI_PATCH_CHECK_OK", json.dumps(resource, ensure_ascii=False))
        return
    if TEMP.exists():
        raise ValueError("Unexpected previous sweep UI build temporary directory")
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA, TEMP
    try:
        report = base.build(changes, RESULT, REPORT)
        signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
        before = cert_digest(base.run([*signer, "verify", "--print-certs", SOURCE],
                                      base.signer_env()))
        after = cert_digest(base.run([*signer, "verify", "--print-certs", RESULT],
                                     base.signer_env()))
        if before != after:
            raise ValueError("APK signing identity changed")
        for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                      "preservesV4TaskItemPatch", "nativeRefreshClass"):
            report.pop(stale, None)
        report.update(campaignProfile="simple-campaign-v1", allMainlineUnlocked=True,
                      changedUnityAssets=["InstanceMobList.instBonusType: mainline only"],
                      sweepResource=resource, signerCertificateSha256=after,
                      inheritsAllUnchangedMembersFrom=SOURCE_SHA,
                      runtimeValidated=False)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print("SWEEP_UI_APK_READY", report["testApk"]["sha256"])
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r"D:\Environment\Android\temp").resolve() or \
                    resolved.name != "witch-online-sweep-ui":
                raise ValueError("Unsafe sweep UI build temporary cleanup")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
