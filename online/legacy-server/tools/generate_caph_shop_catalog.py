"""Extract the CN CAPH point shelf from the preserved original client tables."""

import csv
import hashlib
import json
from pathlib import Path


SOURCE = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "resources" / "caph_shop_catalog.json"


def rows(name, delimiter=","):
    with (SOURCE / name).open("r", encoding="utf-8-sig", newline="") as stream:
        return [row for row in list(csv.DictReader(stream, delimiter=delimiter))[2:]
                if row.get("ID")]


def number(value, default=0):
    return int(value) if value else default


def main():
    structure = next(row for row in rows("shopstructure.txt")
                     if row["ID"] == "Vip" and row["channel_group"] == "25"
                     and row["language"] == "cn")
    if "47000009" not in structure["structure"].split("|"):
        raise ValueError("CAPH point big set is absent from original CN entrance")
    big = next(row for row in rows("shopbigset.txt") if row["ID"] == "47000009")
    if big["channel_group"] != "0" or big["shop_set1"] != "44000017":
        raise ValueError("Unexpected original CAPH point big set")
    source_set = next(row for row in rows("shopset.txt") if row["ID"] == "44000017")
    shops = {row["ID"]: row for row in rows("shop.txt")}
    goods = {row["ID"]: row for row in rows("goods.txt")}
    catalog = json.loads((ROOT / "resources" / "offline_responses.json")
                         .read_text(encoding="utf-8"))["_catalog"]
    if number(source_set["period"]) != 0 or number(source_set["refresh_price"]) != 0:
        raise ValueError("CAPH point set should have no rotation or priced refresh")
    shelf_ids = [source_set[f"shop{i}"] for i in range(1, 51)
                 if source_set.get(f"shop{i}")]
    if shelf_ids != ["4502080001", "4502080002", "4502080003"]:
        raise ValueError("Unexpected original CAPH point shelves")
    output = []
    for shop_id in shelf_ids:
        shop = shops[shop_id]
        if number(shop["price_type"]) != 8 or number(shop["random_num"]) != 0:
            raise ValueError("CAPH shelf must have fixed point prices")
        products = []
        for slot in range(1, 61):
            good_id = shop.get(f"goods{slot}")
            if not good_id:
                continue
            good = goods[good_id]
            kind, item_id = number(good["type"]), number(good["goods_id"])
            if kind == 3 and str(item_id) not in catalog["items"]:
                raise ValueError(f"Missing original CAPH item {item_id}")
            if kind not in (3, 13):
                raise ValueError(f"Unsupported CAPH reward type {kind}")
            products.append({"id": int(good_id), "type": kind, "itemId": item_id,
                             "value": number(good["goods_value"], 1),
                             "price": number(shop[f"price{slot}"]),
                             "stock": number(shop[f"num{slot}"])})
        output.append({"id": int(shop_id), "levelMin": number(shop["level_min"]),
                       "levelMax": number(shop["level_max"]), "priceType": 8,
                       "goods": products})
    if [len(shop["goods"]) for shop in output] != [6, 2, 1]:
        raise ValueError("Original CAPH shelf has unexpected product count")
    inputs = {name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
              for name in ("shopstructure.txt", "shopbigset.txt", "shopset.txt",
                           "shop.txt", "goods.txt")}
    result = {"schemaVersion": 1, "source": "Original APK CN/channel-25 Vip structure",
              "inputs": inputs, "bigSetId": 47000009, "setId": 44000017,
              "shops": output,
              "policy": "Original event opening schedule absent; preservation server exposes fixed point shelf"}
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Wrote {OUTPUT}: 3 shops, 9 original products")


if __name__ == "__main__":
    main()
