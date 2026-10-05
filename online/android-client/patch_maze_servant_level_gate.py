"""Let owned level-one witches appear in the original Barrier Maze team editor.

Only CORE_INSTANCE_SERVANT_MIN_LEVEL in the existing Constant Unity bundle is
changed. The editor itself still enumerates the account's owned servants and
retains its original twelve-member team limit and energy display.
"""

from __future__ import annotations

import codecs
import copy

from patch_feature_level_gates import _constant_tree


ROW_BEFORE = "CORE_INSTANCE_SERVANT_MIN_LEVEL,,,20,,0,,,,,,"
ROW_AFTER = "CORE_INSTANCE_SERVANT_MIN_LEVEL,,,1,,0,,,,,,"


def patch_constant_text(text: str) -> tuple[str, int]:
    lines = text.splitlines(keepends=True)
    matching = [index for index, line in enumerate(lines)
                if line.split(",", 1)[0] == "CORE_INSTANCE_SERVANT_MIN_LEVEL"]
    if len(matching) != 1:
        raise ValueError("Expected exactly one maze servant level gate")
    index = matching[0]
    line = lines[index]
    old = line.rstrip("\r\n")
    if old == ROW_AFTER:
        return text, 0
    if old != ROW_BEFORE:
        raise ValueError("Unexpected maze servant level gate row")
    lines[index] = ROW_AFTER + line[len(old):]
    updated = "".join(lines)
    if len(updated.splitlines()) != len(text.splitlines()):
        raise ValueError("Constant row count changed")
    return updated, 1


def patch_bundle(raw: bytes) -> bytes:
    env, item, tree, original, has_bom = _constant_tree(raw)
    updated, changed = patch_constant_text(original)
    if changed == 0:
        return raw
    other_fields = copy.deepcopy(tree)
    other_fields.pop("bytes")
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + updated.encode("utf-8")
    tree["bytes"] = list(byte ^ 255 for byte in encoded)
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, readback, decoded, result_bom = _constant_tree(result)
    readback.pop("bytes")
    if decoded != updated or result_bom != has_bom or readback != other_fields:
        raise ValueError("Maze level gate bundle did not preserve other asset fields")
    return result


__all__ = ["ROW_BEFORE", "ROW_AFTER", "patch_constant_text", "patch_bundle"]
