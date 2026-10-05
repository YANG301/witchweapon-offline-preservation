"""Sign the chapter-20 missing-background bypass and its rollback."""

import argparse
import json
from pathlib import Path

import build_original_stardust_hotupdate_v29 as previous


PROJECT = Path(__file__).resolve().parents[1]
LESSON = "assetbundle/assets/resources/guide/lesson/lesson30320.ab"
FIX = PROJECT / "docs/星尘降临第20节缺图跳过候选.json"
ROLLBACK = previous.REPORT
FIX_SHA = "f85d70be1a8d19f319383f560e9f24164a533113ac695c988330bbecfd046d75"
ROLLBACK_SHA = "5ff406f3a0dbd7c336c9b48425804be0544e96527b74bcf6ad011209c7c32de3"


def build(mode: str) -> str:
    report = json.loads((FIX if mode == "fix" else ROLLBACK).read_text(encoding="utf-8"))
    expected = FIX_SHA if mode == "fix" else ROLLBACK_SHA
    if len(report["assets"]) != 65 or report["assets"][LESSON]["sha256"] != expected:
        raise ValueError("Reviewed story resource inventory changed")
    if mode == "fix" and (report["missingBackgroundHandling"]["skippedNodeId"] != "744"
                          or report["missingBackgroundHandling"]["retainedOriginalActionNodes"] != 436):
        raise ValueError("Reviewed chapter bypass changed")
    builder = previous.builder
    builder.PREVIOUS = previous.BASELINE
    builder.SEQUENCE = 33 if mode == "fix" else 34
    assets = dict(builder.ASSETS)
    if len(assets) != 8:
        raise ValueError("Baseline overlay changed")
    for logical, details in report["assets"].items():
        if logical in assets:
            raise ValueError("Story resource collides with baseline: " + logical)
        assets[logical] = details["sha256"]
    if len(assets) != 73:
        raise ValueError("Incomplete story overlay")
    builder.ASSETS = assets
    return builder.build()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("fix", "rollback"))
    selected = parser.parse_args().mode
    print("STARDUST20_SKIP_" + selected.upper() + "_READY", build(selected))
