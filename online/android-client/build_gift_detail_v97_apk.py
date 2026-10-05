"""Include the sequence-19 gift descriptions in a complete signed APK."""

from pathlib import Path

import build_dungeon_sweep_v95_apk as base


HERE = Path(__file__).resolve().parent
base.SOURCE = HERE / "build/witchweapon-dungeon-count-v96-test.apk"
base.SOURCE_SHA256 = "8611eff64d9698c9bc41066ef2130c2b216caf6ebf5d95a6c8686dd472db1dc3"
base.OLD_CODE = 20043096
base.NEW_CODE = 20043097
base.OLD_NAME = "2.0.1.20043096"
base.NEW_NAME = "2.0.1.20043097"
base.INIT_SHA256 = "1cceb1087f9ff428b492d74e687cb97a0c5d0edda515fee2abc94e472c3a4bc5"
base.INIT = base.BLOBS / base.INIT_SHA256
base.OUTPUT = HERE / "build/witchweapon-gift-detail-v97-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-gift-detail-v97")


if __name__ == "__main__":
    base.build()
