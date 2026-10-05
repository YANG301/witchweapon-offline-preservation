"""Remove reviewed feature-entry levels, leaving gameplay/ownership checks intact.

This complements patch_feature_level_gates (Constant/InstanceSet) and the
separate 235-row mainline unlock patch.  It never modifies mainline rows,
resource costs, daily quotas, required units, guild permissions, story
ownership, or the linked InstanceSet front_instance/instance_set_next pair.
Lowering a UI entry level is not an assertion that a mode is implemented by
the server; server availability remains authoritative.
"""

from __future__ import annotations

import codecs
import hashlib

from patch_feature_level_gates import _csv_tree
from patch_chapter_level_up_duplicates import (
    _PROFILES as _ELF_PROFILES, _file_offset, _load_segments,
)


# ID -> (original type, original set, original entry level).  These 170
# non-mainline rows are the complete level>1 set in the archived Instance CSV.
INSTANCE_GATES = {}


def _group(start, type_, set_, levels):
    for offset, level in enumerate(levels):
        INSTANCE_GATES[str(start + offset)] = (str(type_), str(set_), str(level))


for _index in range(1, 5):
    _group(3120000001 + _index * 1000, 5, 3020000 + _index,
           (20, 26, 33, 40, 47, 54, 61))
for _index in (5, 6):
    _group(3120000001 + _index * 1000, 6, 3020000 + _index,
           (10, 20, 30, 40, 50, 60))
_group(3120007001, 14, 3020007, (25, 35, 45, 55, 65))
for _index in range(8, 13):
    _group(3120000001 + _index * 1000, 15, 3020000 + _index,
           (30, 40, 45, 50, 55, 60, 65))
_group(3130001001, 1, 3030001, (27,) * 34)
_group(3130001035, 9, 3030001, (27,) * 16)
for _index in range(1, 4):
    _group(3160000001 + _index * 1000, 19, 3060000 + _index, (30,) * 11)
_group(3190002001, 15, 3090002, (30, 40, 45, 50, 55, 60, 65))
assert len(INSTANCE_GATES) == 170

# Mainline sets 3010001..3010016 deliberately belong to the other patch.
INSTANCE_SET_GATES = {
    **{str(3020000 + i): ("2", "20") for i in range(1, 5)},
    **{str(3020000 + i): ("2", "10") for i in range(5, 8)},
    "3030001": ("3", "27"),
    **{str(3060000 + i): ("6", "30") for i in range(1, 4)},
}


def _patch_rows(text, table):
    """Change one reviewed numeric column while retaining every other byte."""
    lines = text.splitlines(keepends=True)
    if not lines:
        raise ValueError("Empty feature table")
    header = lines[0].rstrip("\r\n").split(",")
    if table == "Instance":
        required = ("ID", "instance_type", "instance_set_attached",
                    "instance_enter_level")
        expected = INSTANCE_GATES
    elif table == "InstanceSet":
        required = ("ID", "instance_set_type", "instance_set_enter_level")
        expected = INSTANCE_SET_GATES
    else:
        raise ValueError("Unsupported feature table")
    if any(header.count(name) != 1 for name in required):
        raise ValueError("Unexpected " + table + " header")
    indexes = tuple(header.index(name) for name in required)
    seen = set()
    changed = 0
    output = []
    for line in lines:
        payload = line.rstrip("\r\n")
        values = payload.split(",")
        identifier = values[0]
        if identifier not in expected:
            output.append(line)
            continue
        if identifier in seen or len(values) != len(header):
            raise ValueError("Duplicate/malformed feature row: " + identifier)
        seen.add(identifier)
        original = expected[identifier]
        actual = tuple(values[index] for index in indexes[1:])
        if actual[:-1] != original[:-1] or actual[-1] not in (original[-1], "1"):
            raise ValueError("Unexpected feature gate: " + identifier)
        if actual[-1] != "1":
            values[indexes[-1]] = "1"
            changed += 1
            output.append(",".join(values) + line[len(payload):])
        else:
            output.append(line)
    if seen != set(expected):
        raise ValueError("Missing reviewed feature gates: " +
                         ",".join(sorted(set(expected) - seen)))
    return "".join(output), changed


def patch_instance_text(text):
    return _patch_rows(text, "Instance")


