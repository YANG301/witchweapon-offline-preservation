"""Sign the fixed chapter 20/21 lesson flow as update sequence 27."""

import json
from pathlib import Path

import build_unlimited_stock_hotupdate_v24 as previous


builder = previous.builder
HERE = Path(__file__).resolve().parent
REPORT = HERE.parent / "docs/星尘降临20-21资源构建-v27.json"
LOCAL_BASELINE = (
    "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023")
SOURCE_APK_SHA256 = "9b2cba23a8f8130015ffe4502cce00f705b927ad81bd4de865520cb9ff596e31"


def build() -> str:
    details = json.loads(REPORT.read_text(encoding="utf-8"))
    if details["sourceApkSha256"] != SOURCE_APK_SHA256 or len(details["assets"]) != 22:
        raise ValueError("Chapter resource inventory changed")
    if details["chapters"]["20"]["sentences"] != 341 or (
            details["chapters"]["21"]["sentences"] != 196):
        raise ValueError("Chapter dialogue inventory changed")
    builder.PREVIOUS = LOCAL_BASELINE
    builder.SEQUENCE = 27
    builder.ASSETS = dict(builder.ASSETS)
    for path, info in details["assets"].items():
        if not path.startswith("assetbundle/") or path in builder.ASSETS:
            raise ValueError("Unexpected chapter asset: " + path)
        builder.ASSETS[path] = info["sha256"]
    return builder.build()


if __name__ == "__main__":
    print("STARDUST_STORY_HOTUPDATE_V27_CANDIDATE_OK", build())
