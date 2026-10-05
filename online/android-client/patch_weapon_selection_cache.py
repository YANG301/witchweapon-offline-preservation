"""Persist validated weapon changes before the original party refresh.

The running Android client is native IL2CPP. This appends one Lua observer to
the active init TextAsset; it does not replace the native validation or alter
the settlement assets. Callers composing an APK must update /lua/lua.ab in the
resource index. No device, service, release manifest or user save is touched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "lua" / "init-weapon-selection-cache.lua"
MEMBER = "assets/assetbundle/lua/lua.ab"
LOGICAL_PATH = "/lua/lua.ab"
ASSET_NAME = "init.lua"
MARKER = "-- WWR weapon selection cache persistence v1."


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_init(source: str) -> str:
    block = SCRIPT.read_text(encoding="utf-8")
    if not block.startswith(MARKER + "\n"):
        raise ValueError("Weapon observer marker is missing")
    if MARKER in source:
        if source.endswith("\n" + block) and source.count(MARKER) == 1:
            return source
        raise ValueError("A different weapon-cache observer is already present")
    return source + "\n" + block


def patch_bundle(raw: bytes) -> bytes:
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected exactly one active init.lua TextAsset")
    target = targets[0]
    tree = target.read_typetree()
    original = tree.get("m_Script")
    is_bytes = isinstance(original, bytes)
    if is_bytes:
        source = original.decode("utf-8")
    elif isinstance(original, str):
        source = original
    else:
        raise ValueError("Unexpected init.lua encoding")
    expected = patch_init(source)
    if expected == source:
        return raw
    tree["m_Script"] = expected.encode("utf-8") if is_bytes else expected
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    reopened = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in reopened.objects}
    if set(before) != set(after) or {
            pid for pid in before if before[pid] != after[pid]} != {target.path_id}:
        raise ValueError("Weapon observer modified unrelated Unity objects")
    restored = next(obj for obj in reopened.objects if obj.path_id == target.path_id)
    value = restored.read_typetree()["m_Script"]
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    if value != expected or not value.startswith(source):
        raise ValueError("Weapon observer did not round-trip or lost existing fixes")
    return result
