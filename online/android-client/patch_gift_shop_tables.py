"""Expose the original channel-25 Gift tab while retaining offline supply.

The author's offline client replaced the Resource entry with a single supply
shop and repointed Gift BigSet 47000002 at that supply set.  This changes only
those two CSV rows inside their Unity bundles.  The caller must update both
entries in ``assets/m.assets_list.txt`` when composing a signed APK.

The Gift tab has two original BigSets: item boxes (47000002) and monthly cards
(47000016). Both are restored; the author's original supply entry is retained.
"""

from __future__ import annotations

import codecs

from patch_feature_level_gates import _csv_tree


SHOPSTRUCTURE_MEMBER = "assets/assetbundle/config/clientexel/shopstructure.ab"
SHOPBIGSET_MEMBER = "assets/assetbundle/config/clientexel/shopbigset.ab"
SHOP_MEMBER = "assets/assetbundle/config/clientexel/shop.ab"
GOODS_MEMBER = "assets/assetbundle/config/clientexel/goods.ab"

_RESOURCE_KEY = ("Resource", "25", "cn")
_RESOURCE_ORIGINAL_ENTRY = "14700000101|47000001"
_RESOURCE_GIFT_ENTRY = "9000|47000002|47000016"
_RESOURCE_ENTRY = _RESOURCE_ORIGINAL_ENTRY + "#" + _RESOURCE_GIFT_ENTRY
_GIFT_BIGSETS = {
    "47000002": (("44000025", "44000074", "44000088", "44000006", "44000061"),
                 ("14700000201", "14700000202")),
    "47000016": (("44000022",), ("14700001601", "14700001602")),
}
# Seven original Shop rows under the two Gift-tab BigSets. All 19 slots are
# catalog-backed; type 99 opens the old platform payment flow, so the free
# server uses the original in-game price type 50 at zero cost instead.
_GIFT_SHOPS = {
    "4502990011": ("45030285", "45030435", "45030619"),
    "4502990025": ("45030431", "45030432", "45030433"),
    "4502990006": ("45030434", "45030301"),
    "4502990002": ("45030639", "45030620", "45030621"),
    "4502500025": ("45030460", "45030461", "45030462"),
    "4502990023": ("45030431", "45030432", "45030433"),
    "4502990008": ("45820001", "45820006"),
}
# These five original Gift Goods point to retired server-side TimeData IDs.
# NewShopPanelControl.RefrashShop dereferences GetTimeDatas(time_id).EndTime
# without a null check; no TimeData exists on the preservation server.
# ShopSet daily/weekly purchase periods remain server-enforced.  Removing just
# these obsolete item timers restores rendering without changing their gifts.
_GIFT_TIMED_GOODS = {
    "45030639": "1010130",
    "45030460": "1010010",
    "45030461": "1010011",
    "45030462": "1010011",
    "45820006": "1010003",
}


def _line_parts(line):
    payload = line.rstrip("\r\n")
    return payload.split(","), line[len(payload):]


def _original_rows(text, key_columns, keys):
    rows = {}
    for line in text.splitlines():
        fields = line.split(",")
        key = tuple(fields[:key_columns])
        if key in keys:
            if key in rows:
                raise ValueError("Duplicate original Gift table row")
            rows[key] = fields
    if set(rows) != set(keys):
        raise ValueError("Missing original Gift table row")
    return rows


def patch_shopstructure_text(text, original_text=None):
    """Append only the original Gift tab to the author's Resource entry."""
    if original_text is not None:
        reference = _original_rows(original_text, 3, {_RESOURCE_KEY})[_RESOURCE_KEY]
        if len(reference) != 5 or reference[3] != "资源商店" or \
                reference[4].split("#")[-1] != _RESOURCE_GIFT_ENTRY:
            raise ValueError("Original Gift-tab Resource entry changed")
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError("Empty ShopStructure table")
    header, _ = _line_parts(lines[0])
    if header != ["ID", "channel_group", "language", "name", "structure"]:
        raise ValueError("Unexpected ShopStructure header")
    seen = 0
    changed = 0
    output = []
    for line in lines:
        fields, ending = _line_parts(line)
        if tuple(fields[:3]) == _RESOURCE_KEY:
            seen += 1
            if len(fields) != 5 or fields[3] != "离线补给商店" or \
                    fields[4] not in (_RESOURCE_ORIGINAL_ENTRY, _RESOURCE_ENTRY):
                raise ValueError("Unexpected channel-25 Resource entry")
            if fields[4] != _RESOURCE_ENTRY:
                fields[4] = _RESOURCE_ENTRY
                line = ",".join(fields) + ending
                changed += 1
        output.append(line)
    if seen != 1:
        raise ValueError("Expected one channel-25 Resource entry")
    return "".join(output), changed


