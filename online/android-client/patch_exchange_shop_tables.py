"""Restore the offline APK's original exchange, 7# and airship entrances.

The author's offline edition points every channel-25 store entrance and every
shop BigSet at one unlimited supply shelf.  The underlying original ShopSet,
Shop and Goods tables are still present. Gift-tab patching may run first on
these same bundles. Powder uses its original level bands; 7# and airship
entrances stay open from level one without changing goods or prices.
"""

from __future__ import annotations

from pathlib import Path

from patch_gift_shop_tables import (
    SHOPSTRUCTURE_MEMBER, SHOPBIGSET_MEMBER, SHOP_MEMBER, _line_parts, _original_rows,
    _patch_bundle,
)


_BIGSETS = (
    "47000007", "47000006", "47000023", "47000008", "47000020",
    "47000019", "47000011", "47000012", "47000026",
)
_STRUCTURE_IDS = ("Exchange", "EverydaySecret", "WeekendSecret")
_PRUNED = {
    # Accept the previously shipped entrance as input when upgrading v12.
    # These three IDs have channel_group=0 BigSets shared by all channels.
    "Exchange": ("47000024", "47000005"),
    "EverydaySecret": ("47000025",),
    "WeekendSecret": (),
}
_OFFLINE_ENTRY = "14700000101|47000001"
_LEVEL_BANDS = ((1, 25), (26, 39), (40, 46), (47, 60),
                (61, 67), (68, 75), (76, 91), (92, 100))
_TIERED_SHOPS = {
    **dict(zip(("4501060001", "4501060002", "4501060003", "4501060004",
                "4501060010", "4501060006", "4501060007", "4501060008"),
               _LEVEL_BANDS)),
    **dict(zip(("4501010021", "4501010022", "4501010023", "4501010024",
                "4501010025", "4501010026", "4501010027", "4501010028"),
               _LEVEL_BANDS)),
    **dict(zip(("4501500011", "4501500012", "4501500013", "4501500014",
                "4501500015", "4501500016", "4501500017", "4501500018"),
               _LEVEL_BANDS)),
}
_POWDER_IDS = {"4501060001", "4501060002", "4501060003", "4501060004",
               "4501060010", "4501060006", "4501060007", "4501060008"}
_GUILD_LAST_IDS = {"4501070010", "4501070011", "4501070013"}


def _previous_structure(row):
    result = row[:]
    parts = []
    for panel in row[4].split("#"):
        pieces = [piece for piece in panel.split("|")
                  if piece not in _PRUNED[row[0]]]
        if len(pieces) > 1:
            parts.append("|".join(pieces))
    result[4] = "#".join(parts)
    return result


def patch_shopstructure_text(text, original_text):
    """Restore all original CN entrances, including shared group-0 BigSets."""
    keys = {(name, "25", "cn") for name in _STRUCTURE_IDS}
    references = _original_rows(original_text, 3, keys)
    lines = text.splitlines(keepends=True)
    if not lines or _line_parts(lines[0])[0] != [
            "ID", "channel_group", "language", "name", "structure"]:
        raise ValueError("Unexpected ShopStructure header")
    seen, changed, result = set(), 0, []
    for line in lines:
        fields, ending = _line_parts(line)
        key = tuple(fields[:3])
        if key in keys:
            if key in seen:
                raise ValueError("Duplicate original channel-25 shop entrance")
            seen.add(key)
            original = references[key]
            previous = _previous_structure(original)
            if len(fields) != 5 or fields not in (
                    [key[0], "25", "cn", "离线补给商店", _OFFLINE_ENTRY],
                    previous, original):
                raise ValueError("Unexpected modified exchange entrance " + key[0])
            if fields != original:
                fields = original
                line = ",".join(fields) + ending
                changed += 1
        result.append(line)
    if seen != keys:
        raise ValueError("Missing channel-25 exchange or secret entrance")
    return "".join(result), changed


