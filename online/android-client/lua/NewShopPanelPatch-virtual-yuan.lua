local this = {}

local panel
local helper
local bigSetField
local currentGridField
local detailField
local detailItemField
local detailIconField
local detailValueField
local channelGroup
local enabled = false
local beatRegistered = false

-- Presentation only. The Shop table keeps price_type=50 and price=0, so
-- the original in-game BuyResult path remains the only purchase path.
local virtualYuanSets = {
    ['47000001'] = true, -- virtual recharge
    ['47000002'] = true, -- selected gift boxes
    ['47000016'] = true, -- monthly cards
}

local virtualYuanGoods = {
    ['45030285'] = true, ['45030435'] = true, ['45030619'] = true,
    ['45030434'] = true, ['45030301'] = true,
    ['45030620'] = true, ['45030621'] = true,
    ['45820001'] = true, ['45820006'] = true,
    ['45990010'] = true, ['45990011'] = true, ['45990012'] = true,
    ['45990013'] = true, ['45990014'] = true, ['45990015'] = true,
}

local function showYuan(icon, label)
    -- Currency_Icon_RMB is in the same NewResBar atlas as the source
    -- p1Icon/goldIcon1 sprites; this changes only their appearance.
    if icon ~= nil then
        if icon.spriteName ~= 'Currency_Icon_RMB' then
            icon.spriteName = 'Currency_Icon_RMB'
        end
        if not icon.gameObject.activeSelf then
            icon.gameObject:SetActive(true)
        end
    end
    if label ~= nil and label.text ~= '0' then
        label.text = '0'
    end
end

local function showVirtualPrices()
    local grid = currentGridField:Get(panel)
    if grid ~= nil then
        local transform = grid.transform
        for index = 0, transform.childCount - 1 do
            local item = transform:GetChild(index)
            local icon = item:Find('Mid/p1Icon')
            local value = item:Find('Mid/p1Val')
            if icon ~= nil and value ~= nil then
                showYuan(icon:GetComponent('UISprite'), value:GetComponent('UILabel'))
            end
        end
    end

    local detail = detailField:Get(panel)
    if detail ~= nil and detail.gameObject.activeInHierarchy then
        local goodID = tostring(detailItemField:Get(detail))
        if virtualYuanGoods[goodID] then
            local icon = detailIconField:Get(detail)
            local label = detailValueField:Get(detail)
            showYuan(icon, label)
        end
    end
end

function this:OnEnable(obj)
    enabled = true
    -- Preserve the archived star-shop availability rule.
    local function hideExpiredTabs()
        if Utils.getSeverTime() < 1570032000 then
            local bottomLeft = obj.transform:Find('btnList/BottomLeft')
            for index = 0, bottomLeft.childCount - 1 do
                local child = bottomLeft:GetChild(index)
                if child.name == 'menuSub_47000027' or child.name == 'menuSub_47000029' then
                    child.gameObject:SetActive(false)
                end
            end
        end
    end
    Timer.New(hideExpiredTabs, 0.1, 1, true):Start()
end

function this:Start(obj)
    helper = obj.transform:Find('Helper').gameObject
    helper:SetActive(false)
    channelGroup = tonumber(ManagerCsv.channel_group)
    if channelGroup ~= 60 and channelGroup ~= 25 then
        return
    end

    panel = obj:GetComponent('NewShopPanelControl')
    require 'tolua.reflection'
    tolua.loadassembly('Assembly-CSharp')
    bigSetField = tolua.getfield(typeof('NewShopPanelControl'), 'currentBigSetID')

    if channelGroup == 25 then
        currentGridField = tolua.getfield(typeof('NewShopPanelControl'), 'currentGrid')
        detailField = tolua.getfield(typeof('NewShopPanelControl'), 'ShopItemInfoView')
        detailItemField = tolua.getfield(typeof('ShopItemInfo'), 'itemId')
        detailIconField = tolua.getfield(typeof('ShopItemInfo'), 'goldIcon1')
        detailValueField = tolua.getfield(typeof('ShopItemInfo'), 'goldValue1')
    else
        local names = ManagerCsv.GetInstance()
        local description = names:GetNameStatic('starshop_0') .. '\n' ..
            names:GetNameStatic('starshop_1') .. '\n' ..
            names:GetNameStatic('starshop_2')
        UIEventListener.Get(helper).onClick = function()
            UIHelpPanel:show(description)
        end
    end
    UpdateBeat:Add(this.UpdateBeat, this)
    beatRegistered = true
end

function this:OnDisable(obj)
    enabled = false
end

function this:OnDestroy()
    if beatRegistered then
        UpdateBeat:Remove(this.UpdateBeat, this)
    end
    if bigSetField ~= nil then bigSetField:Destroy() end
    if currentGridField ~= nil then currentGridField:Destroy() end
    if detailField ~= nil then detailField:Destroy() end
    if detailItemField ~= nil then detailItemField:Destroy() end
    if detailIconField ~= nil then detailIconField:Destroy() end
    if detailValueField ~= nil then detailValueField:Destroy() end
    panel = nil
    helper = nil
end

function this.UpdateBeat()
    if not enabled or panel == nil then return end
    local setID = tostring(bigSetField:Get(panel))
    if channelGroup == 60 then
        local showHelp = setID == '47000019' or setID == '47000020'
        if helper.activeSelf ~= showHelp then helper:SetActive(showHelp) end
    elseif virtualYuanSets[setID] then
        showVirtualPrices()
    end
end

return this
