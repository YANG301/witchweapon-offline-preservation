-- Refresh daily/furnace progress after any battle or sweep result, and keep
-- the original daily chapter counters consistent with their level counters.
do
    local nextCheck = 0
    local pending, seenSweep, errorReported = false, false, false
    local resultType, sweepType, dailyType, trialType, trialSelectType
    local detailType, progressType, userType, chapterType, levelType
    local send, idField, sweepIdField, getProgressByChapter
    local levelsProperty, countProperty, battleCountProperty, levelIdProperty

    local function isDungeon(id)
        return id >= 3120001001 and id <= 3120007005
    end

    local function setup()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        resultType = typeof('WaterBell.ProjX.View.Panel.SettlementUI')
        sweepType = typeof('WaterBell.ProjX.View.Panel.SweepPanel')
        dailyType = typeof('DailyPanelControl')
        trialType = typeof('TrialPanelController')
        trialSelectType = typeof('TrialSelectLevel')
        detailType = typeof('WaterBell.ProjX.View.Panel.SelectLevelDetail')
        progressType = typeof('WaterBell.ProjX.Data.NetIO.UserAllProgressLogic')
        userType = typeof('WaterBell.ProjX.Data.Entity.UserInfo')
        chapterType = typeof('WaterBell.ProjX.Data.Entity.ObservableSingleChapter')
        levelType = typeof('WaterBell.ProjX.Data.Entity.ObservableSingleLevel')
        send = tolua.gettypemethod(
            typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        idField = tolua.getfield(resultType, 'instanceId', 65535)
        sweepIdField = tolua.getfield(sweepType, 'instanceId', 65535)
        getProgressByChapter = tolua.getmethod(
            typeof('WaterBell.ProjX.Data.Entity.Progress'),
            'GetProgressByChapterID', typeof('System.Int64'))
        levelsProperty = tolua.getproperty(chapterType, 'Levels', 65535)
        countProperty = tolua.getproperty(chapterType, 'Count', 65535)
        battleCountProperty = tolua.getproperty(levelType, 'BattleCount', 65535)
        levelIdProperty = tolua.getproperty(levelType, 'ID', 65535)
        if resultType == nil or sweepType == nil or dailyType == nil or
                trialType == nil or trialSelectType == nil or
                detailType == nil or progressType == nil or userType == nil or
                chapterType == nil or levelType == nil or send == nil or
                idField == nil or sweepIdField == nil or
                getProgressByChapter == nil or levelsProperty == nil or
                countProperty == nil or battleCountProperty == nil or
                levelIdProperty == nil then
            error('Dungeon sweep refresh target is missing')
        end
    end

    local function active(component)
        return component ~= nil and not component:Equals(nil) and
            component.gameObject.activeInHierarchy
    end

    -- The original ObservableSingleChapter.UpdateChapters adds the incoming
    -- level counts to its old Count on every getAllProgress response.  The
    -- on-screen value can therefore say "1 remaining" while the battle and
    -- sweep validators see an accumulated Count of 2.  Rebuild only the six
    -- daily group counters from their actual per-level counts.  The setter
    -- notifies the original view models; the server still enforces the cap.
    local function repairDailyCounts()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        if user == nil then return end
        local progress = user:GetProgress()
        if progress == nil then return end
        for groupId = 3020001, 3020006 do
            local chapter = getProgressByChapter:Call(progress, groupId)
            if chapter ~= nil then
                local levels = levelsProperty:Get(chapter, nil)
                local expected = groupId <= 3020004 and 7 or 6
                if levels ~= nil and tonumber(tostring(levels.Count)) == expected then
                    local total, complete = 0, true
                    for index = 0, expected - 1 do
                        local level = levels[index]
                        local id = level ~= nil and
                            tonumber(tostring(levelIdProperty:Get(level, nil))) or nil
                        local used = level ~= nil and
                            tonumber(tostring(battleCountProperty:Get(level, nil))) or nil
                        if id == nil or math.floor(id / 1000) ~= groupId + 100000 or
                                used == nil or used < 0 then
                            complete = false
                            break
                        end
                        total = total + used
                    end
                    local limit = groupId <= 3020004 and 2 or 3
                    if complete and total <= limit then
                        local current = tonumber(tostring(countProperty:Get(chapter, nil)))
                        if current ~= total then
                            countProperty:Set(chapter, total, nil)
                            UnityEngine.Debug.Log('ONLINE_DUNGEON_COUNT_REPAIRED '
                                .. tostring(groupId) .. ' ' .. tostring(current)
                                .. ' -> ' .. tostring(total))
                        end
                    end
                end
            end
        end
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25
        local result = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(resultType)
        if active(result) then
            local id = tonumber(tostring(idField:Get(result))) or 0
            -- A failed battle also spends a daily attempt.
            if isDungeon(id) then
                pending = true
            end
            return
        end
        local sweep = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(sweepType)
        if active(sweep) then
            seenSweep = isDungeon(tonumber(tostring(sweepIdField:Get(sweep))) or 0)
            return
        end
        if seenSweep then
            pending, seenSweep = true, false
        end
        local daily = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(dailyType)
        local trial = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(trialType)
        local trialSelect = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(trialSelectType)
        local detail = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(detailType)
        if not active(daily) and not active(trial) and
                not active(trialSelect) and not active(detail) then return end
        repairDailyCounts()
        if not pending then return end
        send:Call(tolua.createinstance(progressType))
        pending = false
        UnityEngine.Debug.Log('ONLINE_DUNGEON_PROGRESS_REFRESH')
    end

    local ok, err = pcall(function()
        setup()
        UpdateBeat:Add(function()
            local success, tickError = pcall(tick)
            if not success then
                if not errorReported then
                    errorReported = true
                    UnityEngine.Debug.LogError(
                        'ONLINE_DUNGEON_PROGRESS_REFRESH ' .. tostring(tickError))
                end
                nextCheck = UnityEngine.Time.realtimeSinceStartup + 5
            end
        end)
    end)
    if not ok then
        UnityEngine.Debug.LogError('ONLINE_DUNGEON_PROGRESS_INIT ' .. tostring(err))
    end
end
