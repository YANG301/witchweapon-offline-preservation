"""Build the isolated local client with visible recharge-pack descriptions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import build_shop_runtime_v16_local_apk as composer
import build_shop_runtime_v17_local_apk as previous


BUILD = Path(__file__).resolve().parent / "build"
RESULT = BUILD / "witchweapon-online-local-staging-shop-runtime-v18.apk"
REPORT = BUILD / "本地测试服商店运行时验收-v18.json"
OLD = b"2.0.1.20043078"
NEW = b"2.0.1.20043079"


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
        raise ValueError("v18 output already exists")
    composer.RESULT = RESULT
    composer.REPORT = REPORT
    report = composer.build(changed)
    report["purpose"] = "Local original shop, exchange counts and visible recharge descriptions"
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
        print("SHOP_RUNTIME_V18_STATIC_OK", len(changed),
              composer.digest(changed["assets/m.assets_list.txt"]))
        return
    report = build(changed)
    print("SHOP_RUNTIME_V18_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
