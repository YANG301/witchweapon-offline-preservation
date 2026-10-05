"""Sign the chapter-20 black-layer reveal correction as sequence 31."""

import json
from pathlib import Path

import build_original_stardust_hotupdate_v29 as previous


builder = previous.builder
PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "docs/星尘降临第20节遮罩切换修复候选.json"
LESSON = "assetbundle/assets/resources/guide/lesson/lesson30320.ab"
PREVIOUS_RELEASE = (
    "29-06fb4ba16491028a99574d644ddb79e890aaba7edd49dd004789e8038a3c0ca5")
LOCAL_BASELINE = (
    "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023")


def build() -> str:
    candidate = json.loads(REPORT.read_text(encoding="utf-8"))
    if (len(candidate["assets"]) != 65
            or candidate["assets"][LESSON]["sha256"] !=
            "5a3f3092c29dc753e78d6f0a348b792570019d784b96a5ee576956841ab123f4"
            or candidate["blackScreenAdaptation"]["clientActions"][-1] !=
            "HideColor after command at node 108"):
        raise ValueError("Reviewed reveal correction candidate changed")
    builder.PREVIOUS = LOCAL_BASELINE
    builder.SEQUENCE = 31
    builder.ASSETS = dict(builder.ASSETS)
    if len(builder.ASSETS) != 8:
        raise ValueError("Reviewed baseline overlay changed")
    for logical, info in candidate["assets"].items():
        if logical in builder.ASSETS:
            raise ValueError("Story resource collides with baseline overlay")
        builder.ASSETS[logical] = info["sha256"]
    if len(builder.ASSETS) != 73:
        raise ValueError("Incomplete corrected story overlay")
    return builder.build()


if __name__ == "__main__":
    print("STARDUST20_REVEAL_HOTUPDATE_V31_READY", build())
