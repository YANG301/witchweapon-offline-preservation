local this = {}

local panel
local currentBigSetID
local price1
local enabled = false
local beatRegistered = false

function this:Awake(obj)
    local center = obj.transform.parent.parent
    local parent = center:Find('price1')
    price1 = {
        obj = parent.gameObject,
        label = parent:Find('Label'):GetComponent('UILabel'),
        img = parent:Find('img').gameObject,
        label1 = parent:Find('Label (1)').gameObject,
    }
end

function this:OnEnable(obj)
    enabled = true
end

function this:Start(obj)
    require 'tolua.reflection'
    tolua.loadassembly('Assembly-CSharp')
    panel = obj.transform.parent.parent.parent:GetComponent('NewShopPanelControl')
    currentBigSetID = tolua.getfield(typeof('NewShopPanelControl'), 'currentBigSetID')
    UpdateBeat:Add(this.UpdateBeat, this)
    beatRegistered = true
end

function this:OnDisable(obj)
    enabled = false
end

function this:OnDestroy()
    if beatRegistered then UpdateBeat:Remove(this.UpdateBeat, this) end
    if currentBigSetID ~= nil then currentBigSetID:Destroy() end
    panel = nil
    price1 = nil
end

function this.UpdateBeat()
    if not enabled or panel == nil then return end
    local setID = tostring(currentBigSetID:Get(panel))
    -- The archived patch adds a second RealRmb counter. Gift cards and
    -- monthly cards already have the normal top resource bar.
    if setID == '47000002' or setID == '47000016' then
        if price1.obj.activeSelf then price1.obj:SetActive(false) end
        return
    end
    if not price1.obj.activeSelf then price1.obj:SetActive(true) end
    if price1.img.activeSelf then price1.img:SetActive(false) end
    if not price1.label1.activeSelf then price1.label1:SetActive(true) end
    price1.label.text = tonumber(tostring(UserInfo.GetInstance():GetPlayer().RealRmb))
end

return this
