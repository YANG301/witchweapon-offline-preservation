"""Extract both original CN/channel-25 Gift-tab groups, without paid orders."""

import csv
import hashlib
import json
from pathlib import Path


SOURCE = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
OUTPUT = Path(__file__).resolve().parents[1] / "resources" / "gift_shop_catalog.json"
GIFT_BIG_SETS = ("47000002", "47000016")
EXPECTED_SET_IDS = (
    "44000025", "44000074", "44000088", "44000006", "44000061",
    "44000022",  # Original monthly-card page in the same Gift tab.
)


def table(name, delimiter=","):
    with (SOURCE / name).open("r", encoding="utf-8-sig", newline="") as source:
        # The first three rows are field names, field types, Chinese descriptions.
        return [row for row in list(csv.DictReader(source, delimiter=delimiter))[2:]
                if row.get("ID")]


def main():
    big = [row for row in table("shopbigset.txt")
           if row["ID"] in GIFT_BIG_SETS and row["channel_group"] == "25"]
    if len(big) != 2 or {row["ID"] for row in big} != set(GIFT_BIG_SETS):
        raise ValueError("Original CN gift big sets are not unique")
    big.sort(key=lambda row: GIFT_BIG_SETS.index(row["ID"]))
    set_ids = [row[f"shop_set{index}"] for row in big
               for index in range(1, 11) if row.get(f"shop_set{index}")]
    if tuple(set_ids) != EXPECTED_SET_IDS:
        raise ValueError("Original gift sets have changed")
    sets = {row["ID"]: row for row in table("shopset.txt")}
    shops = {row["ID"]: row for row in table("shop.txt")}
    goods = {row["ID"]: row for row in table("goods.txt")}
    items = {row["ID"] for row in table("item.txt")}
    month_cards = {row["ID"]: row for row in table("monthcard.txt")}
    dictionary = {row["ID"]: row["content_chinese"]
                  for row in table("dictionary.tsv", delimiter="\t")}
    result = []
    product_count = 0
    for set_id in set_ids:
        original = sets[set_id]
        period = int(original["period"] or 0)
        if period not in (0, 24, 168):
            raise ValueError(f"Unexpected original gift period: {set_id}")
        group = {"id": int(set_id), "periodHours": period, "shops": []}
        for shop_index in range(1, 51):
            shop_id = original.get(f"shop{shop_index}")
            if not shop_id:
                continue
            shop = shops[shop_id]
            if shop["shop_type"] != "02":
                raise ValueError(f"Unexpected original gift shop type: {shop_id}")
            group_shop = {"id": int(shop_id), "originalPriceType": int(shop["price_type"]),
                          "goods": []}
            for good_index in range(1, 61):
                good_id = shop.get(f"goods{good_index}")
                if not good_id:
                    continue
                good = goods[good_id]
                item_id = good["goods_id"]
                if good["type"] == "03":
                    if item_id not in items:
                        raise ValueError(f"Gift item cannot be resolved: {good_id}")
                    payload = {"kind": "item", "itemId": int(item_id)}
                elif good["type"] == "82":
                    card = month_cards.get(item_id)
                    if card is None or card["item_id"] not in items or \
                            card["buy_item_id"]:
                        raise ValueError(f"Gift month card cannot be resolved: {good_id}")
                    payload = {"kind": "monthCard", "monthCardId": int(item_id),
                               "days": int(card["days"]),
                               "dailyItemId": int(card["item_id"])}
                else:
                    raise ValueError(f"Unexpected original Gift-tab goods type: {good_id}")
                original_limit = int(shop[f"num{good_index}"] or 0)
                if original_limit < 0:
                    raise ValueError(f"Invalid original gift limit: {good_id}")
                group_shop["goods"].append({
                    "id": int(good_id), **payload,
                    "originalLimit": original_limit,
                    "originalPrice": int(shop[f"price{good_index}"] or 0),
                    "goodsScore": int(good["goods_score"] or 0),
                    "name": dictionary.get(good["name"], ""),
                })
                product_count += 1
            group["shops"].append(group_shop)
        result.append(group)
    if product_count != 19:
        raise ValueError(f"Expected 19 original gift products, got {product_count}")
    inputs = {}
    for name in ("shopbigset.txt", "shopset.txt", "shop.txt", "goods.txt", "item.txt",
                 "monthcard.txt", "dictionary.tsv"):
        inputs[name] = hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
    catalog = {
        "schemaVersion": 1,
        "source": "Original client tables, channel_group=25, Gift bigsets 47000002 and 47000016",
        "inputs": inputs,
        "bigSetIds": [int(value) for value in GIFT_BIG_SETS],
        "sets": result,
        "policy": {
            "price": "free; no external payment routes",
            "limited": "original quantity; 24h daily / 168h weekly China calendar reset",
            "originalUnlimited": "The two unlimited item packages (num=0) get one free claim/account/China day to prevent farming; the unlimited monthly card renews only after expiry",
            "monthCard": "Original 30/15-day daily item IDs; free claim only after current card expires (ID 1), or original once-per-account limit (ID 6); current-day reward granted lazily, missed days not backfilled",
        },
    }
    OUTPUT.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"Wrote {OUTPUT}: {len(result)} sets, {product_count} goods")


if __name__ == "__main__":
    main()
