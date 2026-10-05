"""Restore Resource/Sundry/Recharge and trim the public Gift page.

The archived offline APK replaced all three Resource categories with a supply
set. This patch restores the original channel-25 entry while keeping zero-cost
virtual claims routed through the existing in-game BuyResult, never an SDK.
It expects the v13 Gift/Exchange table patches to have run first.
"""

from __future__ import annotations

from patch_gift_shop_tables import _line_parts, _patch_bundle


BASE = "assets/assetbundle/config/clientexel/"
MEMBERS = {name: BASE + name.lower() + ".ab" for name in
           ("ShopStructure", "ShopBigSet", "ShopSet", "Shop", "Goods", "Dictionary")}
RESOURCE_CURRENT = "Resource,25,cn,离线补给商店,14700000101|47000001#9000|47000002|47000016"
RESOURCE_ORIGINAL = ("Resource,25,cn,资源商店,"
    "14700000301|47000003#14700000401|47000004#"
    "14700000101|47000001#9000|47000002|47000016")
PUBLIC_GIFT_SETS = ("44000025", "44000088", "44000006")
RECHARGE_GOODS = tuple(str(i) for i in range(45990010, 45990016))
RESOURCE_TIMERS = tuple(str(i) for i in range(45030268, 45030273))
RECHARGE_AMOUNTS = (36, 60, 120, 256, 656, 1300)


def recharge_desc_id(good_id):
    return "1459900" + str(int(good_id) - 45990000).zfill(2) + "03"


def recharge_desc_row(good_id, amount):
    return "\t".join((recharge_desc_id(good_id),
        f"领取后获得{amount}钻晶。", f"領取後獲得{amount}鑽晶。",
        f"受け取るとダイヤ{amount}個を獲得します。",
        f"수령 시 다이아 {amount}개를 얻습니다.",
        f"Receive {amount} Gems.", "0", "15"))


def update_dictionary(text, reference):
    lines = text.splitlines(keepends=True)
    original_lines = reference.splitlines()
    if not lines or lines[0].rstrip("\r\n") != original_lines[0] or \
            original_lines[0] != ("ID\tcontent_chinese\tcontent_tw\tcontent_jp\t"
                                  "content_kr\tcontent_en\tnot_required_translate\tchange"):
        raise ValueError("Unexpected Dictionary schema")
    original = [line.split("\t") for line in original_lines
                if line.startswith("14700000101\t")]
    original_title = [line.split("\t") for line in original_lines
                      if line.startswith("14700000102\t")]
    if len(original) != 1 or original[0][1] != "充值" or \
            len(original_title) != 1 or original_title[0][1] != "钻晶商店":
        raise ValueError("Original Recharge menu label changed")
    desc_rows = {recharge_desc_id(good): recharge_desc_row(good, amount)
                 for good, amount in zip(RECHARGE_GOODS, RECHARGE_AMOUNTS)}
    original_ids = {line.split("\t", 1)[0] for line in original_lines}
    if original_ids.intersection(desc_rows):
        raise ValueError("Recharge description IDs collide with original Dictionary")
    result = []
    seen = set()
    changed = 0
    for line in lines:
        payload, ending = line.rstrip("\r\n"), line[len(line.rstrip("\r\n")):]
        row = payload.split("\t")
        key = row[0]
        if key == "14700000101":
            if key in seen or len(row) != len(original[0]) or \
                    row[1] not in ("免费补给", "充值") or \
                    row[:1] + row[2:] != original[0][:1] + original[0][2:]:
                raise ValueError("Unexpected Recharge menu localization")
            seen.add(key)
            if row[1] != "充值":
                row[1] = "充值"
                changed += 1
                line = "\t".join(row) + ending
        elif key == "14700000102":
            if key in seen or len(row) != len(original_title[0]) or \
                    row[1] not in ("离线补给商店", "钻晶商店") or \
                    row[:1] + row[2:] != original_title[0][:1] + original_title[0][2:]:
                raise ValueError("Unexpected Recharge title localization")
            seen.add(key)
            if row[1] != "钻晶商店":
                row[1] = "钻晶商店"
                changed += 1
                line = "\t".join(row) + ending
        elif key in desc_rows:
            if key in seen or payload != desc_rows[key]:
                raise ValueError("Unexpected Recharge description localization")
            seen.add(key)
        result.append(line)
    if not {"14700000101", "14700000102"}.issubset(seen):
        raise ValueError("Recharge menu or title localization missing")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    if result and not result[-1].endswith(("\r", "\n")):
        result.append(newline)
    for key, row in desc_rows.items():
        if key not in seen:
            result.append(row + newline)
            changed += 1
    return "".join(result), changed


