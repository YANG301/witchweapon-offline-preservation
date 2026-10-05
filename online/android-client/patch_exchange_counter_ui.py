"""Fix the CN exchange counter after the virtual-yuan shop Lua patch.

Only NewShopPanelPatch.lua changes. Call patch_virtual_yuan_display.patch()
first, then patch_bundle() here, then update the APK asset index once.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
ASSET_NAME = "NewShopPanelPatch.lua"
EXPECTED_BUNDLE_SHA256 = "525202a479d2b78ee7366079e26baeaf5ab5b2f1fc9e7cc0d235c9824eb4b758"
EXPECTED_SCRIPT_SHA256 = "10430db8d59aec99f3e6ea66634d7ca2f4178852af7e2f3ca159029e3bd68e47"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Reviewed shop Lua anchor changed: " + old[:60])
    return source.replace(old, new, 1)


def patch_script(source: str) -> str:
    """Preserve virtual ¥0 display while controlling the native buy counter."""
    if digest(source.encode("utf-8")) != EXPECTED_SCRIPT_SHA256:
        raise ValueError("Unreviewed virtual-yuan shop Lua input")
    result = _once(source, "local helper\n", "local helper\nlocal buyWidget\n")
    result = _once(
        result,
        "    enabled = true\n",
        "    enabled = true\n"
        "    -- A reused exchange panel must not show the previous shelf's count.\n"
        "    if tonumber(ManagerCsv.channel_group) == 25 then\n"
        "        local widget = obj.transform:Find('Center/buyWidget')\n"
        "        if widget ~= nil then widget.gameObject:SetActive(false) end\n"
        "    end\n",
    )
    result = _once(
        result,
        "    if channelGroup == 25 then\n"
        "        currentGridField = tolua.getfield(typeof('NewShopPanelControl'), 'currentGrid')\n",
        "    if channelGroup == 25 then\n"
        "        buyWidget = obj.transform:Find('Center/buyWidget').gameObject\n"
        "        currentGridField = tolua.getfield(typeof('NewShopPanelControl'), 'currentGrid')\n",
    )
    result = _once(
        result,
        "    panel = nil\n    helper = nil\nend\n",
        "    panel = nil\n    helper = nil\n    buyWidget = nil\nend\n",
    )
    result = _once(
        result,
        "    local setID = tostring(bigSetField:Get(panel))\n",
        "    local setID = tostring(bigSetField:Get(panel))\n"
        "    if channelGroup == 25 and buyWidget ~= nil then\n"
        "        -- Original Shop.max_total_num: guild 4, maze 6. The native\n"
        "        -- buyCount label continues to receive the server's live value.\n"
        "        local limit = nil\n"
        "        if setID == '47000006' then limit = 4 end\n"
        "        if setID == '47000023' then limit = 6 end\n"
        "        local count = buyWidget.transform:Find('buyCount'):GetComponent('UILabel')\n"
        "        local visible = limit ~= nil and count ~= nil and\n"
        "            string.match(count.text, '/%s*' .. tostring(limit) .. '%s*$') ~= nil\n"
        "        if buyWidget.activeSelf ~= visible then\n"
        "            buyWidget:SetActive(visible)\n"
        "        end\n"
        "    end\n",
    )
    result = _once(
        result,
        "    if channelGroup == 60 then\n"
        "        local showHelp = setID == '47000019' or setID == '47000020'\n",
        "    -- In the shop card, Mid/Num is GoodInfo.Num (remaining stock).\n"
        "    -- The separate ShopItemInfo slider/buyNumber controls purchase\n"
        "    -- quantity, so this affects no reward or buy-dialog number.\n"
        "    if channelGroup == 25 and setID == '47000008' and\n"
        "            currentGridField ~= nil then\n"
        "        local grid = currentGridField:Get(panel)\n"
        "        if grid ~= nil then\n"
        "            local transform = grid.transform\n"
        "            for index = 0, transform.childCount - 1 do\n"
        "                local stock = transform:GetChild(index):Find('Mid/Num')\n"
        "                if stock ~= nil and stock.gameObject.activeSelf then\n"
        "                    stock.gameObject:SetActive(false)\n"
        "                end\n"
        "            end\n"
        "        end\n"
        "    end\n"
        "    if channelGroup == 60 then\n"
        "        local showHelp = setID == '47000019' or setID == '47000020'\n",
    )
    return result


def patch_bundle(raw: bytes) -> bytes:
    if digest(raw) != EXPECTED_BUNDLE_SHA256:
        raise ValueError("Unreviewed virtual-yuan shop Lua bundle")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1:
        raise ValueError("Expected one original shop Lua TextAsset")
    target = targets[0]
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if not isinstance(source, str):
        raise ValueError("Unexpected shop Lua text encoding")
    changed_script = patch_script(source)
    tree["m_Script"] = changed_script
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    check = UnityPy.load(result)
    changed = {obj.path_id for obj in check.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    scripts = [obj.read_typetree().get("m_Script") for obj in check.objects
               if obj.path_id == target.path_id]
    if changed != {target.path_id} or scripts != [changed_script]:
        raise ValueError("Shop Lua bundle changed unrelated objects or failed round trip")
    return result
