"""Merge the signed resource-shop hot update into a complete Android APK."""

from pathlib import Path

import build_welfare_return_v100_apk as previous


base = previous.base
HERE = Path(__file__).resolve().parent
BLOBS = base.BLOBS
INIT_SHA = "4255fb381513e113a6ab2a0e1ae7482f7614e6a7a02437bd17382b9ee1e84271"
BIGSET_SHA = "d75a5514856c147016120df460046d33b8b5ca213e16762168dd99098ed052c5"
SHOP_SHA = "8f74afe74ae5633dc0592358abd3133cc64ed2ca369501d884e64cf07683a06c"
PREFAB_SHA = "e7482aaabd7f9d304694490e19f95e28ebf69e634c54cf645d568df0b396a408"

base.SOURCE = HERE / "build/witchweapon-welfare-return-v100-test.apk"
base.SOURCE_SHA256 = "7d88a0a08f6ba4aa829b2f6473a7e9a37ae101e99419016e4df36bc79caaac67"
base.OLD_CODE = 20043100
base.NEW_CODE = 20043101
base.OLD_NAME = "2.0.1.20043100"
base.NEW_NAME = "2.0.1.20043101"
base.INIT_SHA256 = INIT_SHA
base.INIT = BLOBS / INIT_SHA
base.ADDITIONAL_BUNDLES = {
    "assets/assetbundle/config/clientexel/shopbigset.ab": (BLOBS / BIGSET_SHA, BIGSET_SHA),
    "assets/assetbundle/config/clientexel/shop.ab": (BLOBS / SHOP_SHA, SHOP_SHA),
    "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab":
        (BLOBS / PREFAB_SHA, PREFAB_SHA),
}
base.OUTPUT = HERE / "build/witchweapon-resource-shop-v101-test.apk"
base.REPORT = base.OUTPUT.with_suffix(".json")
base.TEMP = Path(r"D:\Environment\Android\temp\witch-resource-shop-v101")


if __name__ == "__main__":
    base.build()
