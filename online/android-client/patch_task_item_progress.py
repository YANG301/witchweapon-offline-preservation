"""Patch only TaskItemPatch.lua in the preserved lua_projx_patch.ab bundle."""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


SCRIPT = Path(__file__).resolve().parent / "lua" / "TaskItemPatch-online-v4.lua"
ASSET_NAME = "TaskItemPatch.lua"
ORIGINAL_RAW_SHA256 = "893e0dfb759bf25d3447781c4c31db72c37ae9ace6f72285730ef01708e43f5c"
ORIGINAL_SCRIPT_SHA256 = "c27e1a4b997c97769a51240cc3397066b080e4e118cf8a5cfe29b2b5f8a589e9"
MARKER = "Each task row owns an UpdateBeat listener"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch(raw: bytes) -> bytes:
    replacement = SCRIPT.read_text(encoding="utf-8")
    if MARKER not in replacement or "conditionCount.text ~= ''" in replacement:
        raise ValueError("Unexpected task progress replacement")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha256(obj.get_raw_data()) for obj in bundle.objects}
    targets = []
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") == ASSET_NAME:
            targets.append((obj, tree))
    if len(targets) != 1:
        raise ValueError("Expected one original TaskItemPatch.lua TextAsset")
    obj, tree = targets[0]
    source_script = tree["m_Script"]
    if not isinstance(source_script, str):
        raise ValueError("Unexpected original Lua text encoding")
    if (before[obj.path_id] != ORIGINAL_RAW_SHA256 or
            sha256(source_script.encode("utf-8")) != ORIGINAL_SCRIPT_SHA256):
        raise ValueError("Unreviewed TaskItemPatch.lua source")
    tree["m_Script"] = replacement
    obj.save_typetree(tree)
    updated = bundle.file.save(packer="original")

    check = UnityPy.load(updated)
    changed = []
    found = 0
    for candidate in check.objects:
        if sha256(candidate.get_raw_data()) != before.get(candidate.path_id):
            changed.append(candidate.path_id)
        if candidate.path_id == obj.path_id:
            found += 1
            restored = candidate.read_typetree()
            if restored.get("m_Name") != ASSET_NAME or restored.get("m_Script") != replacement:
                raise ValueError("TaskItemPatch.lua failed to round-trip")
    if found != 1 or changed != [obj.path_id]:
        raise ValueError("Other Unity objects changed in lua_projx_patch.ab")
    return updated
