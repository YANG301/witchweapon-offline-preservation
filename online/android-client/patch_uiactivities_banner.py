"""Retarget the original UIActivities carousel to three restored features.

The source is the original Unity 2017 Lua TextAsset. This patches only that
TextAsset within lua_projx_ui.ab; the caller must update the APK asset list and
sign a new APK. Historical activity adverts are deliberately never displayed.
"""

from __future__ import annotations

import hashlib

import UnityPy


ASSET_NAME = "UIActivities.lua"
MAIN_ASSET_NAME = "MainScenePanelAdd.lua"
ORIGINAL_TEXT_ASSET_SHA256 = "1a0417b852b99313bc51c316ab4f7566862a5651341aaebddbefe243a7bb5a4e"
ORIGINAL_MAIN_ASSET_SHA256 = "471f211c2fb84a95d56b9d93da45985c2176a38483587571ae2c257f2a4cd24d"
MARKER = "-- Online restoration: neutral original carousel assets"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one source marker, found {count}")
    return source.replace(old, new, 1)


def patch_script(source: str) -> str:
    if MARKER in source:
        raise ValueError("The carousel patch is already present")

    source = replace_once(
        source,
        "local ADTemplet = {}\n",
        """local ADTemplet = {}
-- Online restoration: neutral original carousel assets and current destinations.
local OnlineADCaption = {
    [27] = "新丰洲公告",
    [28] = "邮件信箱",
    [44] = "每日签到",
}
local OnlineADTint = {
    [27] = {0.85, 1.00, 1.00},
    [28] = {1.00, 0.87, 0.94},
    [44] = {0.91, 1.00, 0.84},
}
-- The restored server does not yet provide every historical shop/draw row.
-- The original overview creates all prefab rows before reading their data;
-- a missing shop set aborts init before the native carousel is even loaded.
local function onlineCanShowShopSetByID(shopID)
    local ok, visible = pcall(UIActivitiesModel.CanShowShopSetByID, shopID)
    return ok and visible or false
end

local function onlineHasActivityRow(row)
    if row.type == 'Power' then
        return UIActivitiesModel.GetPowerInfo() ~= nil
    elseif row.type == 'Draw' then
        local drawType = row.index == 1 and WaterBell.ProjX.View.Panel.LuckDrawTypes.Gold
            or WaterBell.ProjX.View.Panel.LuckDrawTypes.Diamond
        local ok, canFree, isFree, freeTime, count, maximum =
            pcall(UIActivitiesModel.GetDrawSomeInfoByType, drawType)
        return ok and type(count) == 'number' and type(maximum) == 'number'
    elseif row.type == 'Shop' then
        local shopIDs = {44000001, 44000014, 44000012}
        local shopID = shopIDs[row.index]
        local ok = pcall(UIActivitiesModel.CanShowShopSetByID, shopID)
        if not ok then return false end
        local timeOK, timeValue
        if row.index == 1 then
            timeOK, timeValue = pcall(UIActivitiesModel.GetOneShopUpdateTimeByID, shopID)
        else
            timeOK, timeValue = pcall(UIActivitiesModel.GetShopSetStopTimeByID, shopID)
        end
        return timeOK and type(timeValue) == 'number'
    elseif row.type == 'Task' then
        local ok, done, total = pcall(UIActivitiesModel.GetTaskSomeCount)
        return ok and done ~= nil and total ~= nil
    end
    return true
end
""",
        "slide definitions",
    )

    source = replace_once(
        source,
        "local function showADAutoAnimation( ... )",
        """local function updateOnlineADVisual()
    local card = ADTemplet[curADIndex]
    if not card or not tAD then return end
    local tint = OnlineADTint[card.id] or {1, 1, 1}
    tAD.Texture.color = Color.New(tint[1], tint[2], tint[3], 1)
    tAD.TimeLabel.text = card.caption or ""
end

local function showADAutoAnimation( ... )""",
        "visual update function",
    )
    source = replace_once(
        source,
        "tAD.Texture.mainTexture = ADTemplet[curADIndex].asset\n\t--tAD.TimeLabel.text",
        "tAD.Texture.mainTexture = ADTemplet[curADIndex].asset\n\tupdateOnlineADVisual()\n\t--tAD.TimeLabel.text",
        "automatic slide visual update",
    )
    source = replace_once(
        source,
        "tAD.Texture.mainTexture = ADTemplet[curIndex].asset\n\tcurADIndex = curIndex\n\tupdateADPoint()",
        "tAD.Texture.mainTexture = ADTemplet[curIndex].asset\n\tcurADIndex = curIndex\n\tupdateOnlineADVisual()\n\tupdateADPoint()",
        "arrow slide visual update",
    )
    source = replace_once(
        source,
        "\tlocal data = ADTemplet[curADIndex]\n\tlocal typeid = data.typeid",
        """    local data = ADTemplet[curADIndex]
    if data.id == 27 then
        GUtilUISuper.show(typeof(UIAnnouncement), "UIAnnouncement", nil, true)
        return
    elseif data.id == 28 then
        UISceneManager.getInstance():GotoBackLua(
            UISceneState.New(UISceneID.MAIN_SCENE_NEW:ToInt()),
            UISceneState.New(UISceneID.MAIL_SCENE:ToInt()), 'UIActivities.onBack')
        return
    elseif data.id == 44 then
        local sign = UIActivitiesModel.GetServerDataByID(26)
        if sign then UIActivitiesReward:show(1, sign) end
        return
    end
    local typeid = data.typeid""",
        "carousel destinations",
    )
    start = source.index("\tADTemplet = {}\n", source.index("local function loadAD( ... )"))
    end = source.index("\n\ttable.sort(ADTemplet", start)
    source = source[:start] + """    ADTemplet = {}
    local neutral = AssetsManager.LoadTextureForLua("UI/UIImage/ActivityImg/AD/default")
    if neutral then
        for i, v in ipairs(data) do
            -- Keep the original arrows, animation and pagination, but show only
            -- the server's three current cards. Old CSV adverts have expired.
            if v.type == ActivityModel.ActivityType.AD.typeid and OnlineADCaption[v.id] then
                table.insert(ADTemplet, {
                    name = "default",
                    asset = neutral,
                    starttime = v.starttime,
                    endtime = v.endtime,
                    id = v.id,
                    caption = OnlineADCaption[v.id],
                    typeid = 0,
                    parameter = {},
                })
            end
        end
    end
""" + source[end:]
    source = replace_once(
        source,
        "\tt.TimeLabel = t.Self:Find('TimeLabel'):GetComponent('UILabel')",
        """    t.TimeLabel = t.Self:Find('TimeLabel'):GetComponent('UILabel')
    t.TimeLabel.width = 620
    t.TimeLabel.height = 54
    t.TimeLabel.fontSize = 36
    t.TimeLabel.transform.localPosition = Vector3.New(0, -80, 0)""",
        "original caption label",
    )
    source = replace_once(
        source,
        "tAD.Texture.mainTexture = ADTemplet[curADIndex].asset\n\n\tshowADAutoAnimation()",
        "tAD.Texture.mainTexture = ADTemplet[curADIndex].asset\n\tupdateOnlineADVisual()\n\n\tshowADAutoAnimation()",
        "initial slide visual update",
    )
    source = replace_once(
        source,
        "local lockLevel = ManagerCsv.GetInstance():GetConstant('ACTIVITY_MAINPAGE_MISSION_LEVEL').value3",
        "local lockLevel = 1 -- Restored daily tasks are available from the first level.",
        "daily task visibility gate",
    )
    shop_call = "local CanShow = UIActivitiesModel.CanShowShopSetByID(shopsID)"
    if source.count(shop_call) != 2:
        raise ValueError("Expected both original shop visibility call sites")
    source = source.replace(shop_call,
                            "local CanShow = onlineCanShowShopSetByID(shopsID)")
    source = replace_once(
        source,
        "\tlocal delIndex\n\tlocal level =",
        """    -- Keep original rows whose backing state is ready; empty historical shop
    -- records must not leave the cloned prefab text in place or block loadAD().
    for i = #HandAccount, 1, -1 do
        if not onlineHasActivityRow(HandAccount[i]) then
            table.remove(HandAccount, i)
        end
    end

    local delIndex
    local level =""",
        "unavailable overview row filter",
    )
    for caption in ("新丰洲公告", "邮件信箱", "每日签到"):
        if source.count(caption) != 1:
            raise ValueError("Expected one carousel caption: " + caption)
    return source


