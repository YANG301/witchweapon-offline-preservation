"""Pinned Lua-only StoryQuest counter fix for the distributed updater APK."""

from __future__ import annotations

import hashlib
from pathlib import Path
import UnityPy


ROOT = Path(__file__).resolve().parent
MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
SOURCE_V5 = ROOT / "lua" / "TaskItemPatch-online-v5.lua"
SOURCE_V6 = ROOT / "lua" / "TaskItemPatch-online-v6.lua"
EXPECTED_BUNDLE = "e22a201278657e66495f1cf9b6db8103418ac7f0f0c305a205589f83f31918de"
EXPECTED_OBJECT = "3d5281dd6ade47e3d930c51724e8f8b4447e4bf74ff0f37e47c8dd19592899d9"
EXPECTED_TEXT = "c7dedd70aea061d7b927d60eaf0df56ed465f5650d6527f6023a2ae8fbafa37c"
OLD_COUNTER = (
    "    if status == -1 then\n"
    "        text = '[FF0000]' .. tostring(meta) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'\n"
)
NEW_COUNTER = (
    "    if status == -1 then\n"
    "        local shown = math.max(0, math.min(meta, target))\n"
    "        text = '[FF0000]' .. tostring(shown) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'\n"
)
OLD_HEADER = "-- QuestInfoView.StatusChanged owns the original 领取/前往/已领取 controls."
NEW_HEADER = (
    "-- StoryQuest can remain locked after its target is met until the previous\n"
    "-- chapter reward is claimed; display no more than the original target."
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    if digest(raw) != EXPECTED_BUNDLE:
        raise ValueError("Distributed Lua bundle is not the reviewed baseline")
    original = SOURCE_V5.read_text(encoding="utf-8")
    updated = SOURCE_V6.read_text(encoding="utf-8")
    if digest(original.encode("utf-8")) != EXPECTED_TEXT:
        raise ValueError("Reviewed v5 Lua source changed")
    if original.count(OLD_COUNTER) != 1 or original.count(OLD_HEADER) != 1:
        raise ValueError("StoryQuest counter anchor changed")
    if updated != original.replace(OLD_HEADER, NEW_HEADER, 1).replace(
        OLD_COUNTER, NEW_COUNTER, 1
    ):
        raise ValueError("v6 Lua has changes unrelated to the StoryQuest counter")

    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    target = None
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") != "TaskItemPatch.lua":
            continue
        if target is not None or before[obj.path_id] != EXPECTED_OBJECT:
            raise ValueError("Unexpected TaskItemPatch TextAsset")
        if tree.get("m_Script") != original:
            raise ValueError("Distributed TaskItemPatch text differs")
        target = obj.path_id
        tree["m_Script"] = updated
        obj.save_typetree(tree)
    if target is None:
        raise ValueError("TaskItemPatch TextAsset missing")

    changed = bundle.file.save(packer="original")
    after = UnityPy.load(changed)
    altered = {obj.path_id for obj in after.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    if altered != {target}:
        raise ValueError("Other Unity objects changed")
    text = next(obj.read_typetree().get("m_Script") for obj in after.objects
                if obj.path_id == target)
    if text != updated:
        raise ValueError("StoryQuest Lua failed to round-trip")
    return changed
