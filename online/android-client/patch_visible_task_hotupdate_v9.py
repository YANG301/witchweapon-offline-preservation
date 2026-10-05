"""Mark the original task counter so a downloaded Lua update is visible."""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
ASSET_NAME = "TaskItemPatch.lua"
BASE_BUNDLE_SHA256 = "88882155712a5338c97e8e7a1f94c34afbd0a3ee317ea4a0ec80771e6d43c7ad"
BASE_OBJECT_SHA256 = "b4b55cdab950f582fc630ef1b68c3ddaac9274df142c09f58e6f996f0fd28cbd"
BASE_SCRIPT_SHA256 = "e98e26f4ac5a616f40b0eeb02ceb4e5188993718cfa1d7d419b2e95d4f98c434"
OLD = "    if row.label.text ~= text then row.label.text = text end"
NEW = "    text = '[80E0FF]热更9[-] ' .. text\n" + OLD


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    if sha(raw) != BASE_BUNDLE_SHA256:
        raise ValueError("Lua AssetBundle differs from signed sequence 8")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = [
        obj for obj in bundle.objects
        if obj.type.name == "TextAsset"
        and obj.read_typetree().get("m_Name") == ASSET_NAME
    ]
    if len(targets) != 1:
        raise ValueError("Task counter TextAsset inventory changed")
    target = targets[0]
    if before[target.path_id] != BASE_OBJECT_SHA256:
        raise ValueError("Task counter TextAsset differs from reviewed baseline")
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if not isinstance(source, str) or sha(source.encode("utf-8")) != BASE_SCRIPT_SHA256:
        raise ValueError("Task counter Lua source differs from reviewed baseline")
    if source.count(OLD) != 1:
        raise ValueError("Task counter display anchor is ambiguous")
    changed_source = source.replace(OLD, NEW, 1)
    tree["m_Script"] = changed_source
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    checked = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in checked.objects}
    if set(before) != set(after) or {
        path_id for path_id in before if before[path_id] != after[path_id]
    } != {target.path_id}:
        raise ValueError("Task marker patch changed unrelated Unity objects")
    scripts = [
        obj.read_typetree().get("m_Script") for obj in checked.objects
        if obj.path_id == target.path_id
    ]
    if scripts != [changed_source]:
        raise ValueError("Task marker Lua did not round-trip")
    return result