def patch_instance_set_text(text):
    return _patch_rows(text, "InstanceSet")


def _patch_bundle(raw, name):
    env, obj, tree, original, has_bom = _csv_tree(raw, name)
    patched, changed = _patch_rows(original, name)
    if not changed:
        return raw
    encoded = (codecs.BOM_UTF8 if has_bom else b"") + patched.encode("utf-8")
    tree["bytes"] = [value ^ 0xff for value in encoded]
    obj.save_typetree(tree)
    output = env.file.save(packer="original")
    _, _, _, actual, bom_after = _csv_tree(output, name)
    if actual != patched or bom_after != has_bom:
        raise ValueError("Feature CSV did not round-trip")
    return output


def patch_instance_bundle(raw):
    return _patch_bundle(raw, "Instance")


def patch_instance_set_bundle(raw):
    return _patch_bundle(raw, "InstanceSet")


# MainScenePanel.CanOpenDaily_1 / CanOpenDaily_3 contain *only* player-level
# reads and a comparison against 9 / 24. Daily_2 already returns true.
# Each tuple: method, RVA, size, patched instruction RVA, original SHA-256.
# ARM32 identity was cross-checked by the unique adjacent sequence
# Daily_1(200 bytes), Daily_2(mov r0,1; bx lr), Daily_3(200 bytes), including
# identical GetInstance/GetPlayer/get_Level calls and comparisons 9 / 24.
NATIVE_GATES = {
    "arm64-v8a": (
        ("CanOpenDaily_1", 0x3BDFDFC, 160, 0x3BDFE90,
         "1b5a20ea22381194b5985d797fc3ab885ae437d9d1eebc0896a8e3e22e218747"),
        ("CanOpenDaily_3", 0x3BDFEA4, 160, 0x3BDFF38,
         "168b0fddae752062c7455e879fe60465e5fd70b5a347693e8e689f99badb0321"),
    ),
    "armeabi-v7a": (
        ("CanOpenDaily_1", 0x36C4F9C, 200, 0x36C5048,
         "46ca594c7b28427a734866f19802474e4d738eed9afbc6449c1a80265116b3f4"),
        ("CanOpenDaily_3", 0x36C506C, 200, 0x36C5118,
         "49faaddd90d2789ea6b57a33c1d0d30d0ab6a0a195400c77ea2f9022f2cbe99f"),
    ),
}

NATIVE_INSTRUCTIONS = {
    # cset w0,gt -> mov w0,#1
    "arm64-v8a": (bytes.fromhex("e0d79f1a"), bytes.fromhex("20008052")),
    # movwgt r4,#1 -> movw r4,#1 (following mov r0,r4 remains original)
    "armeabi-v7a": (bytes.fromhex("014000c3"), bytes.fromhex("014000e3")),
}


def patch_native_entry_gates(raw, abi):
    """Return (ELF bytes, changed gate count); reject altered method bodies.

    The SHA check normalizes our one changed instruction so a repeat build
    is a no-op. No other method is rewritten, including server IsOpen,
    resource/daily-count checks, battle results, and level-up dictionary fix.
    """
    if abi not in NATIVE_GATES:
        raise ValueError("Unsupported feature ABI: " + abi)
    segments = _load_segments(raw, _ELF_PROFILES[abi])
    old, new = NATIVE_INSTRUCTIONS[abi]
    edits = []
    for name, address, size, patch_address, expected_sha in NATIVE_GATES[abi]:
        start = _file_offset(segments, address)
        end = _file_offset(segments, address + size - 4) + 4
        patch = _file_offset(segments, patch_address)
        if end - start != size:
            raise ValueError("Noncontiguous native entry method: " + name)
        instruction = raw[patch:patch + 4]
        if instruction not in (old, new):
            raise ValueError("Unexpected native entry instruction: " + name)
        normalized = bytearray(raw[start:end])
        normalized[patch - start:patch - start + 4] = old
        if hashlib.sha256(normalized).hexdigest() != expected_sha:
            raise ValueError("Unexpected native entry method: " + name)
        if instruction == old:
            edits.append(patch)
    if not edits:
        return raw, 0
    output = bytearray(raw)
    for patch in edits:
        output[patch:patch + 4] = new
    return bytes(output), len(edits)
