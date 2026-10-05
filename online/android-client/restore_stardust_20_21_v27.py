"""Rebuild chapters 20/21 with portrait handoff matching original lessons."""

from pathlib import Path

import restore_stardust_20_21 as restore


restore.REPORT = Path(__file__).resolve().parents[1] / "docs/星尘降临20-21资源构建-v27.json"


if __name__ == "__main__":
    report = restore.build()
    print("STARDUST_STORY_V27_RESOURCES_OK", report["chapters"]["20"]["sentences"],
          report["chapters"]["21"]["sentences"])
