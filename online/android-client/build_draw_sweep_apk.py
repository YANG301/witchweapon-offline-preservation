"""Combine the pinned draw-retry client with sweep UI and original Gift tab.

Only InstanceMobList, ShopStructure, ShopBigSet, Shop, Goods, the asset index,
and one zero-price comparison per IL2CPP architecture change.
The priced draw Constant and Android request bridge survive byte-for-byte.
"""

import json
from pathlib import Path
import sys
import zipfile

import build_sweep_ui_apk as sweep
from build_online_apk import patch_index
from patch_gift_shop_tables import gift_bundle_replacements
from patch_zero_price_shop_cost import zero_price_shop_replacements


HERE = Path(__file__).resolve().parent
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel")
sweep.SOURCE = HERE / "build/witchweapon-online-original-ui-draw-retry-all-week-v2.apk"
sweep.SOURCE_SHA = "b51a0768f3628dd7c2784f1f67501a195475a922329406e08de4b0bd8b3da68e"
sweep.RESULT = HERE / "build/witchweapon-online-original-ui-gift-draw-sweep-v3.apk"
sweep.REPORT = HERE / "build/原版礼包抽卡扫荡组合包验收-v3.json"
sweep.TEMP = Path(r"D:\Environment\Android\temp\witch-online-sweep-ui")
_sweep_prepare = sweep.prepare


def prepare_combined():
    replacements, audit = _sweep_prepare()
    with zipfile.ZipFile(sweep.SOURCE) as source:
        gifts = gift_bundle_replacements(
            source.read,
            lambda member: (ORIGINAL / Path(member).name).read_bytes(),
        )
        replacements.update(gifts)
        native = zero_price_shop_replacements(source.read)
        replacements.update(native)
        bundles = {name: payload for name, payload in replacements.items()
                   if name.startswith("assets/assetbundle/config/clientexel/")}
        replacements[sweep.INDEX] = patch_index(source.read(sweep.INDEX), {
            "/config/clientexel/" + Path(name).name: payload
            for name, payload in bundles.items()
        })
    audit["giftBundleSha256"] = {
        Path(name).name: sweep.digest(payload) for name, payload in gifts.items()
    }
    audit["zeroPriceNativeSha256"] = {
        name: sweep.digest(payload) for name, payload in native.items()
    }
    return replacements, audit


sweep.prepare = prepare_combined


def verify_inherited_draw() -> None:
    with zipfile.ZipFile(sweep.SOURCE) as source, zipfile.ZipFile(sweep.RESULT) as result:
        for name in (
            "classes2.dex",
            "assets/assetbundle/config/clientexel/constant.ab",
            "assets/assetbundle/config/clientexel/shopset.ab",
            "assets/assetbundle/config/clientexel/item.ab",
        ):
            if source.read(name) != result.read(name):
                raise ValueError("Unrelated inherited payload changed: " + name)
        for name, patched in zero_price_shop_replacements(source.read).items():
            if result.read(name) != patched:
                raise ValueError("Unexpected zero-price native payload: " + name)


if __name__ == "__main__":
    sweep.main()
    if "--build" in sys.argv:
        verify_inherited_draw()
        report = json.loads(sweep.REPORT.read_text(encoding="utf-8"))
        report["changedUnityAssets"] = [
            "InstanceMobList.instBonusType: repeatable mainline only",
            "ShopStructure: original channel-25 Gift tab",
            "ShopBigSet: original package and monthly-card groups",
            "Shop: free original package prices routed through in-game purchase",
            "Goods: remove five expired original personal timer references",
        ]
        report["inheritedPricedDrawAndAllWeekDaily"] = True
        report["zeroPriceNativeChange"] = "One guarded price-comparison instruction per ARM ABI"
        sweep.REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        print("GIFT_DRAW_SWEEP_INHERITANCE_OK")
