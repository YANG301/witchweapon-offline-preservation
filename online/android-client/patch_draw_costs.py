"""Restore the six original draw costs/cooldown inside Constant.ab.

This leaves already-reviewed level gate changes and all unrelated constants
unchanged. The APK builder must also update m.assets_list.txt for the bundle.
"""

from __future__ import annotations

import codecs

from patch_feature_level_gates import _constant_tree


DRAW_VALUES = {
    "DRAW_COOLDOWN_GOLD": 600,
    "DRAW_COST_SINGLE_GOLD": 10000,
    "DRAW_COST_MULTI_GOLD_FIVE": 38000,
    "DRAW_COST_MULTI_GOLD_TEN": 90000,
    "DRAW_COST_SINGLE_DIAMOND": 1,
    "DRAW_COST_MULTI_DIAMOND": 10,
}


def patch_text(current: str, original: str) -> str:
    if not current.startswith("ID,value1,value2,value3,value4,channel_group,"):
        raise ValueError("Unexpected current Constant header")
    original_rows = {}
    for line in original.splitlines():
        columns = line.split(",")
        key = columns[0]
        if key in DRAW_VALUES:
            if key in original_rows or len(columns) < 6 or columns[5] != "0" or \
                    columns[3] != str(DRAW_VALUES[key]):
                raise ValueError("Original draw constant differs: " + key)
            original_rows[key] = columns[3]
    if set(original_rows) != set(DRAW_VALUES):
        raise ValueError("Original draw constants are incomplete")

    seen = set()
    updated = []
    for line in current.splitlines(keepends=True):
        payload = line.rstrip("\r\n")
        columns = payload.split(",")
        key = columns[0]
        if key in DRAW_VALUES:
            if key in seen or len(columns) < 6 or columns[5] != "0" or \
                    columns[3] not in ("0", original_rows[key]):
                raise ValueError("Current draw constant differs: " + key)
            seen.add(key)
            columns[3] = original_rows[key]
            line = ",".join(columns) + line[len(payload):]
        updated.append(line)
    if seen != set(DRAW_VALUES):
        raise ValueError("Current draw constants are incomplete")
    result = "".join(updated)
    if len(result.splitlines()) != len(current.splitlines()):
        raise ValueError("Draw constant row count changed")
    return result


def patch_bundle(current: bytes, original: bytes) -> bytes:
    env, item, tree, current_text, bom = _constant_tree(current)
    original_text = _constant_tree(original)[3]
    revised = patch_text(current_text, original_text)
    if revised == current_text:
        return current
    encoded = (codecs.BOM_UTF8 if bom else b"") + revised.encode("utf-8")
    tree["bytes"] = list(byte ^ 255 for byte in encoded)
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, readback, readback_bom = _constant_tree(result)
    if readback != revised or readback_bom != bom:
        raise ValueError("Patched draw Constant did not round-trip")
    return result