def update_rows(text, reference, table):
    lines = text.splitlines(keepends=True)
    refs = {line.split(",", 1)[0]: line.rstrip("\r\n").split(",")
            for line in reference.splitlines()}
    header = lines[0].rstrip("\r\n").split(",")
    if header != reference.splitlines()[0].split(","):
        raise ValueError("Unexpected " + table + " schema")
    count = 0
    output = []
    for line in lines:
        row, ending = _line_parts(line)
        original = row[:]
        key = row[0]
        if table == "ShopStructure" and tuple(row[:3]) == ("Resource", "25", "cn"):
            if line.rstrip("\r\n") not in (RESOURCE_CURRENT, RESOURCE_ORIGINAL):
                raise ValueError("Unexpected channel-25 Resource menu")
            if refs.get("Resource", []) != RESOURCE_ORIGINAL.split(","):
                # The original source has multiple channel rows with the same
                # ID; use its exact channel-25 line below instead.
                if RESOURCE_ORIGINAL not in reference.splitlines():
                    raise ValueError("Original Resource menu changed")
            row = RESOURCE_ORIGINAL.split(",")
            count += 1
        elif table == "ShopBigSet" and row[0] == "47000001" and row[1] == "25":
            source = next((x.split(",") for x in reference.splitlines()
                           if x.startswith("47000001,25,")), None)
            if source is None or source[5] != "44000007":
                raise ValueError("Original Recharge BigSet changed")
            if row != source and not (row[2] == "4" and row[5] == "44000001"):
                raise ValueError("Unexpected offline Recharge BigSet")
            row = source
            count += 1
        elif table == "ShopBigSet" and row[0] == "47000002" and row[1] == "25":
            if row[5:10] != ["44000025", "44000074", "44000088", "44000006", "44000061"]:
                if row[5:8] != list(PUBLIC_GIFT_SETS):
                    raise ValueError("Unexpected Gift BigSet")
            row[5:15] = list(PUBLIC_GIFT_SETS) + [""] * 7
            count += 1
        elif table == "ShopBigSet" and row[0] in ("47000003", "47000004") and row[1] == "25":
            source = next((x.split(",") for x in reference.splitlines()
                           if x.startswith(row[0] + ",25,")), None)
            expected_sets = ("44000028", "44000009") if row[0] == "47000003" else ("44000247",)
            if source is None or tuple(source[5:5+len(expected_sets)]) != expected_sets:
                raise ValueError("Original Resource BigSet changed")
            if row != source and not (row[2] == "4" and row[5] == "44000001"):
                raise ValueError("Unexpected offline Resource BigSet")
            row = source
            count += 1
        elif table == "ShopSet" and key == "44000006":
            if row[header.index("shop1")] != "4502990002" or \
                    row[header.index("shop2")] not in ("4502500025", ""):
                raise ValueError("Unexpected war-uniform Gift shelf")
            row[header.index("shop2")] = ""
            count += 1
        elif table == "Shop" and key == "4502990002":
            expected = ("45030639", "45030620", "45030621")
            actual = tuple(row[header.index("goods" + str(n))] for n in range(1, 4))
            if actual not in (expected, ("45030620", "45030621", "")):
                raise ValueError("Unexpected war-uniform goods")
            for slot, good in enumerate(("45030620", "45030621", ""), 1):
                row[header.index("goods" + str(slot))] = good
                row[header.index("price" + str(slot))] = "0" if good else ""
                row[header.index("num" + str(slot))] = "0" if good else ""
            count += 1
        elif table == "Shop" and key == "4502990003":
            source = refs.get(key)
            if source is None or source[header.index("price_type")] != "99":
                raise ValueError("Original Recharge shelf changed")
            if row[header.index("price_type")] not in ("99", "50"):
                raise ValueError("Unexpected Recharge payment type")
            for slot, good in enumerate(RECHARGE_GOODS, 1):
                if row[header.index("goods" + str(slot))] != good:
                    raise ValueError("Original Recharge product changed")
                if row[header.index("price" + str(slot))] not in \
                        (source[header.index("price" + str(slot))], "0"):
                    raise ValueError("Unexpected Recharge price")
                row[header.index("price" + str(slot))] = "0"
            row[header.index("price_type")] = "50"
            count += 1
        elif table == "Goods" and key in RESOURCE_TIMERS:
            source = refs.get(key)
            field = header.index("time_id")
            if source is None or source[field] != "1010004" or row[field] not in ("1010004", ""):
                raise ValueError("Unexpected retired Resource timer")
            row[field] = ""
            count += 1
        elif table == "Goods" and key in RECHARGE_GOODS:
            source = refs.get(key)
            field = header.index("good_desc")
            if source is None or not source[header.index("name")]:
                raise ValueError("Original Recharge description missing")
            description = recharge_desc_id(key)
            if row[field] not in ("", source[header.index("name")], description):
                raise ValueError("Unexpected Recharge description")
            row[field] = description
            count += 1
        if row != original:
            line = ",".join(row) + ending
        output.append(line)
    expected = {"ShopStructure": 1, "ShopBigSet": 4, "ShopSet": 1,
                "Shop": 2, "Goods": 11}[table]
    if count != expected:
        raise ValueError(f"Expected {expected} reviewed {table} rows, found {count}")
    return "".join(output)


def replacements(read_member, read_original_member):
    result = {}
    for table, member in MEMBERS.items():
        before = read_member(member)
        patch_text = ((lambda current, reference: update_dictionary(current, reference))
                      if table == "Dictionary" else
                      (lambda current, reference, table=table:
                       (update_rows(current, reference, table), 1)))
        after = _patch_bundle(before, read_original_member(member), table,
                              patch_text)
        if after != before:
            result[member] = after
    return result
