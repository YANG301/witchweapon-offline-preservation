"""Reconnect the original activity-overview links to the restored 7# set.

The v9 APK's UIActivities.lua still asks for retired ShopSet 44000014,
whereas its restored 7# BigSet 47000011 contains ShopSet 44000070. The
existing overview preflight therefore removes that row before rendering.
This edits one existing Lua TextAsset; no prefab, product or payment changes.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_ui.ab"
ASSET_NAME = "UIActivities.lua"
EXPECTED_V9_BUNDLE_SHA256 = "9d84aea2981744acd3649c4fb529a351ba36f7299b3bb8a74026aa9bd7477706"
EXPECTED_V9_OBJECT_SHA256 = "7b344375acbc0be53f573da82b095355858c089a05d09c2fb17d3651784e6d5f"
MARKER = "-- Online restoration: 7# uses restored ShopSet 44000070"


def _once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one source marker, found {count}")
    return source.replace(old, new, 1)


def patch_script(source: str) -> str:
    if MARKER in source:
        raise ValueError("7# overview links already patched")
    source = _once(
        source,
        "local function onlineHasActivityRow(row)",
        """-- Online restoration: 7# uses restored ShopSet 44000070.
-- The preservation server rotates this set at UTC+8 midnight.
local function online7DailyResetSeconds()
    local now = tonumber(tostring(GUtilTime.toUtcTimestamp())) or 0
    local chinaSeconds = now + 28800
    return (math.floor(chinaSeconds / 86400) + 1) * 86400 - chinaSeconds
end

local function onlineHasActivityRow(row)""",
        "daily reset helper",
    )
    source = _once(source,
                   "local shopIDs = {44000001, 44000014, 44000012}",
                   "local shopIDs = {44000001, 44000070, 44000012}",
                   "overview preflight set IDs")
    if source.count("shopsID = 44000014") != 2:
        raise ValueError("Expected exactly two active 7# overview references")
    source = source.replace("shopsID = 44000014", "shopsID = 44000070")
    source = _once(source,
        "t.TimeEXTips.text = ManagerCsv.GetInstance():GetNameStatic('Homepage7#2')",
        "t.TimeEXTips.text = ManagerCsv.GetInstance():GetNameStatic('HomepageShop3')",
        "7# refresh label")
    source = _once(source,
        "t.TimeEXLabel.text = UIActivitiesModel.GetTimeSpanStr(UIActivitiesModel.GetShopSetStopTimeByID( shopsID ) - GUtilTime.toUtcTimestamp())",
        "t.TimeEXLabel.text = UIActivitiesModel.GetTimeSpanStr(online7DailyResetSeconds())",
        "7# daily reset countdown")
    if source.count("shopsID = 44000070") != 2 or \
            source.count("bigShopsID = 47000011") != 1 or \
            source.count("shopsID = 44000012") != 2 or \
            source.count("bigShopsID = 47000012") != 1:
        raise ValueError("Original 7#/airship navigation changed unexpectedly")
    return source


def patch_bundle(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != EXPECTED_V9_BUNDLE_SHA256:
        raise ValueError("Unreviewed v9 activity Lua bundle")
    bundle = UnityPy.load(raw)
    old_objects = {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest()
                   for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected one original activity overview TextAsset")
    target = targets[0]
    if old_objects[target.path_id] != EXPECTED_V9_OBJECT_SHA256:
        raise ValueError("Unreviewed v9 activity overview script")
    tree = target.read_typetree()
    if not isinstance(tree.get("m_Script"), str):
        raise ValueError("Unexpected activity Lua text encoding")
    tree["m_Script"] = patch_script(tree["m_Script"])
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    updated = UnityPy.load(result)
    changed = [obj.path_id for obj in updated.objects if
               hashlib.sha256(obj.get_raw_data()).hexdigest() != old_objects[obj.path_id]]
    if changed != [target.path_id]:
        raise ValueError("Activity patch changed unrelated Unity objects")
    reloaded = next(obj.read_typetree()["m_Script"] for obj in updated.objects
                    if obj.path_id == target.path_id)
    if reloaded != tree["m_Script"]:
        raise ValueError("7# activity Lua failed bundle round-trip")
    return result
