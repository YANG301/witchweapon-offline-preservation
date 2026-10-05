"""Build an isolated APK that counts Android touch phases in the Unity window.

The input APK and project Java sources are read-only. Only classes2.dex changes;
the original Unity assets, native libraries, package ID and launcher are kept.
This is a diagnostic candidate, never an automatic install or deployment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

import build_original_ui_new_account_v2_apk as base


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-base-station-tutorial-v2-test.apk"
SOURCE_SHA256 = "327948e95ee0d386b2e62a7b00cd9ec179c08dc48de90792f85c38d09c8973e9"
SOURCE_DEX_SHA256 = "55ba6963af4c688d4f1b82e9f3e2e450c4ad986940d1ab6f8e01a6851d9d70ec"
RESULT = HERE / "build/witchweapon-online-original-ui-lottery-touch-probe.apk"
REPORT = HERE / "build/抽卡触摸隔离诊断包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-lottery-touch-probe")
TEMP_PARENT = Path(r"D:\Environment\Android\temp")
OFFLINE = HERE / "src/com/codex/witchweapon/OfflineApplication.java"
TRACE = HERE / "src/com/codex/witchweapon/LotteryTouchTrace.java"
ANCHOR = "        gameActivity = activity;\n"
INJECTION = ANCHOR + "        LotteryTouchTrace.attach(activity);\n"


def configure_base() -> None:
    base.SOURCE = SOURCE
    base.SOURCE_SHA256 = SOURCE_SHA256
    base.SOURCE_DEX_SHA256 = SOURCE_DEX_SHA256
    base.RESULT = RESULT
    base.REPORT = REPORT
    base.TEMP = TEMP


def check_inputs() -> set[str]:
    configure_base()
    old_classes = base.inspect_inputs()
    if TRACE.is_file() is False:
        raise ValueError("Missing diagnostic Java source")
    source = OFFLINE.read_text(encoding="utf-8")
    if source.count(ANCHOR) != 1 or "LotteryTouchTrace.attach" in source:
        raise ValueError("OfflineApplication lifecycle anchor changed")
    if "Lcom/codex/witchweapon/LotteryTouchTrace;" in old_classes:
        raise ValueError("Diagnostic class already exists in source DEX")
    return old_classes


def compile_trace(old_classes: set[str]) -> bytes:
    source_dir = TEMP / "source/com/codex/witchweapon"
    classes_dir = TEMP / "classes"
    dex_dir = TEMP / "dex"
    source_dir.mkdir(parents=True)
    classes_dir.mkdir()
    dex_dir.mkdir()
    patched = source_dir / "OfflineApplication.java"
    patched.write_text(OFFLINE.read_text(encoding="utf-8").replace(ANCHOR, INJECTION),
                       encoding="utf-8")
    sources = [patched, TRACE]
    sources.extend(HERE / "src/com/codex/witchweapon" / name
                   for name in base.ADAPTER if name != "OfflineApplication.java")
    sources.extend(base.AUTHOR / name for name in base.AUTHOR_HELPERS)
    env = os.environ.copy()
    env["TEMP"] = str(TEMP)
    env["TMP"] = str(TEMP)
    base.run([base.JAVAC, "-encoding", "UTF-8", "-source", "8", "-target", "8",
              "-classpath", base.ANDROID, "-d", classes_dir, *sources], env)
    class_files = sorted(classes_dir.rglob("*.class"))
    if not class_files:
        raise ValueError("Java compile emitted no classes")
    base.run([base.JAVA, "-cp", base.TOOLS / "lib/d8.jar",
              "com.android.tools.r8.D8", "--min-api", "21", "--lib",
              base.ANDROID, "--output", dex_dir, *class_files], env)
    dex = (dex_dir / "classes.dex").read_bytes()
    found = base.dex_classes(dex)
    if not old_classes.issubset(found) or \
            "Lcom/codex/witchweapon/LotteryTouchTrace;" not in found:
        raise ValueError("Candidate DEX lost adapter classes or touch probe")
    if hashlib.sha256(dex).hexdigest() == SOURCE_DEX_SHA256:
        raise ValueError("Candidate DEX did not change")
    return dex


def clean_temp() -> None:
    parent = TEMP_PARENT.resolve()
    target = TEMP.resolve()
    if target.parent != parent or TEMP.is_symlink():
        raise ValueError("Refusing to clean an unexpected build path")
    if TEMP.is_dir():
        shutil.rmtree(TEMP)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    old_classes = check_inputs()
    if args.check:
        print("LOTTERY_TOUCH_PROBE_INPUTS_OK", len(old_classes), "classes")
        return
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise ValueError("Diagnostic output or temporary directory already exists")
    TEMP.mkdir(parents=True)
    candidate_dex = compile_trace(old_classes)
    report = base.build(candidate_dex, old_classes)
    report["diagnostic"] = {
        "tag": "WW-LOTTERY-TOUCH",
        "records": ["DOWN", "UP/CANCEL", "moveCount", "consumed"],
        "recordsCoordinatesOrText": False,
        "changesInputEvents": False,
        "runtimeValidated": False,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    clean_temp()
    print("LOTTERY_TOUCH_PROBE_APK_READY", report["testApk"]["sha256"], RESULT)


if __name__ == "__main__":
    main()