def patch_shopbigset_text(text, original_text=None):
    """Restore both original Gift BigSets without altering any other group."""
    if original_text is not None:
        keys={(bigset_id,"25") for bigset_id in _GIFT_BIGSETS}
        references=_original_rows(original_text,2,keys)
        for (bigset_id,_),row in references.items():
            ids,names=_GIFT_BIGSETS[bigset_id]
            if len(row)!=15 or row[2]!="2" or tuple(row[3:5])!=names or \
                    tuple(row[5:5+len(ids)])!=ids or \
                    row[5+len(ids):] != [""]*(10-len(ids)):
                raise ValueError("Original Gift BigSet row changed")
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError("Empty ShopBigSet table")
    header, _ = _line_parts(lines[0])
    expected = ["ID", "channel_group", "format", "name", "title"] + \
        [f"shop_set{i}" for i in range(1, 11)]
    if header != expected:
        raise ValueError("Unexpected ShopBigSet header")
    seen = set()
    changed = 0
    output = []
    for line in lines:
        fields, ending = _line_parts(line)
        if len(fields)>1 and fields[1]=="25" and fields[0] in _GIFT_BIGSETS:
            bigset_id=fields[0]
            if bigset_id in seen:
                raise ValueError("Duplicate channel-25 Gift BigSet")
            seen.add(bigset_id)
            target_ids,names=_GIFT_BIGSETS[bigset_id]
            if len(fields) != len(header) or tuple(fields[3:5]) != names:
                raise ValueError("Unexpected channel-25 Gift BigSet identity")
            original = fields[2] == "4" and fields[5:] == \
                ["44000001"] + [""] * 9
            restored = fields[2] == "2" and tuple(fields[5:5+len(target_ids)]) == \
                target_ids and fields[5+len(target_ids):] == [""] * (10-len(target_ids))
            if not original and not restored:
                raise ValueError("Unexpected channel-25 Gift BigSet contents")
            if original:
                fields[2] = "2"
                fields[5:] = list(target_ids)+[""]*(10-len(target_ids))
                line = ",".join(fields) + ending
                changed += 1
        output.append(line)
    if seen != set(_GIFT_BIGSETS):
        raise ValueError("Expected two channel-25 Gift BigSets")
    return "".join(output), changed


def patch_shop_text(text, original_text):
    """Route only original Gift-tab products through free in-game purchases."""
    lines = text.splitlines(keepends=True)
    reference = original_text.splitlines(keepends=True)
    if not lines or not reference:
        raise ValueError("Empty Shop table")
    header, _ = _line_parts(lines[0])
    original_header, _ = _line_parts(reference[0])
    if header != original_header or header[:8] != [
            "ID", "shop_type", "level_min", "level_max", "max_total_num",
            "random_num", "price_type", "currency_id"]:
        raise ValueError("Unexpected Shop header")
    originals = _original_rows(original_text, 1, {(key,) for key in _GIFT_SHOPS})
    seen = set()
    changed = 0
    output = []
    for line in lines:
        fields, ending = _line_parts(line)
        shop_id = fields[0]
        if shop_id in _GIFT_SHOPS:
            if shop_id in seen:
                raise ValueError("Duplicate Gift Shop row")
            seen.add(shop_id)
            source = originals[(shop_id,)]
            if len(fields) != len(header) or len(source) != len(header):
                raise ValueError("Malformed Gift Shop row")
            expected_goods = _GIFT_SHOPS[shop_id]
            if source[1] != "02" or source[6] not in ("50", "99") or \
                    fields[6] not in (source[6], "50"):
                raise ValueError("Unexpected Gift Shop payment type")
            allowed = {6}
            for index, good_id in enumerate(expected_goods, 1):
                good_column = header.index("goods" + str(index))
                price_column = header.index("price" + str(index))
                if source[good_column] != good_id or fields[good_column] != good_id or \
                        not source[price_column].isdigit() or \
                        fields[price_column] not in (source[price_column], "0"):
                    raise ValueError("Unexpected Gift Shop product slot")
                allowed.add(price_column)
            for index, (current, original) in enumerate(zip(fields, source)):
                if index not in allowed and current != original:
                    raise ValueError("Unreviewed Gift Shop column changed")
            patched = fields[:]
            patched[6] = "50"
            for index in range(1, len(expected_goods)+1):
                patched[header.index("price" + str(index))] = "0"
            if patched != fields:
                line = ",".join(patched) + ending
                changed += 1
        output.append(line)
    if seen != set(_GIFT_SHOPS):
        raise ValueError("Expected seven original Gift Shop rows")
    return "".join(output), changed


