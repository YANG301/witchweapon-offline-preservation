"""Build a signed original-UI test APK with reviewed player-level gates lowered.

The source v4 APK already contains the restored login, chat, banner and task
counter. The v6 quest-refresh Lua fix and two level-table bundles are applied
in one pass, so this candidate does not regress those earlier features.
Only static payload/signature checks are performed here; runtime onboarding
must be tested with a separate account and emulator instance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_online_apk import patch_index
import patch_feature_level_gates as gates


HERE = Path(__file__).resolve().parent
CONSTANT = "assets/assetbundle/config/clientexel/constant.ab"
INSTANCE_SET = "assets/assetbundle/config/clientexel/instanceset.ab"
INDEX = "assets/m.assets_list.txt"
RESULT = HERE / "build" / "witchweapon-online-original-ui-new-account-v1-test.apk"
REPORT = HERE / "build" / "新账号与等级入口候选包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-new-account-v1")


def prepare() -> dict[str, bytes]:
    replacements = base.prepare()
    with zipfile.ZipFile(base.SOURCE) as source:
        if CONSTANT not in source.namelist() or INSTANCE_SET not in source.namelist():
            raise ValueError("Reviewed level-table bundles are absent from source APK")
        constant = gates.patch_bundle(source.read(CONSTANT))
        instance_set = gates.patch_instance_set_bundle(source.read(INSTANCE_SET))
        replacements[CONSTANT] = constant
        replacements[INSTANCE_SET] = instance_set
        replacements[INDEX] = patch_index(source.read(INDEX), {
            "/lua/lua_projx_ui.ab": replacements[base.BUNDLE],
            "/config/clientexel/constant.ab": constant,
            "/config/clientexel/instanceset.ab": instance_set,
        })
    return replacements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    replacements = prepare()
    if args.check:
        print("NEW_ACCOUNT_APK_STATIC_CHECK_OK", {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in sorted(replacements.items())
        })
        return
    # Reuse the reviewed ZIP-copy/signature verifier, with task-scoped
    # intermediates on the portable Android toolchain drive.
    base.TEMP = TEMP
    report = base.build(replacements, RESULT, REPORT)
    report["changedLevelTables"] = ["Constant", "InstanceSet"]
    report["playerLevelGatesLowered"] = {"Constant": 27, "InstanceSet": 26}
    report["preservesChapterPrerequisites"] = True
    report["runtimeValidated"] = False
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("NEW_ACCOUNT_APK_READY", report["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
