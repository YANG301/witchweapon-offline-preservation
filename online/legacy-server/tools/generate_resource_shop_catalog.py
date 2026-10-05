"""Extract the archived CN resource, sundry and recharge shelves.

The game is free. Recharge goods are virtual, zero-cost grants and never use
payment routes; their original nominal RMB values are recorded separately.
"""

import csv
import hashlib
import json
from pathlib import Path


SOURCE = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
OUTPUT = Path(__file__).resolve().parents[1] / "resources" / "resource_shop_catalog.json"
SETS = ("44000028", "44000009", "44000247", "44000007")
RECHARGE_GOODS = ("45990010", "45990011", "45990012", "45990013", "45990014", "45990015")
RECHARGE_PERIODS = ("day", "day", "week", "week", "month", "month")


def rows(name):
    with (SOURCE / name).open(encoding="utf-8-sig", newline="") as stream:
        return [row for row in list(csv.DictReader(stream))[2:] if row.get("ID")]


def integer(raw):
    return int(raw) if raw else 0


def main():
    sets = {row["ID"]: row for row in rows("shopset.txt")}
    shops = {row["ID"]: row for row in rows("shop.txt")}
    goods = {row["ID"]: row for row in rows("goods.txt")}
    big = {row["ID"]: row for row in rows("shopbigset.txt")
           if row["channel_group"] == "25"}
    assert [big[key]["shop_set1"] for key in ("47000003", "47000004", "47000001")] == [
        "44000028", "44000247", "44000007"]
    assert big["47000003"]["shop_set2"] == "44000009"
    output = []
    for set_id in SETS:
        source_set = sets[set_id]
        period = integer(source_set["period"])
        assert period == {"44000028": 24, "44000009": 0,
                          "44000247": 8, "44000007": 0}[set_id]
        result_set = {
            "id": int(set_id), "periodHours": period,
            "refreshCurrencyType": integer(source_set["refresh_currency_type"]),
            "refreshPrice": integer(source_set["refresh_price"]),
            "refreshLimit": integer(source_set["refresh_limit"]),
            "shops": [],
        }
        for index in range(1, 51):
            shop_id = source_set.get(f"shop{index}")
            if not shop_id:
                continue
            shop = shops[shop_id]
            shop_type = integer(shop["price_type"])
            result_shop = {
                "id": int(shop_id), "shopType": integer(shop["shop_type"]),
                "priceType": shop_type, "randomNum": integer(shop["random_num"]),
                "maxTotal": integer(shop["max_total_num"]), "goods": [],
            }
            if set_id == "44000247":
                assert shop_type in (1, 50) and result_shop["randomNum"] in (1, 2, 6)
            elif set_id == "44000007":
                assert shop_type == 99 and shop_id == "4502990003"
            else:
                assert shop_type == 50
            for slot in range(1, 61):
                good_id = shop.get(f"goods{slot}")
                if not good_id:
                    continue
                good = goods[good_id]
                kind = integer(good["type"])
                assert kind in (2, 3, 13, 99)
                product = {
                    "id": int(good_id), "type": kind,
                    "itemId": integer(good["goods_id"]),
                    "value": integer(good["goods_value"]) if kind in (13, 99) else
                             max(1, integer(good["goods_value"])),
                    "stock": integer(shop[f"num{slot}"]),
                    "price": integer(shop[f"price{slot}"]),
                    "goodsScore": integer(good["goods_score"]),
                }
                if set_id == "44000007":
                    assert good_id == RECHARGE_GOODS[slot - 1]
                    product["claimPeriod"] = RECHARGE_PERIODS[slot - 1]
                    product["originalPrice"] = product["price"]
                    product["price"] = 0
                    product["stock"] = 1
                result_shop["goods"].append(product)
            assert result_shop["goods"]
            result_set["shops"].append(result_shop)
        output.append(result_set)
    assert [len(item["shops"]) for item in output] == [1, 1, 12, 1]
    assert [len(item["shops"][0]["goods"]) for item in output] == [5, 8, 38, 6]
    assert output[2]["refreshCurrencyType"] == 50
    assert output[2]["refreshPrice"] == 10 and output[2]["refreshLimit"] == 30
    inputs = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
              for name in ("shopstructure.txt", "shopbigset.txt", "shopset.txt",
                           "shop.txt", "goods.txt")}
    catalog = {
        "schemaVersion": 1, "source": "Original CN channel-25 resource/sundry/recharge tables",
        "inputs": inputs, "sets": output,
        "policy": {
            "recharge": "zero-cost virtual claim; 18/30 RMB tiers daily, 60/128 weekly, 328/648 monthly; original nominal cents and Goods.goods_score retained",
            "sundry": "original 8-hour rotation and 10-diamond refresh, max 30 refreshes per 8-hour bucket; stable account-specific selection",
        },
    }
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RESOURCE_SHOP_CATALOG_OK", len(output), sum(len(group["shops"]) for group in output))


if __name__ == "__main__":
    main()
