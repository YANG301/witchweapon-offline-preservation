"""Mirror the signed welfare-return UI repair in a complete Android APK."""

from pathlib import Path

import build_monthly_mail_v99_apk as previous


base = previous.base
HERE = Path(__file__).resolve().parent
UI_SHA = "3654dbe119b72f1c5a0a2b86b581edc81ba7b84a13bfe85d63cfe1c078c40f61"
base.SOURCE = HERE / "build/witchweapon-monthly-mail-v99-test.apk"
base.SOURCE_SHA256 = "09606dd1271343d535a6415ab90c82751cdfd49da3a856f521f3e4bc9628469e"
base.OLD_CODE = 20043099
base.NEW_CODE = 20043100
base.OLD_NAME = "2.0.1.20043099"
base.NEW_NAME = "2.0.1.20043100"
base.ADDITIONAL_BUNDLES = {
    "assets/assetbundle/lua/lua_projx_ui.ab": (base.BLOBS / UI_SHA, UI_SHA),
}
base.OUTPUT = HERE / "build/witchweapon-welfare-return-v100-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-welfare-return-v100")


if __name__ == "__main__":
    base.build()
