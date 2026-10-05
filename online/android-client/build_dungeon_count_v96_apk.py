"""Mirror the signed daily-attempt count hotfix in a full Android APK."""

from pathlib import Path

import build_dungeon_sweep_v95_apk as base


HERE = Path(__file__).resolve().parent
base.SOURCE = HERE / "build/witchweapon-dungeon-sweep-v95-test.apk"
base.SOURCE_SHA256 = "d75db284bcdab89ee8f2a7c0e17bab40841a2c2e73b5add4672fa5d65c7be21d"
base.OLD_CODE = 20043095
base.NEW_CODE = 20043096
base.OLD_NAME = "2.0.1.20043095"
base.NEW_NAME = "2.0.1.20043096"
base.INIT_SHA256 = "7eedd74aa0e7306864a44fbe405f087d8c2cc709e9aa8ea13014c1656ae38a05"
base.INIT = base.BLOBS / base.INIT_SHA256
base.OUTPUT = HERE / "build/witchweapon-dungeon-count-v96-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-dungeon-count-v96")


if __name__ == "__main__":
    base.build()
