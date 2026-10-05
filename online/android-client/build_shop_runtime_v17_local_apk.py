"""Compose the isolated v17 client with verified live shop presentation.

The build retains the pinned v15 local-only endpoint, restores the original
shop title, embeds the active Lua hook, and advances asset cache version 78.
It never points at or changes the public server.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_shop_runtime_v16_local_apk as previous


BUILD = Path(__file__).resolve().parent / "build"
RESULT = BUILD / "witchweapon-online-local-staging-shop-runtime-v17.apk"
REPORT = BUILD / "本地测试服商店运行时验收-v17.json"
OLD = b"2.0.1.20043077"
NEW = b"2.0.1.20043078"


def prepare():
    changed = previous.prepare()
    if changed["assets/m.version"] != OLD + b"\r\n":
        raise ValueError("Unexpected prepared cache version")
    fixture = changed["assets/offline_responses.json"]
    if fixture.count(OLD) != 3 or NEW in fixture:
        raise ValueError("Unexpected prepared version fixture")
    changed["assets/m.version"] = NEW + b"\r\n"
    changed["assets/offline_responses.json"] = fixture.replace(OLD, NEW)
    return changed


def build(changed):
    if RESULT.exists() or REPORT.exists():
        raise ValueError("v17 output already exists")
    previous.RESULT = RESULT
    previous.REPORT = REPORT
    report = previous.build(changed)
    report["purpose"] = "Local original shop presentation, title and exchange counter"
    report["assetVersion"] = NEW.decode("ascii")
    report["runtimeValidated"] = False
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changed = prepare()
    if not args.build:
        print("SHOP_RUNTIME_V17_STATIC_OK", len(changed),
              previous.digest(changed["assets/m.assets_list.txt"]))
        return
    report = build(changed)
    print("SHOP_RUNTIME_V17_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
