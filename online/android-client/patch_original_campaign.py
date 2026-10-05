"""Remove author demo routing from original campaign UI and restore stage 1-3.

This leaves chapter availability to the original UI and server progress. It
does not enable missing chapter 16 data or move the demo to a different ID.
"""

import codecs
import hashlib

import UnityPy

from patch_feature_level_gates import _csv_tree


MAZE_UI = "-- Persistent twelve-encounter expedition label; no development command hook."
MAZE_CARRY = "-- Apply the expedition checkpoint once per spawned hero, and capture energy."
SUPPLY = "-- Refresh the original observable models after a committed inventory transaction."
PROBE_START = "-- BEGIN CODEX LOTTERY INPUT PROBE"
PROBE_END = "-- END CODEX LOTTERY INPUT PROBE"
RESTORED = "-- Original campaign UI restored; availability follows server progress.\n"


def text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def extract(raw, name):
    found = [o.read_typetree()["m_Script"] for o in UnityPy.load(raw).objects
             if o.type.name == "TextAsset" and o.read_typetree()["m_Name"] == name]
    if len(found) != 1:
        raise ValueError("Expected one TextAsset: " + name)
    return text(found[0])


def patch_init(script):
    for marker in (MAZE_UI, MAZE_CARRY, SUPPLY, PROBE_START, PROBE_END):
        if script.count(marker) != 1:
            raise ValueError("Unexpected init.lua marker: " + marker)
    start, carry, end = (script.index(x) for x in (MAZE_UI, MAZE_CARRY, SUPPLY))
    if not start < carry < end:
        raise ValueError("Author maze blocks are not contiguous")
    removed = script[start:end]
    if "LOCAL_MAZE_UI" not in removed or "LOCAL_MAZE_CARRY" not in removed or \
            "supported=id==3110001002 or id==3110001003" not in removed:
        raise ValueError("Unexpected author maze block")
    carry_block = script[carry:end]
    if carry_block.count("~=3110001003") != 1:
        raise ValueError("Unexpected checkpoint stage restriction")
    carry_block = carry_block.replace("~=3110001003", "~=3130001026", 1)
    result = script[:start] + RESTORED + carry_block + script[end:]
    probe_start, probe_end = result.index(PROBE_START), result.index(PROBE_END)
    probe_end += len(PROBE_END)
    if probe_start >= probe_end or result[probe_end:].strip():
        raise ValueError("Probe is not an isolated suffix")
    result = result[:probe_start] + result[probe_end:]
    if any(x in result for x in (MAZE_UI, "LOCAL_MAZE_UI", PROBE_START)):
        raise ValueError("Old maze/probe logic remains")
    # Retained production callbacks between the two cuts are byte-for-byte.
    retained = script[end:script.index(PROBE_START)]
    if result[start + len(RESTORED) + len(carry_block):].rstrip() != retained.rstrip():
        raise ValueError("An unrelated production callback changed")
    return result


def patch_detail(script, original):
    marker = "    if tonumber(tostring(instanceId)) == 3110001003 then"
    end_marker = "    PatchModel.SelectLevelDetail_ActivityDataFloor = nil"
    if script.count(marker) != 1 or script.count(end_marker) != 1:
        raise ValueError("Unexpected stage 1-3 detail override")
    start, end = script.index(marker), script.index(end_marker)
    result = script[:start] + script[end:]
    if result != original:
        raise ValueError("Detail patch does not restore original Lua exactly")
    return result


def patch_asset(raw, name, transform):
    env = UnityPy.load(raw)
    before = {o.path_id: hashlib.sha256(o.get_raw_data()).digest() for o in env.objects}
    changed = None
    expected = None
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        if tree["m_Name"] != name:
            continue
        if changed is not None:
            raise ValueError("Duplicate Lua TextAsset")
        was_bytes = isinstance(tree["m_Script"], bytes)
        expected = transform(text(tree["m_Script"]))
        tree["m_Script"] = expected.encode("utf-8") if was_bytes else expected
        obj.save_typetree(tree)
        changed = obj.path_id
    if changed is None:
        raise ValueError("Lua TextAsset missing")
    output = env.file.save(packer="original")
    after = UnityPy.load(output)
    if {o.path_id for o in after.objects} != set(before):
        raise ValueError("Unity object set changed")
    for obj in after.objects:
        if obj.path_id == changed:
            if text(obj.read_typetree()["m_Script"]) != expected:
                raise ValueError("Lua did not round-trip")
        elif hashlib.sha256(obj.get_raw_data()).digest() != before[obj.path_id]:
            raise ValueError("An unrelated Unity object changed")
    return output


def restore_rows(raw, original_raw, name, ids, delimiter=","):
    env, obj, tree, old, bom = _csv_tree(raw, name)
    original = _csv_tree(original_raw, name)[3]
    original_rows = {}
    for line in original.splitlines():
        identity = line.split(delimiter, 1)[0]
        if identity in ids:
            if identity in original_rows:
                raise ValueError("Duplicate original row: " + identity)
            original_rows[identity] = line
    if set(original_rows) != set(ids):
        raise ValueError("Original rows missing")
    seen = set()
    output = []
    for line in old.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        identity = content.split(delimiter, 1)[0]
        if identity in ids:
            if identity in seen:
                raise ValueError("Duplicate target row: " + identity)
            seen.add(identity)
            output.append(original_rows[identity] + line[len(content):])
        else:
            output.append(line)
    if seen != set(ids):
        raise ValueError("Target rows missing")
    updated = "".join(output)
    if updated == old:
        raise ValueError("Expected author-modified rows")
    encoded = (codecs.BOM_UTF8 if bom else b"") + updated.encode("utf-8")
    tree["bytes"] = [b ^ 255 for b in encoded]
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    if _csv_tree(result, name)[3] != updated:
        raise ValueError("Restored table failed round-trip")
    return result
