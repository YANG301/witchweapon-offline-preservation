-- Require a visible weapon selection before an available furnace depth can start.
-- Also block a depth when the day's core claim quota is exhausted.
do
    local panelType, containerField, selectedField, cannotSelectField, childrenProperty
    local dataProperty, canFightField
    local currentPanel
    local blocked = {}
    local reportedError = false

    local function alive(value)
        return value ~= nil and not value:Equals(nil)
    end

    local function restore(entry)
        if not alive(entry.button) then return end
        if entry.button.onClick == nil then
            entry.button.onClick = entry.originalClick
        end
        if alive(entry.listener) then
            entry.listener.onClick = entry.originalListener
        end
    end

    local function restoreAll()
        for id, entry in pairs(blocked) do
            restore(entry)
            blocked[id] = nil
        end
    end

    local function setup()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        panelType = typeof('WaterBell.ProjX.View.Panel.ClimbTowerLevelDetail')
        local containerType = typeof('WaterBell.ProjX.View.Panel.UIPanelSingleContainer')
        local baseType = typeof('WaterBell.ProjX.View.Panel.UIPanelBase')
        local dataType = typeof('WaterBell.ProjX.View.Panel.CTLD_LevelButtonData')
        containerField = tolua.getfield(panelType, 'levelContainer', 65535)
        selectedField = tolua.getfield(panelType, 'selectWeaponID', 65535)
        cannotSelectField = tolua.getfield(panelType, 'cannotSelect', 65535)
        childrenProperty = tolua.getproperty(containerType, 'Children', 65535)
        dataProperty = tolua.getproperty(baseType, 'Data', 65535)
        canFightField = tolua.getfield(dataType, 'canFight', 65535)
        if panelType == nil or containerField == nil or selectedField == nil or
                cannotSelectField == nil or
                childrenProperty == nil or dataProperty == nil or canFightField == nil then
            error('Furnace selection target is missing')
        end
    end

    local function blockReason(panel)
        local exhausted = cannotSelectField:Get(panel)
        -- Native UpdatePanel hides both selection views when the daily quota is spent.
        -- Check this first even if a weapon ID remains from an earlier selection.
        if alive(exhausted) and exhausted.activeSelf then
            return '今日可用次数已用完'
        end
        -- SelectWeapon writes this field only after the native validation succeeds.
        local ok, weaponID = pcall(function()
            return tonumber(tostring(selectedField:Get(panel)))
        end)
        if not ok or weaponID == nil or weaponID <= 0 then
            return '请指定武器'
        end
        return nil
    end

    local function guard(child)
        local level = child.gameObject:GetComponent('CTLD_LevelButton')
        if not alive(level) then return nil end
        local data = dataProperty:Get(level, nil)
        local canFight = data ~= nil and tostring(canFightField:Get(data)) or 'False'
        if canFight ~= 'True' and canFight ~= 'true' then return nil end
        local button = level.gameObject:GetComponent('ButtonEx')
        if not alive(button) or not button.enabled or not button.isEnabled then return nil end
        local id = button:GetInstanceID()
        local entry = blocked[id]
        if entry ~= nil then
            -- C# may rebind a button while the panel stays open.
            if button.onClick ~= nil then
                entry.originalClick = button.onClick
                button.onClick = nil
            end
            if alive(entry.listener) then
                entry.listener.onClick = entry.gateClick
            end
            return id
        end
        local originalClick = button.onClick
        local listener = UIEventListener.Get(button.gameObject)
        local originalListener = listener.onClick
        local gateClick = function()
            local reason = alive(currentPanel) and blockReason(currentPanel) or '请指定武器'
            if reason == nil then
                restoreAll()
            else
                NetworkAlertUI.TryShowWarningTipBox(reason)
            end
        end
        button.onClick = nil
        listener.onClick = gateClick
        blocked[id] = {
            button = button,
            listener = listener,
            originalClick = originalClick,
            originalListener = originalListener,
            gateClick = gateClick,
        }
        return id
    end

    local function tick()
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(panelType)
        if not alive(panel) or not panel.gameObject.activeInHierarchy then
            restoreAll()
            currentPanel = nil
            return
        end
        if currentPanel == nil or not panel:Equals(currentPanel) then
            restoreAll()
            currentPanel = panel
        end
        if blockReason(panel) == nil then
            restoreAll()
            return
        end
        local container = containerField:Get(panel)
        if not alive(container) then return end
        local children = childrenProperty:Get(container, nil)
        if children == nil then return end
        local seen = {}
        for index = 0, children.Count - 1 do
            local child = children[index]
            if alive(child) then
                local id = guard(child)
                if id ~= nil then seen[id] = true end
            end
        end
        for id, entry in pairs(blocked) do
            if not seen[id] then
                restore(entry)
                blocked[id] = nil
            end
        end
    end

    local ok, err = pcall(function()
        setup()
        UpdateBeat:Add(function()
            local success, tickError = pcall(tick)
            if not success then
                pcall(restoreAll)
                if not reportedError then
                    reportedError = true
                    UnityEngine.Debug.LogError('ONLINE_FURNACE_SELECTION_GATE ' .. tostring(tickError))
                end
            end
        end)
    end)
    if not ok and not reportedError then
        reportedError = true
        UnityEngine.Debug.LogError('ONLINE_FURNACE_SELECTION_INIT ' .. tostring(err))
    end
end
