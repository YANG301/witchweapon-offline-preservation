"""Build a signed APK that admits level-one witches to Barrier Maze teams.

The pinned source is the current draw-retry/all-week APK. Only Constant.ab and
its asset-index entry change. This command never installs or deploys the APK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_online_apk import patch_index
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
import patch_maze_servant_level_gate as gate
from patch_feature_level_gates import _constant_tree


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-draw-retry-all-week-v2.apk"
SOURCE_SHA256 = "b51a0768f3628dd7c2784f1f67501a195475a922329406e08de4b0bd8b3da68e"
SOURCE_CONSTANT_SHA256 = "8ea1ae95071c46e7d224d87ba0ae9442641e3c10f52dc2ca3b8258c4636dd878"
RESULT = HERE / "build/witchweapon-online-original-ui-maze-servant-level1-v1.apk"
REPORT = HERE / "build/原版结界迷宫魔女等级门槛修复候选包验收.json"
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
TEMP = TEMP_PARENT / "witch-online-maze-servant-level1"
BUNDLE = "assets/assetbundle/config/clientexel/constant.ab"
INDEX = "assets/m.assets_list.txt"
INDEX_KEY = "/config/clientexel/constant.ab"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned draw-retry/all-week source APK is missing or changed")
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or BUNDLE not in names or INDEX not in names:
            raise ValueError("Unexpected source APK member inventory")
        original = source.read(BUNDLE)
        if sha256(original) != SOURCE_CONSTANT_SHA256:
            raise ValueError("Pinned Constant bundle changed")
        updated = gate.patch_bundle(original)
        if updated == original or gate.patch_bundle(updated) != updated:
            raise ValueError("Maze servant level patch is missing or not idempotent")
        before = _constant_tree(original)[3]
        after = _constant_tree(updated)[3]
        if after.replace(gate.ROW_AFTER, gate.ROW_BEFORE) != before or \
                before.count(gate.ROW_BEFORE) != 1 or after.count(gate.ROW_AFTER) != 1:
            raise ValueError("An unrelated Constant CSV row changed")
        old_index = source.read(INDEX)
        new_index = patch_index(old_index, {INDEX_KEY: updated})
        old_lines = old_index.decode("utf-8").splitlines()
        new_lines = new_index.decode("utf-8").splitlines()
        if len(old_lines) != len(new_lines) or sum(a != b for a, b in zip(old_lines, new_lines)) != 1:
            raise ValueError("Asset index changed outside the Constant entry")
        differing = next(i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b)
        if "=" + INDEX_KEY + ":" not in old_lines[differing] or \
                "=" + INDEX_KEY + ":" not in new_lines[differing]:
            raise ValueError("Wrong asset index row changed")
    return {BUNDLE: updated, INDEX: new_index}


def verify_signed(replacements: dict[str, bytes]) -> tuple[int, str]:
    signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
    before = cert_digest(base.run(
        [*signer, "verify", "--print-certs", SOURCE], base.signer_env()))
    after = cert_digest(base.run(
        [*signer, "verify", "--print-certs", RESULT], base.signer_env()))
    if before != after:
        raise ValueError("APK signing certificate changed")
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(RESULT) as built:
        old_names = {name for name in source.namelist() if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in built.namelist() if not base.SIGNATURE.fullmatch(name)}
        if old_names != new_names or len(built.namelist()) != len(set(built.namelist())):
            raise ValueError("Signed APK payload inventory changed")
        for name, expected in replacements.items():
            if built.read(name) != expected:
                raise ValueError("Signed payload differs from verified replacement: " + name)
        unchanged = old_names - replacements.keys()
        for name in unchanged:
            old, new = source.getinfo(name), built.getinfo(name)
            if (old.file_size, old.CRC, old.compress_size) != \
                    (new.file_size, new.CRC, new.compress_size):
                raise ValueError("Unrelated payload member changed: " + name)
        for name in ("AndroidManifest.xml", "classes.dex", "classes2.dex",
                     "lib/arm64-v8a/libil2cpp.so", "lib/armeabi-v7a/libil2cpp.so"):
            if source.read(name) != built.read(name):
                raise ValueError("Inherited game or native patch changed: " + name)
    return len(unchanged), after


def build(replacements: dict[str, bytes]) -> dict:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned maze candidate already exists")
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA256, TEMP
    report = base.build(replacements, RESULT, REPORT)
    count, certificate = verify_signed(replacements)
    for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                  "preservesV4TaskItemPatch", "nativeRefreshClass"):
        report.pop(stale, None)
    report.update(
        purpose="Barrier Maze team editor accepts owned level-one witches",
        changedUnityAssets=["Constant.CORE_INSTANCE_SERVANT_MIN_LEVEL: 20 to 1"],
        changedPayloadMembers=sorted(replacements),
        unchangedPayloadMembersChecked=count,
        sameSignerCertificateSha256=certificate,
        sourceDrawRetryAndDailyWeekdayPatchesPreserved=True,
        mazeDailyResetAndTwelveServantLimitUnchanged=True,
        runtimeValidated=False,
    )
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign APK; never install")
    arguments = parser.parse_args()
    if TEMP.exists():
        raise ValueError("Unexpected previous maze build directory")
    try:
        replacements = prepare()
        if arguments.build:
            report = build(replacements)
            print("MAZE_SERVANT_LEVEL1_APK_READY", report["testApk"]["sha256"], RESULT)
        else:
            print("MAZE_SERVANT_LEVEL1_PATCH_CHECK_OK", sha256(replacements[BUNDLE]))
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != TEMP_PARENT.resolve() or resolved.name != TEMP.name:
                raise ValueError("Unsafe maze-build intermediate cleanup")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
