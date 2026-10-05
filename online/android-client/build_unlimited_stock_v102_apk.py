"""Merge the signed unlimited-stock UI repair into a complete Android APK."""

from pathlib import Path

import build_resource_shop_v101_apk as previous


base = previous.base
HERE = Path(__file__).resolve().parent
LUA_SHA = "41687e77660680325c7c306509bfeeac20f62abb5f56750609e0369076156b94"
base.SOURCE = HERE / "build/witchweapon-resource-shop-v101-test.apk"
base.SOURCE_SHA256 = "8af6932968f68ef79434a2ef7e7ade5ca605227a8a890b42b26ab88d015be4d0"
base.OLD_CODE = 20043101
base.NEW_CODE = 20043102
base.OLD_NAME = "2.0.1.20043101"
base.NEW_NAME = "2.0.1.20043102"
base.INIT_SHA256 = LUA_SHA
base.INIT = base.BLOBS / LUA_SHA
base.ADDITIONAL_BUNDLES = {}
base.OUTPUT = HERE / "build/witchweapon-unlimited-stock-v102-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-unlimited-stock-v102")


if __name__ == "__main__":
    base.build()
