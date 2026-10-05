-- Repaint the preserved quest row when GetAllQuest updates its native model.
-- StoryQuest can remain locked after its target is met until the previous
-- chapter reward is claimed; display no more than the original target.
local this = {}
local rows = {}
local showCounterByType = {}
local questViewType
local questModelType
local questDataType
local methodStatus
local methodMeta
local CHECK_INTERVAL = 0.5
local properties = {}
local observing, nextRowsCheck = false, 0

local function getProperty(typeObject, name, target)
    if target == nil then return nil end
    local key = tostring(typeObject) .. '/' .. name
    local property = properties[key]
    if property == nil then
        property = tolua.getproperty(typeObject, name)
        properties[key] = property
    end
    if property == nil then return nil end
    local ok, value = pcall(function() return property:Get(target, nil) end)
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
    rows[row.owner] = nil
end

-- One observer for all rows, including rows pooled beneath a hidden page.
-- Removing each destroyed owner releases its view/label; hidden rows do not
-- keep reflecting quest models or allocating native property handles.
local function updateRows()
    local now = UnityEngine.Time.realtimeSinceStartup
    if now < nextRowsCheck then return end
    nextRowsCheck = now + CHECK_INTERVAL
    if WWRRuntimeUI ~= nil and not WWRRuntimeUI.SceneShown(18) then return end
    for _, row in pairs(rows) do this.UpdateBeat(row, now) end
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
    if not observing then
        observing = true
        UpdateBeat:Add(updateRows)
    end
end

function this:OnDestroy(obj)
    if obj ~= nil then removeRow(rows[obj]) end
end

function this.UpdateBeat(row, now)
    if not row.listening then return end
    now = now or UnityEngine.Time.realtimeSinceStartup
    if now < row.nextCheck then return end
    row.nextCheck = now + CHECK_INTERVAL
    if row.owner == nil or row.owner:Equals(nil) then
        removeRow(row)
        return
    end
    if not row.owner.activeInHierarchy then return end
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

    -- Native binding has already painted a newly created row. Record its first
    -- snapshot rather than re-entering native layout for every pooled task.
    -- Subsequent model changes still repaint the existing original controls.
    if row.lastStatus == nil then row.lastStatus = status end
    if row.lastMeta == nil then row.lastMeta = meta end
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
        local shown = math.max(0, math.min(meta, target))
        text = '[FF0000]' .. tostring(shown) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    else
        text = '[FFFFFF]' .. tostring(target) .. '[-][AFAFAF]/' .. tostring(target) .. '[-]'
    end
    if row.label.text ~= text then row.label.text = text end
end

return this
