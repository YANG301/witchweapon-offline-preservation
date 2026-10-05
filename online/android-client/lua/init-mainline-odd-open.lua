-- In the open-all mainline profile, the native post-battle UserInfoSimple
-- closes nonrepeatable normal stages after it parses the server OpenLevel event.
-- Restore only the 80 odd normal stage unlock flags while settlement or map is visible.
do
    local nextCheck = 0
    local reportedError = false
    local pendingMapSync = false
    local mapType, settlementType, chapterType, levelType
    local getChapter, levelsProperty, idProperty, unlockProperty, syncData

    local function setup()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        mapType = typeof('WaterBell.ProjX.View.Panel.MapPanelControl')
        settlementType = typeof('WaterBell.ProjX.View.Panel.SettlementUI')
        chapterType = typeof('WaterBell.ProjX.Data.Entity.ObservableSingleChapter')
        levelType = typeof('WaterBell.ProjX.Data.Entity.ObservableSingleLevel')
        getChapter = tolua.getmethod(
            typeof('WaterBell.ProjX.Data.Entity.Progress'),
            'GetProgressByChapterID', typeof('System.Int64'))
        levelsProperty = tolua.getproperty(chapterType, 'Levels', 65535)
        idProperty = tolua.getproperty(levelType, 'ID', 65535)
        unlockProperty = tolua.getproperty(levelType, 'UnLocok', 65535)
        syncData = tolua.gettypemethod(mapType, 'SyncData', 65535)
        if mapType == nil or settlementType == nil or chapterType == nil or
                levelType == nil or getChapter == nil or levelsProperty == nil or
                idProperty == nil or unlockProperty == nil or syncData == nil then
            error('Mainline odd-stage reflection target is missing')
        end
    end

    local function active(panel)
        return panel ~= nil and not panel:Equals(nil) and
            panel.gameObject.activeInHierarchy
    end

    local function isFalse(value)
        return value == false or tostring(value) == 'False' or
            tostring(value) == 'false'
    end

    local function restoreOddStages()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        if user == nil then return 0 end
        local progress = user:GetProgress()
        if progress == nil then return 0 end
        local changed = 0
        for chapterNumber = 1, 16 do
            local chapter = getChapter:Call(progress, 3010000 + chapterNumber)
            if chapter ~= nil then
                local levels = levelsProperty:Get(chapter, nil)
                local count = levels ~= nil and tonumber(tostring(levels.Count)) or nil
                if count ~= nil and count > 0 and count <= 20 then
                    local prefix = 3110000000 + chapterNumber * 1000
                    for index = 0, count - 1 do
                        local level = levels[index]
                        if level ~= nil then
                            local id = tonumber(tostring(idProperty:Get(level, nil)))
                            local order = id ~= nil and id - prefix or nil
                            if order ~= nil and order >= 1 and order <= 10 and
                                    order % 2 == 1 and
                                    isFalse(unlockProperty:Get(level, nil)) then
                                -- The property setter emits SelfChange, updating CanFight.
                                -- Leave IsClear, repeatability, counts and sweep rules alone.
                                unlockProperty:Set(level, true, nil)
                                changed = changed + 1
                            end
                        end
                    end
                end
            end
        end
        return changed
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25
        local settlement = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(settlementType)
        local map = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(mapType)
        if not active(settlement) and not active(map) then return end
        local changed = restoreOddStages()
        if changed > 0 then
            pendingMapSync = true
            UnityEngine.Debug.Log('ONLINE_MAINLINE_ODD_OPEN_REPAIRED ' .. tostring(changed))
        end
        -- OpenPanel normally calls SyncData. If the native close happens while
        -- the map is already open, refresh its icon state once after the repair.
        if pendingMapSync and active(map) and not active(settlement) then
            syncData:Call(map)
            pendingMapSync = false
        end
    end

    local ok, err = pcall(function()
        setup()
        UpdateBeat:Add(function()
            local success, tickError = pcall(tick)
            if not success then
                nextCheck = UnityEngine.Time.realtimeSinceStartup + 1
                if not reportedError then
                    reportedError = true
                    UnityEngine.Debug.LogError(
                        'ONLINE_MAINLINE_ODD_OPEN ' .. tostring(tickError))
                end
            end
        end)
    end)
    if not ok then
        UnityEngine.Debug.LogError('ONLINE_MAINLINE_ODD_OPEN_INIT ' .. tostring(err))
    end
end