def patch_shopbigset_text(text, original_text):
    """Restore original set IDs and special-shop layouts for nine BigSets."""
    keys = {(bigset, "25") for bigset in _BIGSETS}
    references = _original_rows(original_text, 2, keys)
    lines = text.splitlines(keepends=True)
    if not lines or _line_parts(lines[0])[0] != (
            ["ID", "channel_group", "format", "name", "title"] +
            [f"shop_set{i}" for i in range(1, 11)]):
        raise ValueError("Unexpected ShopBigSet header")
    seen, changed, result = set(), 0, []
    for line in lines:
        fields, ending = _line_parts(line)
        key = tuple(fields[:2])
        if key in keys:
            if key in seen:
                raise ValueError("Duplicate original channel-25 BigSet")
            seen.add(key)
            original = references[key]
            offline = original[:]
            offline[2] = "4"
            offline[5:] = ["44000001"] + [""] * 9
            if len(fields) != 15 or fields not in (offline, original):
                raise ValueError("Unexpected modified channel-25 BigSet " + key[0])
            if fields != original:
                line = ",".join(original) + ending
                changed += 1
        result.append(line)
    if seen != keys:
        raise ValueError("Missing original channel-25 BigSet")
    return "".join(result), changed


def patch_shop_level_text(text, original_text):
    """Restore powder bands and retain the last verified guild pool above 67."""
    keys = {(shop_id,) for shop_id in set(_TIERED_SHOPS) | _GUILD_LAST_IDS}
    references = _original_rows(original_text, 1, keys)
    lines = text.splitlines(keepends=True)
    if not lines or _line_parts(lines[0])[0][:8] != [
            "ID", "shop_type", "level_min", "level_max", "max_total_num",
            "random_num", "price_type", "currency_id"]:
        raise ValueError("Unexpected Shop header")
    seen, changed, result = set(), 0, []
    for line in lines:
        fields, ending = _line_parts(line)
        shop_id = fields[0]
        if (shop_id,) in keys:
            if shop_id in seen:
                raise ValueError("Duplicate tiered exchange shelf")
            seen.add(shop_id)
            source = references[(shop_id,)]
            low, high = _TIERED_SHOPS.get(shop_id, (61, 67))
            desired = ([str(low), str(high)] if shop_id in _POWDER_IDS else
                       ["61", "100"] if shop_id in _GUILD_LAST_IDS else ["1", "100"])
            if len(fields) != len(source) or source[2:4] != [str(low), str(high)] or \
                    fields[2:4] not in ([str(low), str(high)], ["1", "100"], desired) or \
                    any(a != b for index, (a, b) in enumerate(zip(fields, source))
                        if index not in (2, 3)):
                raise ValueError("Unreviewed tiered exchange shelf " + shop_id)
            if fields[2:4] != desired:
                fields[2:4] = desired
                line = ",".join(fields) + ending
                changed += 1
        result.append(line)
    if seen != {key[0] for key in keys}:
        raise ValueError("Missing tiered exchange shelf")
    return "".join(result), changed


def patch_shopstructure_bundle(raw, original_raw):
    return _patch_bundle(raw, original_raw, "ShopStructure", patch_shopstructure_text)


def patch_shopbigset_bundle(raw, original_raw):
    return _patch_bundle(raw, original_raw, "ShopBigSet", patch_shopbigset_text)


def patch_shop_level_bundle(raw, original_raw):
    return _patch_bundle(raw, original_raw, "Shop", patch_shop_level_text)


def exchange_bundle_replacements(read_current, read_original):
    """Return composable bundle bytes; input may already contain Gift patches."""
    output = {}
    for name, patch in (
            (SHOPSTRUCTURE_MEMBER, patch_shopstructure_bundle),
            (SHOPBIGSET_MEMBER, patch_shopbigset_bundle),
            (SHOP_MEMBER, patch_shop_level_bundle)):
        before = read_current(name)
        after = patch(before, read_original(name))
        if after == before:
            raise ValueError("Exchange table already restored: " + name)
        output[name] = after
    return output
