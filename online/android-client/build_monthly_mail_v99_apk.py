"""Include the sequence-21 inbox refresh in a signed complete APK."""

from pathlib import Path

import build_dungeon_sweep_v95_apk as base


HERE = Path(__file__).resolve().parent
base.SOURCE = HERE / "build/witchweapon-gift-contents-v98-test.apk"
base.SOURCE_SHA256 = (
    "f7f85780ba976af311bfd4f9177a6c7c8cc2c1a00b8bfc6fe5a2e6a8fe520098")
base.OLD_CODE = 20043098
base.NEW_CODE = 20043099
base.OLD_NAME = "2.0.1.20043098"
base.NEW_NAME = "2.0.1.20043099"
base.INIT_SHA256 = (
    "a6431c1e803c2dfc359f12e64f3e35528cc4b8ea5df90c1c175125d32471404d")
base.INIT = base.BLOBS / base.INIT_SHA256
base.ADDITIONAL_BUNDLES = {}
base.OUTPUT = HERE / "build/witchweapon-monthly-mail-v99-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-monthly-mail-v99")


if __name__ == "__main__":
    base.build()
