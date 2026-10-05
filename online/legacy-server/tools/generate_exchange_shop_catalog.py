"""Preserve the original CN/channel-25 exchange and secret-shop shelves.

The APK contains catalog data, not historical server rotation seeds or event
start/stop timestamps.  We keep those gaps explicit in the generated record.
"""

import csv
import hashlib
import json
from pathlib import Path


SOURCE = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "resources" / "exchange_shop_catalog.json"
RESPONSES = ROOT / "resources" / "offline_responses.json"
BIGSET_IDS = (
    "47000007", "47000006", "47000024", "47000023", "47000005",
    "47000008", "47000020", "47000019", "47000011", "47000025",
    "47000012", "47000026",
)
SECRET_DAILY = {"47000011", "47000025"}
SECRET_WEEKEND = {"47000012", "47000026"}


def rows(name, delimiter=","):
    with (SOURCE / name).open("r", encoding="utf-8-sig", newline="") as f:
        return [row for row in list(csv.DictReader(f, delimiter=delimiter))[2:]
                if row.get("ID")]


def number(value, default=0):
    return int(value) if value else default


def main():
    # Channel 25 ShopStructure directly references three all-channel (group 0)
    # BigSets. They are not missing channel rows and must not be dropped.
    big = {r["ID"]: r for r in rows("shopbigset.txt")
           if r["channel_group"] in ("0", "25")}
    sets = {r["ID"]: r for r in rows("shopset.txt")}
    shops = {r["ID"]: r for r in rows("shop.txt")}
    goods = {r["ID"]: r for r in rows("goods.txt")}
    dictionary = {r["ID"]: r["content_chinese"]
                  for r in rows("dictionary.tsv", "\t")}
    catalog = json.loads(RESPONSES.read_text(encoding="utf-8"))["_catalog"]
    output = []
    seen_sets = set()
    seen_goods = 0
    for big_id in BIGSET_IDS:
        entry = big[big_id]
        for slot in range(1, 11):
            set_id = entry.get(f"shop_set{slot}")
            if not set_id:
                continue
            if set_id in seen_sets:
                raise ValueError(f"Duplicate original set {set_id}")
            seen_sets.add(set_id)
            source_set = sets[set_id]
            period = number(source_set["period"])
            # 7# has no period in the static table.  Its original heading is
            # EverydaySecret; the local service uses a documented daily reset.
            effective_period = 24 if big_id in SECRET_DAILY else period
            result_set = {
                "id": int(set_id), "bigSetId": int(big_id),
                "name": dictionary.get(entry["name"], ""),
                "originalPeriodHours": period,
                "periodHours": effective_period,
                "weekendOnly": big_id in SECRET_WEEKEND,
                "refreshCurrencyType": number(source_set["refresh_currency_type"]),
                "refreshItem": number(source_set["refresh_item"]),
                "refreshPrice": number(source_set["refresh_price"]),
                "refreshLimit": number(source_set["refresh_limit"]),
                "needVip": number(source_set["need_vip"]),
                "vipIncrease": number(source_set["vip_increase"]),
                "shops": [],
            }
            for shop_slot in range(1, 51):
                shop_id = source_set.get(f"shop{shop_slot}")
                if not shop_id:
                    continue
                source_shop = shops[shop_id]
                price_type = number(source_shop["price_type"])
                if price_type not in (1, 2, 6, 7, 9, 10, 50):
                    raise ValueError(f"Unmapped original currency {shop_id}: {price_type}")
                result_shop = {
                    "id": int(shop_id), "kind": number(source_shop["shop_type"]),
                    "levelMin": number(source_shop["level_min"], 1),
                    "levelMax": number(source_shop["level_max"], 100),
                    "maxTotal": number(source_shop["max_total_num"]),
                    "randomNum": number(source_shop["random_num"]),
                    "priceType": price_type,
                    "currencyId": number(source_shop["currency_id"]),
                    "discountIds": [number(source_shop[f"discount{i}"])
                                    for i in range(1, 6) if source_shop.get(f"discount{i}")],
                    "goods": [],
                }
                for goods_slot in range(1, 61):
                    goods_id = source_shop.get(f"goods{goods_slot}")
                    if not goods_id:
                        continue
                    good = goods[goods_id]
                    item_type = number(good["type"])
                    item_id = number(good["goods_id"])
                    value = number(good["goods_value"], 1)
                    if item_type in (2, 3):
                        key = "equips" if item_type == 2 else "items"
                        if str(item_id) not in catalog[key]:
                            raise ValueError(f"Unknown original {key} reward: {goods_id}")
                    elif item_type not in (13, 85, 99):
                        raise ValueError(f"Unimplemented exchange reward {goods_id}: {item_type}")
                    price = number(source_shop[f"price{goods_slot}"])
                    stock = number(source_shop[f"num{goods_slot}"])
                    if price < 0 or stock < 0 or value < 1:
                        raise ValueError(f"Invalid original good {goods_id}")
                    result_shop["goods"].append({
                        "id": int(goods_id), "type": item_type,
                        "itemId": item_id, "value": value,
                        "price": price, "stock": stock,
                        "name": dictionary.get(good["name"], ""),
                        **({"needVip": number(good["need_vip"])}
                           if big_id in ("47000019", "47000020") else {}),
                        **({"timeId": number(good["time_id"])}
                           if big_id == "47000019" and good.get("time_id") else {}),
                    })
                    seen_goods += 1
                if not result_shop["goods"]:
                    raise ValueError(f"Empty original shop {shop_id}")
                result_set["shops"].append(result_shop)
            if not result_set["shops"]:
                raise ValueError(f"Empty original set {set_id}")
            output.append(result_set)
    if len(output) != 23 or seen_goods < 2000:
        raise ValueError(f"Unexpected original scope: {len(output)} sets, {seen_goods} goods")
    inputs = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
              for name in ("shopstructure.txt", "shopbigset.txt", "shopset.txt",
                           "shop.txt", "goods.txt", "dictionary.tsv")}
    result = {
        "schemaVersion": 1,
        "source": "Original APK clientexel, CN channel_group=25 plus shared channel_group=0; exchange + 7# + weekend airship",
        "inputs": inputs,
        "bigSetIds": [int(v) for v in BIGSET_IDS],
        "sets": output,
        "guildOriginDiscount": {
            "chanceBasisPoints": 2000, "discountBasisPoints": 1000,
            "source": "Owner-approved provisional odds; original screenshot confirms 10% reduction, historical server odds unavailable",
        },
        "policy": {
            "starScheduleEffectiveAt": 1790895600,
            "starSchedule": "Original starshop_1: magic devices reset each China calendar day; resource/core stock resets each pair of natural months (Jan-Feb, Mar-Apr, ...); original no-period costume shelf stays one-time",
            "starConditions": "Original starshop_2 and native SetItemUI: per-SetInfo VipExtra increases the base CAPH requirement, capped at level five; Cube Resources keeps its fixed Goods.need_vip",
            "starSelection": "Five preserved candidate groups, one device per group. Cube quantity follows the owner's five-item restoration target; the static table has no historical server quantity. Recollection refresh rerolls all five groups for one 150-fragment charge, with no repeat inside the day's five rotations.",
            "starEventWindows": [],
            "starEvents": "Core and costume Goods.time_id is preserved. No historical dates are available; they remain closed unless an explicit timeId/start/end window is configured. Product availability is independent of stock reset.",
            "daily7Reset": "Original set 44000070 omits period; local 7# stock resets each China day",
            "weekend": "Saturday/Sunday in China time; original server event time unavailable",
            "rotation": "Stable account/set/shop/bucket deterministic sample from original random pool",
            "discount": "Guild origin: stable per-account/item/day provisional discount; other original live promotions remain unavailable",
        },
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Wrote {OUTPUT}: {len(output)} sets, {seen_goods} catalog goods")


if __name__ == "__main__":
    main()
