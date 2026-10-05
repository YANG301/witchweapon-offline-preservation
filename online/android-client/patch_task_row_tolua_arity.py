"""Patch only the task-row Lua TextAsset in the reviewed v4/v5 bundle.

No APK is built, installed, or deployed here. A caller replacing this member
must also update its entry in assets/m.assets_list.txt and re-sign the APK.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
EXPECTED_BUNDLE_SHA256 = "8754381499f50e81484d487edf85aad24b938e0d295bc92fa43912af44346eeb"
EXPECTED_TASK_OBJECT_SHA256 = "52c9581ea18f60847d1806743e8ab27e251a7f1b278e2644d2270a4bbd29007b"
EXPECTED_TASK_TEXT_SHA256 = "3b9c2983a620968c9c9f5649f7c98870aa6d119392d246940fac00e5db53787f"
TASK_SOURCE = Path(__file__).resolve().parent / "lua" / "TaskItemPatch-online-v5.lua"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_bundle(raw: bytes) -> bytes:
    if digest(raw) != EXPECTED_BUNDLE_SHA256:
        raise ValueError("Unreviewed task-row Lua bundle")
    updated = TASK_SOURCE.read_text(encoding="utf-8")
    for marker in ("tolua.getmethod(rowType, 'StatusChanged', intType)",
                   "tolua.getmethod(rowType, 'MetaChanged', intType)"):
        if marker not in updated:
            raise ValueError("Task-row typed reflection source changed")

    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    target_id = None
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") != "TaskItemPatch.lua":
            continue
        if target_id is not None:
            raise ValueError("Duplicate task-row TextAsset")
        if before[obj.path_id] != EXPECTED_TASK_OBJECT_SHA256:
            raise ValueError("Unreviewed task-row TextAsset")
        original = tree.get("m_Script")
        if not isinstance(original, str) or digest(original.encode("utf-8")) != EXPECTED_TASK_TEXT_SHA256:
            raise ValueError("Unreviewed task-row Lua text")
        if original.count("tolua.gettypemethod(rowType, 'StatusChanged', 65535)") != 1:
            raise ValueError("Original broken reflection call changed")
        target_id = obj.path_id
        tree["m_Script"] = updated
        obj.save_typetree(tree)
    if target_id is None:
        raise ValueError("Task-row TextAsset missing")

    result = bundle.file.save(packer="original")
    after = UnityPy.load(result)
    changed = {obj.path_id for obj in after.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    if changed != {target_id}:
        raise ValueError("Unexpected Lua bundle object change")
    scripts = [obj.read_typetree().get("m_Script") for obj in after.objects
               if obj.path_id == target_id]
    if scripts != [updated]:
        raise ValueError("Task-row Lua did not round-trip")
    return result