def patch_main_script(source: str) -> str:
    source = replace_once(
        source,
        "function MainScenePanelAdd.showOnNewDay( ... )\n\tdo return end\n",
        "function MainScenePanelAdd.showOnNewDay( ... )\n\t-- Open the original overview once per role and local UTC+8 day.\n",
        "disabled first-login activity overview",
    )
    return replace_once(
        source,
        "math.floor(Utils.getSeverTime() / 86400)",
        "math.floor((Utils.getSeverTime() + 28800) / 86400)",
        "Asia/Shanghai daily activity opening gate",
    )


def patch(raw: bytes) -> bytes:
    bundle = UnityPy.load(raw)
    before = {}
    targets = {}
    for obj in bundle.objects:
        before[obj.path_id] = hashlib.sha256(obj.get_raw_data()).hexdigest()
        if obj.type.name == "TextAsset":
            tree = obj.read_typetree()
            if tree.get("m_Name") in (ASSET_NAME, MAIN_ASSET_NAME):
                if tree["m_Name"] in targets:
                    raise ValueError("Duplicate source TextAsset: " + tree["m_Name"])
                targets[tree["m_Name"]] = obj
    if (set(targets) != {ASSET_NAME, MAIN_ASSET_NAME}
            or before[targets[ASSET_NAME].path_id] != ORIGINAL_TEXT_ASSET_SHA256
            or before[targets[MAIN_ASSET_NAME].path_id] != ORIGINAL_MAIN_ASSET_SHA256):
        raise ValueError("Original carousel or daily gate TextAsset differs from reviewed source")

    for name, update in ((ASSET_NAME, patch_script), (MAIN_ASSET_NAME, patch_main_script)):
        obj = targets[name]
        tree = obj.read_typetree()
        script = tree["m_Script"]
        if not isinstance(script, str):
            raise ValueError("Unexpected Lua script encoding")
        tree["m_Script"] = update(script)
        obj.save_typetree(tree)
    updated = bundle.file.save(packer="original")

    check = UnityPy.load(updated)
    changed = []
    for obj in check.objects:
        digest = hashlib.sha256(obj.get_raw_data()).hexdigest()
        if digest != before.get(obj.path_id):
            changed.append(obj.path_id)
        if obj.path_id == targets[ASSET_NAME].path_id:
            reloaded = obj.read_typetree()["m_Script"]
            for caption in (MARKER, "新丰洲公告", "邮件信箱", "每日签到"):
                if caption not in reloaded:
                    raise ValueError("Patched Lua did not round-trip: " + caption)
        elif obj.path_id == targets[MAIN_ASSET_NAME].path_id:
            reloaded = obj.read_typetree()["m_Script"]
            if (reloaded.count("math.floor((Utils.getSeverTime() + 28800) / 86400)") != 1
                    or "math.floor(Utils.getSeverTime() / 86400)" in reloaded
                    or "do return end" in reloaded):
                raise ValueError("Daily gate did not round-trip")
    if set(changed) != {obj.path_id for obj in targets.values()} or len(changed) != 2:
        raise ValueError("Unexpected AssetBundle objects changed: " + str(changed))
    return updated
