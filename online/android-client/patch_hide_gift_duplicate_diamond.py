"""Hide the archived extra RealRmb counter on the Gift and month-card tabs."""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
ASSET_NAME = "DiamondScrollViewPatch.lua"
SOURCE_SHA256 = "1e99b0caa3e0734d2fdc80c40c80ac7d4ce8eb88c6734a739ccb8080116f9272"
SCRIPT = Path(__file__).resolve().parent / "lua" / "DiamondScrollViewPatch-gift-clean.lua"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    replacement = SCRIPT.read_text(encoding="utf-8")
    if ("setID == '47000002' or setID == '47000016'" not in replacement or
            "price1.obj:SetActive(false)" not in replacement or
            "BuyShop" in replacement or "PAY_TYPE" in replacement):
        raise ValueError("Unreviewed Gift counter script")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [(obj, obj.read_typetree()) for obj in bundle.objects
               if obj.type.name == "TextAsset" and
               obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected exactly one DiamondScrollViewPatch.lua")
    obj, tree = targets[0]
    source = tree.get("m_Script")
    if not isinstance(source, str):
        raise ValueError("Unexpected Lua asset encoding")
    if source == replacement:
        return raw
    if digest(source.encode("utf-8")) != SOURCE_SHA256:
        raise ValueError("Unreviewed DiamondScrollViewPatch.lua source")
    tree["m_Script"] = replacement
    obj.save_typetree(tree)
    updated = bundle.file.save(packer="original")
    check = UnityPy.load(updated)
    changed = {item.path_id for item in check.objects
               if digest(item.get_raw_data()) != before[item.path_id]}
    if changed != {obj.path_id}:
        raise ValueError("Unrelated Unity asset changed")
    restored = next(item.read_typetree() for item in check.objects
                    if item.path_id == obj.path_id)
    if restored.get("m_Name") != ASSET_NAME or restored.get("m_Script") != replacement:
        raise ValueError("Gift counter Lua failed to round-trip")
    return updated
