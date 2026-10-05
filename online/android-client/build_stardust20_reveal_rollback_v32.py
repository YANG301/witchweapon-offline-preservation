"""Pre-sign a monotonic rollback to the chapter-20 v29 story resources."""

import json

import build_stardust20_reveal_hotupdate_v31 as previous


builder = previous.builder


def build() -> str:
    baseline = json.loads(previous.previous.REPORT.read_text(encoding="utf-8"))
    if len(baseline["assets"]) != 65 or baseline["assets"][previous.LESSON]["sha256"] != (
            "5ff406f3a0dbd7c336c9b48425804be0544e96527b74bcf6ad011209c7c32de3"):
        raise ValueError("Reviewed v29 resources changed")
    builder.PREVIOUS = previous.LOCAL_BASELINE
    builder.SEQUENCE = 32
    builder.ASSETS = dict(builder.ASSETS)
    if len(builder.ASSETS) != 8:
        raise ValueError("Reviewed baseline overlay changed")
    for logical, info in baseline["assets"].items():
        if logical in builder.ASSETS:
            raise ValueError("Story resource collides with baseline overlay")
        builder.ASSETS[logical] = info["sha256"]
    if len(builder.ASSETS) != 73:
        raise ValueError("Incomplete rollback story overlay")
    return builder.build()


if __name__ == "__main__":
    print("STARDUST20_REVEAL_ROLLBACK_V32_READY", build())
