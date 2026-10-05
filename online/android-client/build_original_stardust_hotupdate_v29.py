"""Sign the preserved Stardust 19-21 candidate as update sequence 29."""

import json
from pathlib import Path

import build_stardust_story_rollback_v28 as previous


builder = previous.builder
PROJECT = Path(__file__).resolve().parents[1]
REPORT = PROJECT / "docs/星尘降临原版19-21资源候选.json"
BASELINE = "24-c1f08ba0cf43d89b945b917916e0c2f467086bdc118f96e9ea05c4144fba2023"


def build() -> str:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    if (data["sourceVersion"] != "2.0.1.20092956" or
            data["sourceApkSha256"] !=
            "ab79f49e33df8a12ae9b87ed8955b431001f471bb7724d5bef24606e011b9367" or
            len(data["assets"]) != 65 or data["missingOriginalAssets"] or
            data["blackScreenAdaptation"]["coverNode"] != 105):
        raise ValueError("Preserved chapter candidate changed")
    builder.PREVIOUS = BASELINE
    builder.SEQUENCE = 29
    builder.ASSETS = dict(builder.ASSETS)
    for path, info in data["assets"].items():
        if not path.startswith("assetbundle/") or path in builder.ASSETS:
            raise ValueError("Unexpected preserved story asset: " + path)
        builder.ASSETS[path] = info["sha256"]
    return builder.build()


if __name__ == "__main__":
    print("ORIGINAL_STARDUST_HOTUPDATE_V29_READY", build())
