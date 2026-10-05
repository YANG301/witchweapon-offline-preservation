-- Keep the preserved QuestInfoView and its original status colours.
-- Each task row owns an UpdateBeat listener; the original patch shared one
-- label between all rows and stopped updating as soon as it had any text.
local this = {}
local rows = {}
local showCounterByType = {}
local questViewType
local questModelType
local questDataType
local CHECK_INTERVAL = 0.5

local function getProperty(typeObject, name, target)
    if target == nil then return nil end
    local property = tolua.getproperty(typeObject, name)
    if property == nil then return nil end
    local ok, value = pcall(function() return property:Get(target, nil) end)
    property:Destroy()
    if ok then return value end
    return nil
end

local function hasCounter(typeID)
    local cached = showCounterByType[typeID]
    if cached ~= nil then return cached end
    local csv = CSVPool.AchievementConfig()
    if csv == nil then return false end
    local visible = true
    for i = 1, #csv do
        if csv[i].ID == typeID then
            visible = csv[i].arg1 ~= ''
            break
        end
    end
    showCounterByType[typeID] = visible
    return visible
end

local function removeRow(row)
    if row == nil or not row.listening then return end
    row.listening = false
    UpdateBeat:Remove(this.UpdateBeat, row)
    rows[row.owner] = nil
end

function this:Start(obj)
    require 'tolua.reflection'
    tolua.loadassembly('Assembly-CSharp')
    questViewType = questViewType or typeof('QuestInfoViewBase')
    questModelType = questModelType or typeof('QuestInfoViewModel')
    questDataType = questDataType or typeof('QuestData')

    if rows[obj] ~= nil then removeRow(rows[obj]) end
    local row = {
        owner = obj,
        view = obj.transform:GetComponent('QuestInfoView'),
        label = obj.transform:Find('btn/conditionCount'):GetComponent('UILabel'),
        nextCheck = 0,
        listening = true,
    }
    rows[obj] = row
    UpdateBeat:Add(this.UpdateBeat, row)
end

function this:OnDestroy(obj)
    -- LuaComponent passes its GameObject on versions that expose it here.
    -- On other versions the listener also removes itself when Unity destroys it.
    if obj ~= nil then removeRow(rows[obj]) end
end

function this.UpdateBeat(row)
    if not row.listening then return end
    if row.owner == nil or row.owner:Equals(nil) then
        removeRow(row)
        return
    end
    local now = UnityEngine.Time.realtimeSinceStartup
    if now < row.nextCheck then return end
    row.nextCheck = now + CHECK_INTERVAL
    if row.label == nil or row.label:Equals(nil) then
        removeRow(row)
        return
    end
    if not row.label.gameObject.activeSelf then return end

    local quest = getProperty(questViewType, 'QuestInfo', row.view)
    if quest == nil then return end
    local info = getProperty(questModelType, 'Info', quest)
    if info == nil then return end
    local status = getProperty(questModelType, 'Status', quest)
    local meta = getProperty(questModelType, 'Meta', quest)
    local typeID = getProperty(questDataType, 'Type', info)
    local target = getProperty(questDataType, 'Argu1', info)
    if status == nil or meta == nil or typeID == nil or target == nil then return end
    if not hasCounter(typeID) then return end

    if row.lastStatus == status and row.lastMeta == meta and
       row.lastTarget == target and row.label.text == row.lastText then return end

    local text
    if status == -1 then
        text = '[FF0000]' .. tostring(meta) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    else
        text = '[FFFFFF]' .. tostring(target) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    end
    if row.label.text ~= text then row.label.text = text end
    row.lastStatus = status
    row.lastMeta = meta
    row.lastTarget = target
    row.lastText = text
end

return this
