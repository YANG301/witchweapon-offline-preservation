"""Add an opt-in shop presentation fix to the active local-test Lua init bundle.

The archived NewShopPanelPatch and DiamondScrollViewPatch text assets are not
bound in the current shop prefab. This patch touches only lua.ab/init.lua and
leaves all server prices, purchase calls and production assets unchanged.
The APK composer must update /lua/lua.ab in m.assets_list.txt after patching.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import UnityPy


HERE = Path(__file__).resolve().parent
MEMBER = "assets/assetbundle/lua/lua.ab"
ASSET_NAME = "init.lua"
SCRIPT = HERE / "lua" / "init-shop-presentation-local.lua"
ORIGINAL_BUNDLE_SHA256 = "365032acb78ff15de55a01e278c4500f1b5ca323e8eb748d7e84db12dd971f19"
ORIGINAL_INIT_SHA256 = "5c5aa1b50d5ba6995736147277b3d95fcde4717ea4ed38a8f22236797c41f9e0"
MARKER = "-- Local test client only. This block is appended to the already-running"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_bundle(raw: bytes, *, enabled: bool = False) -> bytes:
    """Return a reviewed local-test bundle; the default is a bytewise no-op."""
    if not enabled:
        return raw
    block = SCRIPT.read_text(encoding="utf-8")
    if not block.startswith(MARKER) or \
            "UpdateBeat:Add(function()" not in block or \
            "Currency_Icon_RMB" not in block or \
            "BuyShop" in block or "PAY_TYPE" in block:
        raise ValueError("Unreviewed local shop presentation script")

    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects
               if obj.type.name == "TextAsset" and
               obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected one init.lua TextAsset")
    target = targets[0]
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if not isinstance(source, str):
        raise ValueError("Unexpected init.lua encoding")
    if source.endswith("\n" + block) and \
            digest(source[:-len(block)-1].encode("utf-8")) == ORIGINAL_INIT_SHA256:
        return raw
    if digest(raw) != ORIGINAL_BUNDLE_SHA256 or \
            digest(source.encode("utf-8")) != ORIGINAL_INIT_SHA256:
        raise ValueError("Unreviewed input lua.ab/init.lua")

    expected = source + "\n" + block
    tree["m_Script"] = expected
    target.save_typetree(tree)
    updated = bundle.file.save(packer="original")
    restored = UnityPy.load(updated)
    changed = {obj.path_id for obj in restored.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    scripts = [obj.read_typetree().get("m_Script") for obj in restored.objects
               if obj.path_id == target.path_id]
    if changed != {target.path_id} or scripts != [expected]:
        raise ValueError("Local shop Lua changed unrelated assets or failed round trip")
    return updated
