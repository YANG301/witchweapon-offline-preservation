-- Repaint the preserved quest row when GetAllQuest updates its native model.
-- QuestInfoView.StatusChanged owns the original 领取/前往/已领取 controls.
local this = {}
local rows = {}
local showCounterByType = {}
local questViewType
local questModelType
local questDataType
local methodStatus
local methodMeta
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
    local rowType = typeof('QuestInfoView')
    -- LuaMethod.Call counts the types supplied when looking up the method.
    -- The BindingFlags overload leaves that list empty, so Call(view, value)
    -- fails with "no overload for method takes '3' arguments".
    local intType = typeof('System.Int32')
    methodStatus = methodStatus or tolua.getmethod(rowType, 'StatusChanged', intType)
    methodMeta = methodMeta or tolua.getmethod(rowType, 'MetaChanged', intType)

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
    if row.view == nil or row.view:Equals(nil) or
       row.label == nil or row.label:Equals(nil) then
        removeRow(row)
        return
    end

    local quest = getProperty(questViewType, 'QuestInfo', row.view)
    if quest == nil then return end
    local info = getProperty(questModelType, 'Info', quest)
    if info == nil then return end
    local status = getProperty(questModelType, 'Status', quest)
    local meta = getProperty(questModelType, 'Meta', quest)
    local typeID = getProperty(questDataType, 'Type', info)
    local target = getProperty(questDataType, 'Argu1', info)
    if status == nil or meta == nil or typeID == nil or target == nil then return end

    -- The old v4 patch changed only conditionCount. The native row already has
    -- the original button/status painter; call it whenever the model changes.
    if not row.statusPainterFailed and row.lastStatus ~= status then
        local ok, err = pcall(function() methodStatus:Call(row.view, status) end)
        if not ok then
            row.statusPainterFailed = true
            UnityEngine.Debug.LogError('ONLINE_TASK_STATUS ' .. tostring(err))
        else
            row.lastStatus = status
        end
    end
    if not row.metaPainterFailed and row.lastMeta ~= meta then
        local ok, err = pcall(function() methodMeta:Call(row.view, meta) end)
        if not ok then
            row.metaPainterFailed = true
            UnityEngine.Debug.LogError('ONLINE_TASK_META ' .. tostring(err))
        else
            row.lastMeta = meta
        end
    end
    if not row.label.gameObject.activeSelf or not hasCounter(typeID) then return end

    local text
    if status == -1 then
        text = '[FF0000]' .. tostring(meta) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    else
        text = '[FFFFFF]' .. tostring(target) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    end
    if row.label.text ~= text then row.label.text = text end
end

return this
