"""Ship the original gift item rows in the full APK alongside the hot update."""

from pathlib import Path

import build_dungeon_sweep_v95_apk as base


HERE = Path(__file__).resolve().parent
base.SOURCE = HERE / "build/witchweapon-dungeon-count-v96-test.apk"
base.SOURCE_SHA256 = "8611eff64d9698c9bc41066ef2130c2b216caf6ebf5d95a6c8686dd472db1dc3"
base.OLD_CODE = 20043096
base.NEW_CODE = 20043098
base.OLD_NAME = "2.0.1.20043096"
base.NEW_NAME = "2.0.1.20043098"
base.INIT_SHA256 = "7eedd74aa0e7306864a44fbe405f087d8c2cc709e9aa8ea13014c1656ae38a05"
base.INIT = base.BLOBS / base.INIT_SHA256
item_sha = "cb0fc7196a97924bbdb6d5c83146053fe48034993d2788a12ca6ec12bce56210"
base.ADDITIONAL_BUNDLES = {
    "assets/assetbundle/config/clientexel/item.ab": (base.BLOBS / item_sha, item_sha),
}
base.OUTPUT = HERE / "build/witchweapon-gift-contents-v98-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-gift-contents-v98")


if __name__ == "__main__":
    base.build()
