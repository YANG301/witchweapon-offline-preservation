"""Sign the chapter 20/21 story resources as update sequence 25.

Only locally reviewed self-contained AssetBundles are included.  The signed
manifest can be deployed after staging playback succeeds; running this script
does not change the live server or the current update pointer.
"""

import json
from pathlib import Path

import build_unlimited_stock_hotupdate_v24 as previous


builder = previous.builder
HERE = Path(__file__).resolve().parent
REPORT = HERE.parent / "docs/星尘降临20-21资源构建.json"
EXPECTED_PREVIOUS = (
    "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023")
EXPECTED_APK = "9b2cba23a8f8130015ffe4502cce00f705b927ad81bd4de865520cb9ff596e31"


def build() -> str:
    details = json.loads(REPORT.read_text(encoding="utf-8"))
    if details["sourceApkSha256"] != EXPECTED_APK:
        raise ValueError("Story resources were built from another client")
    if details["chapters"]["20"]["sentences"] != 341 or (
            details["chapters"]["21"]["sentences"] != 196):
        raise ValueError("Story dialogue inventory changed")
    if len(details["assets"]) != 22 or len(details["newBackgrounds"]) != 16:
        raise ValueError("Story bundle inventory changed")
    builder.PREVIOUS = EXPECTED_PREVIOUS
    builder.SEQUENCE = 25
    builder.ASSETS = dict(builder.ASSETS)
    for path, info in details["assets"].items():
        if not path.startswith("assetbundle/") or path in builder.ASSETS:
            raise ValueError("Unexpected story update path: " + path)
        builder.ASSETS[path] = info["sha256"]
    return builder.build()


if __name__ == "__main__":
    print("STARDUST_STORY_HOTUPDATE_V25_CANDIDATE_OK", build())
