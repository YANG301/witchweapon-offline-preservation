"""Build a test APK that selects the preserved base-station first tutorial.

The source is the already tested original-UI new-account v2 APK.  This changes
only LessonTrigger.ab and its bundle index; registration, online endpoints,
native libraries and all other original resources remain byte-identical.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_online_apk import patch_index
import patch_original_tutorial_route as route


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-new-account-v2-register-fix.apk"
SOURCE_SHA256 = "80f02c2507549a2bd5e4013a4b9718149331e4f280afbba31b837d616646122b"
TRIGGER_SHA256 = "ac6cfe5d05078975750f37eb338de7fb9dd5114f44a26347a3fc1fb0fc454d73"
TRIGGER = "assets/assetbundle/config/clientexel/lessontrigger.ab"
INDEX = "assets/m.assets_list.txt"
RESULT = HERE / "build/witchweapon-online-original-ui-base-station-tutorial-v2-test.apk"
REPORT = HERE / "build/基地版新手教程候选包验收-v2.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-base-station-tutorial-v2")
ORIGINAL_ASSETS = (
    "assets/assetbundle/assets/resources/guide/lesson/lesson10001.ab",
    "assets/assetbundle/assets/resources/guide/lesson/lesson00001.ab",
    "assets/assetbundle/scene/map_1020_basestation.ab",
    "assets/assetbundle/video/00001_1.mp4",
)


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned new-account v2 APK missing or changed")
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or any(name not in names for name in
                                             (TRIGGER, INDEX, *ORIGINAL_ASSETS)):
            raise ValueError("Source APK lacks an original tutorial resource")
        old = source.read(TRIGGER)
        if hashlib.sha256(old).hexdigest() != TRIGGER_SHA256:
            raise ValueError("Source LessonTrigger bundle changed")
        patched = route.patch_bundle(old)
        if patched == old or route.patch_bundle(patched) != patched:
            raise ValueError("Base-station tutorial route patch is invalid")
        index = patch_index(source.read(INDEX),
                            {"/config/clientexel/lessontrigger.ab": patched})
    return {TRIGGER: patched, INDEX: index}


def build() -> dict[str, object]:
    replacements = prepare()
    base.SOURCE = SOURCE
    base.SOURCE_SHA256 = SOURCE_SHA256
    base.TEMP = TEMP
    report = base.build(replacements, RESULT, REPORT)
    report.pop("changedUnityTextAsset", None)
    report.pop("originalUnityTextAssetSha256", None)
    report.pop("preservesV4TaskItemPatch", None)
    report.pop("nativeRefreshClass", None)
    report["changedUnityTextAsset"] = "LessonTrigger"
    report["originalBundleSha256"] = TRIGGER_SHA256
    report["tutorial"] = {
        "openingStory": "lesson10001",
        "firstBattle": 3150001001,
        "firstBattleQuest": 509005002,
        "battleLesson": "lesson00001",
        "scene": "map_1020_basestation",
        "sourceResourcesPresent": list(ORIGINAL_ASSETS),
    }
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",
                      encoding="utf-8")
    with zipfile.ZipFile(RESULT) as result:
        if result.read(TRIGGER) != replacements[TRIGGER] or \
                result.read(INDEX) != replacements[INDEX]:
            raise ValueError("Signed APK tutorial route differs from reviewed bytes")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.check:
        replacements = prepare()
        print("BASE_STATION_TUTORIAL_INPUTS_OK",
              hashlib.sha256(replacements[TRIGGER]).hexdigest())
        return
    report = build()
    print("BASE_STATION_TUTORIAL_APK_READY", report["testApk"]["sha256"],
          RESULT)


if __name__ == "__main__":
    main()
