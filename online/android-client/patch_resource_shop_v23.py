"""Narrow resource-shop layout and navigation repair against the signed v100 APK.

Only ShopBigSet, Shop, init.lua, and the shop prefab FreshView default change.
Every input bundle and row is pinned to the reviewed v100 build.
"""
from __future__ import annotations

import codecs
import hashlib
from pathlib import Path

import UnityPy

from patch_feature_level_gates import _csv_tree


ROOT = Path(__file__).resolve().parent
MEMBERS = {
    "ShopBigSet": "assets/assetbundle/config/clientexel/shopbigset.ab",
    "Shop": "assets/assetbundle/config/clientexel/shop.ab",
    "Lua": "assets/assetbundle/lua/lua.ab",
    "Prefab": "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab",
}
INPUT_SHA = {
    "ShopBigSet": "bd53b71ca884e72c259c430d136866b1b65c2c00df384fa8ad029d297e5b6af0",
    "Shop": "fe312242090397f6eb8d3b8015b81148801eb6b186094f425c98e7535a102f02",
    "Lua": "a6431c1e803c2dfc359f12e64f3e35528cc4b8ea5df90c1c175125d32471404d",
    "Prefab": "909f99e09c56f14be78b29a3ce5c8a0c496f28c8a32aaaf76227bf27cadf4759",
}
INIT_SHA = "e2de31541b58b49d2511724eff2fb7c561f3931ecc8ddad6147600b28641e6cb"
FRESH_GO = -2239071707974191724
OLD_HIDE = """        require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
        local shopType=typeof('NewShopPanelControl')
        local shop=UnityEngine.Object.FindObjectOfType(shopType)
        if shop then
            for _,name in ipairs({'FreshView'}) do
                local widget=tolua.getfield(shopType,name,65535):Get(shop)
                if widget then widget.gameObject:SetActive(false) end
            end
        end
"""
OLD_TICK = """    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextTick then return end
        nextTick = now + 0.1
        local shop = UnityEngine.Object.FindObjectOfType(shopType)
        if shop == nil or not shop.gameObject.activeInHierarchy then
            hiddenCounter = nil
            return
        end
        local setID = tostring(field(shopType, 'currentBigSetID', shop))
        refreshCounter(shop, setID)
        refreshExchange(shop, setID)
        if yuanSets[setID] then
            refreshCards(shop)
            refreshDetail(shop, setID)
        end
    end
"""
NEW_TICK = """    -- Resource, sundry and recharge have no Gift subtabs. Native DrawButtonSub
    -- retains the previous Gift buttons for a frame when switching categories.
    -- Run this small visibility guard every frame, before the slower card pass.
    local hiddenSubTabs = {}
    local subTabPaths = {'btnList/BottomLeft', 'DefultShop/leftBottom'}
    local function refreshNavigation(shop, setID)
        local simple = setID == '47000001' or setID == '47000003' or
                       setID == '47000004'
        for _,path in ipairs(subTabPaths) do
            local node = shop.transform:Find(path)
            if node ~= nil then
                if simple then
                    if node.gameObject.activeSelf then
                        node.gameObject:SetActive(false)
                        hiddenSubTabs[path] = true
                    end
                elseif hiddenSubTabs[path] then
                    node.gameObject:SetActive(true)
                    hiddenSubTabs[path] = nil
                end
            end
        end
        -- Refresh belongs to sundry (and the original star exchange). Do not
        -- let its prefab default or a previous page show it in other categories.
        if setID ~= '47000004' and setID ~= '47000020' then
            local fresh = field(shopType, 'FreshView', shop)
            if fresh ~= nil and fresh.gameObject.activeSelf then
                fresh.gameObject:SetActive(false)
            end
        end
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        local shop = UnityEngine.Object.FindObjectOfType(shopType)
        if shop == nil or not shop.gameObject.activeInHierarchy then
            hiddenCounter = nil
            hiddenSubTabs = {}
            return
        end
        local setID = tostring(field(shopType, 'currentBigSetID', shop))
        if setID == '0' then return end
        refreshNavigation(shop, setID)
        if now < nextTick then return end
        nextTick = now + 0.1
        refreshCounter(shop, setID)
        refreshExchange(shop, setID)
        if yuanSets[setID] then
            refreshCards(shop)
            refreshDetail(shop, setID)
        end
    end
"""


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pinned(name: str, raw: bytes) -> None:
    if digest(raw) != INPUT_SHA[name]:
        raise ValueError("Unreviewed " + name + " v100 bundle")


def _patch_table(raw: bytes, name: str, edit) -> bytes:
    _pinned(name, raw)
    env, obj, tree, source, bom = _csv_tree(raw, name)
    updated = edit(source)
    if updated == source:
        raise ValueError(name + " target row did not change")
    tree["bytes"] = [value ^ 255 for value in
                     ((codecs.BOM_UTF8 if bom else b"") + updated.encode("utf-8"))]
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    _, _, _, roundtrip, new_bom = _csv_tree(result, name)
    if roundtrip != updated or new_bom != bom:
        raise ValueError(name + " bundle round-trip failed")
    return result