def patch_goods_text(text, original_text):
    """Drop only retired individual timers from original Gift goods.

    The offline client's TimeInfoHelper has no data for those old activity
    clocks.  We keep all names, reward IDs, type-82 month-card references and
    the separate ShopSet refresh periods intact.
    """
    lines = text.splitlines(keepends=True)
    reference = original_text.splitlines(keepends=True)
    if not lines or not reference:
        raise ValueError("Empty Goods table")
    header, _ = _line_parts(lines[0])
    original_header, _ = _line_parts(reference[0])
    if header != original_header or "time_id" not in header or header[0] != "ID":
        raise ValueError("Unexpected Goods header")
    time_column = header.index("time_id")
    originals = _original_rows(original_text, 1,
                               {(key,) for key in _GIFT_TIMED_GOODS})
    seen = set()
    changed = 0
    output = []
    for line in lines:
        fields, ending = _line_parts(line)
        good_id = fields[0]
        if good_id in _GIFT_TIMED_GOODS:
            if good_id in seen:
                raise ValueError("Duplicate timed Gift Goods row")
            seen.add(good_id)
            source = originals[(good_id,)]
            if len(fields) != len(header) or len(source) != len(header) or \
                    source[time_column] != _GIFT_TIMED_GOODS[good_id] or \
                    fields[time_column] not in (source[time_column], ""):
                raise ValueError("Unexpected retired Gift timer")
            if any(current != original for index, (current, original) in
                   enumerate(zip(fields, source)) if index != time_column):
                raise ValueError("Unreviewed Gift Goods column changed")
            if fields[time_column]:
                fields[time_column] = ""
                line = ",".join(fields) + ending
                changed += 1
        output.append(line)
    if seen != set(_GIFT_TIMED_GOODS):
        raise ValueError("Expected five timed Gift Goods rows")
    return "".join(output), changed


def _patch_bundle(raw, original_raw, name, patch_text):
    env, obj, tree, original, has_bom = _csv_tree(raw, name)
    _, _, _, reference, _ = _csv_tree(original_raw, name)
    patched, changed = patch_text(original, reference)
    if not changed:
        return raw
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + patched.encode("utf-8")
    tree["bytes"] = [byte ^ 255 for byte in encoded]
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, actual, bom_after = _csv_tree(result, name)
    if actual != patched or bom_after != has_bom:
        raise ValueError(name + " CSV failed bundle round-trip")
    return result


def patch_shopstructure_bundle(raw, original_raw):
    """Return ShopStructure bundle bytes for a composable APK replacement."""
    return _patch_bundle(raw, original_raw, "ShopStructure", patch_shopstructure_text)


def patch_shopbigset_bundle(raw, original_raw):
    """Return ShopBigSet bundle bytes for a composable APK replacement."""
    return _patch_bundle(raw, original_raw, "ShopBigSet", patch_shopbigset_text)


def patch_shop_bundle(raw, original_raw):
    """Return Shop bundle bytes with 19 free Gift-tab prices only."""
    return _patch_bundle(raw, original_raw, "Shop", patch_shop_text)


def patch_goods_bundle(raw, original_raw):
    """Return original Gift goods with retired TimeData references cleared."""
    return _patch_bundle(raw, original_raw, "Goods", patch_goods_text)


def gift_bundle_replacements(read_member, read_original_member):
    """Build three replacements from APK and original-bundle read callables.

    The parent builder may merge this mapping with other independent bundle
    replacements, then update the asset index once for all changed bundles.
    """
    output = {}
    for member, patch in ((SHOPSTRUCTURE_MEMBER, patch_shopstructure_bundle),
                          (SHOPBIGSET_MEMBER, patch_shopbigset_bundle),
                          (SHOP_MEMBER, patch_shop_bundle),
                          (GOODS_MEMBER, patch_goods_bundle)):
        before = read_member(member)
        after = patch(before, read_original_member(member))
        if after == before:
            raise ValueError("Gift bundle is already restored: " + member)
        output[member] = after
    return output
