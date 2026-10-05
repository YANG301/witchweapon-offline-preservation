"""Stage RMB icon and 0 Lua logic; the current CN shop prefab does not bind it.

This changes only NewShopPanelPatch.lua in lua_projx_patch.ab. The caller must
also update /lua/lua_projx_patch.ab in assets/m.assets_list.txt after merging
all bundle edits. No Shop.price_type, price, native code or payment SDK is
modified here.

This asset round-trip is not a runtime visual fix by itself. The current
NewShopPanel prefab has no LuaComponent and its prices are drawn by IL2CPP.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
ASSET_NAME = "NewShopPanelPatch.lua"
SOURCE_SHA256 = "bed7dd033a5f2796f8328d1f24ef026506ca3e9353eb11a5da0faa089703f13f"
SCRIPT = Path(__file__).resolve().parent / "lua" / "NewShopPanelPatch-virtual-yuan.lua"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    replacement = SCRIPT.read_text(encoding="utf-8")
    if ("local virtualYuanSets" not in replacement or
            "icon.spriteName = 'Currency_Icon_RMB'" not in replacement or
            "label.text = '0'" not in replacement or
            "BuyShop" in replacement or "PAY_TYPE" in replacement or
            "SetShopPrice" in replacement):
        raise ValueError("Unreviewed virtual-yuan UI script")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [(obj, obj.read_typetree()) for obj in bundle.objects
               if obj.type.name == "TextAsset" and
               obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected exactly one NewShopPanelPatch.lua")
    obj, tree = targets[0]
    source = tree.get("m_Script")
    if not isinstance(source, str):
        raise ValueError("Unexpected Lua asset encoding")
    if source == replacement:
        return raw
    if digest(source.encode("utf-8")) != SOURCE_SHA256:
        raise ValueError("Unreviewed NewShopPanelPatch.lua source")
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
        raise ValueError("Virtual-yuan Lua failed to round-trip")
    return updated