def _bigset_text(source: str) -> str:
    lines = source.splitlines(keepends=True)
    fields = lines[0].rstrip("\r\n").split(",")
    if fields[:6] != ["ID", "channel_group", "format", "name", "title", "shop_set1"]:
        raise ValueError("Unreviewed ShopBigSet columns")
    hits = 0
    result = []
    for line in lines:
        payload = line.rstrip("\r\n")
        row = payload.split(",")
        if row[:2] == ["47000003", "25"]:
            if (hits or len(row) != len(fields) or row[2:7] != [
                    "3", "14700000301", "14700000302", "44000028", "44000009"] or
                    any(row[7:])):
                raise ValueError("Unreviewed resource BigSet")
            row[5:7] = ["44000009", ""]
            line = ",".join(row) + line[len(payload):]
            hits += 1
        result.append(line)
    if hits != 1:
        raise ValueError("Resource BigSet missing or duplicated")
    return "".join(result)


def _shop_text(source: str) -> str:
    lines = source.splitlines(keepends=True)
    fields = lines[0].rstrip("\r\n").split(",")
    if fields[:3] != ["ID", "shop_type", "level_min"]:
        raise ValueError("Unreviewed Shop columns")
    hits = 0
    result = []
    for line in lines:
        payload = line.rstrip("\r\n")
        row = payload.split(",")
        if row[0] == "4502500001":
            if hits or len(row) != len(fields) or row[fields.index("price_type")] != "50":
                raise ValueError("Unreviewed diamond resource shelf")
            goods = [row[fields.index("goods" + str(index))] for index in range(1, 9)]
            prices = [row[fields.index("price" + str(index))] for index in range(1, 9)]
            if (goods != ["45030125", "45030124", "45130009", "45130010",
                          "45130011", "45030202", "45030256", "45030267"] or
                    prices != ["26", "260", "5", "45", "420", "100", "40", "30"] or
                    any(row[fields.index("goods" + str(index))]
                        for index in range(9, 61))):
                raise ValueError("Unreviewed original resource products")
            row[fields.index("goods7")] = "45030267"
            row[fields.index("price7")] = "30"
            row[fields.index("goods8")] = ""
            row[fields.index("price8")] = ""
            row[fields.index("num8")] = ""
            line = ",".join(row) + line[len(payload):]
            hits += 1
        result.append(line)
    if hits != 1:
        raise ValueError("Diamond resource shelf missing or duplicated")
    return "".join(result)


def patch_lua(raw: bytes) -> bytes:
    _pinned("Lua", raw)
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset" and
               obj.read_typetree().get("m_Name") == "init.lua"]
    if len(targets) != 1:
        raise ValueError("Expected one init.lua")
    target = targets[0]
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if (not isinstance(source, str) or digest(source.encode("utf-8")) != INIT_SHA or
            source.count(OLD_HIDE) != 1 or source.count(OLD_TICK) != 1):
        raise ValueError("Unreviewed shop init script")
    updated = source.replace(OLD_HIDE, "", 1).replace(OLD_TICK, NEW_TICK, 1)
    if "for _,name in ipairs({'FreshView'}) do" in updated:
        raise ValueError("Legacy one-second refresh hide remains")
    tree["m_Script"] = updated
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    decoded = UnityPy.load(result)
    changed = {obj.path_id for obj in decoded.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    scripts = [obj.read_typetree().get("m_Script") for obj in decoded.objects
               if obj.path_id == target.path_id]
    if changed != {target.path_id} or scripts != [updated]:
        raise ValueError("Shop Lua changed unrelated objects")
    return result


def patch_prefab(raw: bytes) -> bytes:
    _pinned("Prefab", raw)
    bundle = UnityPy.load(raw)
    objects = {obj.path_id: obj for obj in bundle.objects}
    before = {path_id: digest(obj.get_raw_data()) for path_id, obj in objects.items()}
    target = objects.get(FRESH_GO)
    if target is None or target.type.name != "GameObject":
        raise ValueError("Original FreshView GameObject missing")
    tree = target.read_typetree()
    if tree.get("m_Name") != "FreshView" or tree.get("m_IsActive") is not True:
        raise ValueError("Unexpected FreshView prefab state")
    tree["m_IsActive"] = False
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    decoded = UnityPy.load(result)
    changed = {obj.path_id for obj in decoded.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    actual = next(obj.read_typetree() for obj in decoded.objects
                  if obj.path_id == FRESH_GO)
    if changed != {FRESH_GO} or actual.get("m_IsActive") is not False:
        raise ValueError("Shop prefab changed unrelated objects")
    return result


def replacements(read_member):
    return {
        MEMBERS["ShopBigSet"]: _patch_table(
            read_member(MEMBERS["ShopBigSet"]), "ShopBigSet", _bigset_text),
        MEMBERS["Shop"]: _patch_table(
            read_member(MEMBERS["Shop"]), "Shop", _shop_text),
        MEMBERS["Lua"]: patch_lua(read_member(MEMBERS["Lua"])),
        MEMBERS["Prefab"]: patch_prefab(read_member(MEMBERS["Prefab"])),
    }

