-- Refresh every original task entry and serialize single/batch reward clicks.
-- Never grant resources or reopen a loot popup here: native settlement owns both.
do
    local nextCheck, lastErrorAt = 0, -100
    local panelType, rowType, viewType, modelType, questType, jobType, metaType
    local managerType, managerModelType, protocolType, messageType, achievementMessageType, send
    local achievementType, achievementJobType, achievementMetaType
    local popupTypes = {}
    local fields, properties, lists = {}, {}, {}
    local entries, panelID, mode, signature, repaintAt = {}, nil, nil, nil, nil
    local refreshQueued, pending = false, nil
    local sourceQuest, initialized
    local nextMainlineFetch, fetching, wasBusy = 0, false, false
    local MAINLINE_REFRESH_INTERVAL = 5

    local function alive(value)
        return value ~= nil and not value:Equals(nil)
    end

    local function active(value)
        return alive(value) and value.gameObject.activeInHierarchy
    end

    local function property(kind, name)
        local key = tostring(kind) .. '/' .. name
        if properties[key] == nil then
            properties[key] = tolua.getproperty(kind, name, 65535)
            if properties[key] == nil then error('Task property missing: ' .. name) end
        end
        return properties[key]
    end

    local function get(kind, name, target)
        if target == nil then return nil end
        return property(kind, name):Get(target, nil)
    end

    local function setup()
        if initialized then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        panelType = typeof('WaterBell.ProjX.View.Panel.TaskPanelController')
        rowType = typeof('QuestInfoView')
        viewType = typeof('QuestInfoViewBase')
        modelType = typeof('QuestInfoViewModel')
        questType = typeof('WaterBell.ProjX.Data.Entity.Quest')
        jobType = typeof('WaterBell.ProjX.Data.Entity.ObservableJob')
        metaType = typeof('WaterBell.ProjX.Data.Entity.ObservableMetaInfo')
        managerType = typeof('QuestSystemManagerViewBase')
        managerModelType = typeof('QuestSystemManagerViewModel')
        protocolType = typeof('WaterBell.ProjX.Data.NetIO.ProtocolManager')
        messageType = typeof('WaterBell.ProjX.Data.NetIO.GetAllQuest')
        achievementMessageType = typeof('WaterBell.ProjX.Data.NetIO.GetAllAchieve')
        achievementType = typeof('WaterBell.ProjX.Data.Entity.Achievement')
        achievementJobType = typeof('WaterBell.ProjX.Data.Entity.AchievementJob')
        achievementMetaType = typeof('WaterBell.ProjX.Data.Entity.AchievementMeta')
        for _, name in ipairs({'GetAwardsPanel', 'GetLootsPanel'}) do
            popupTypes[#popupTypes + 1] = typeof('WaterBell.ProjX.View.Panel.' .. name)
        end
        send = tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        for _, name in ipairs({'currentMode', 'taskType', 'Current_Grid', 'id', 'buttonFinish', 'getAllBtn'}) do
            fields[name] = tolua.getfield(panelType, name, 65535)
            if fields[name] == nil then error('Task field missing: ' .. name) end
        end
        fields.rowButton = tolua.getfield(rowType, 'getAwardBtn', 65535)
        fields.repaint = tolua.getmethod(panelType, 'ReFreshGrid', typeof('UnityEngine.Transform'), typeof('System.Boolean'))
        fields.achievement = tolua.gettypemethod(panelType, 'ReFreshAchieGrid', 65535)
        fields.allButton = tolua.gettypemethod(panelType, 'SetGetAllBtn', 65535)
        fields.protocol = tolua.gettypemethod(protocolType, 'GetInstance', 65535)
        fields.count = tolua.gettypemethod(protocolType, 'getNormalMsgCount', 65535)
        fields.collectionCount = tolua.getproperty(typeof('System.Collections.ICollection'), 'Count', 65535)
        fields.collectionItem = tolua.getmethod(typeof('System.Collections.IList'), 'get_Item', typeof('System.Int32'))
        fields.achievementCount = tolua.gettypemethod(achievementType, 'GetProgressingAchieveLength', 65535)
        fields.achievementMeta = tolua.getmethod(achievementType, 'GetProgressingAchieveByIndex', typeof('System.Int32'))
        for _, name in ipairs({'DailyQuests', 'SideQuests', 'RandomQuests', 'GuideQuest', 'StoryQuest', 'ActivityQuest', 'ActivityDailyQuest'}) do
            lists[#lists + 1] = property(managerModelType, name)
        end
        if send == nil or fields.rowButton == nil or fields.repaint == nil or
                fields.achievement == nil or fields.allButton == nil or
                fields.protocol == nil or fields.count == nil or fields.collectionCount == nil or
                fields.collectionItem == nil then
            error('Task reflection methods unavailable')
        end
        initialized = true
        UnityEngine.Debug.LogWarning('ONLINE_TASK_LIVE_READY 143')
    end

    -- ObservableCollection<T>/ModelCollection<T> need not have a generated
    -- ToLua wrapper. Use their preserved non-generic IList/ICollection API.
    local function count(list) return fields.collectionCount:Get(list, nil) end
    local function item(list, index) return fields.collectionItem:Call(list, index) end

    local function isAchievement(value)
        return value == 'AchievTask' or tonumber(value) == 2
    end

    local function rewardVisible()
        for _, kind in ipairs(popupTypes) do
            if active((WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(kind)) then return true end
        end
        return false
    end

    local function achievementSignature()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        if user == nil then return nil end
        local achievements = user:GetAchievement()
        if achievements == nil then return nil end
        local parts = {}
        local jobs = get(achievementType, 'AchieveJob', achievements)
        if jobs ~= nil then
            for index = 0, count(jobs) - 1 do
                local job = item(jobs, index)
                parts[#parts + 1] = tostring(get(achievementJobType, 'ID', job)) .. ':' ..
                    tostring(get(achievementJobType, 'Status', job))
            end
        end
        local length = tonumber(tostring(fields.achievementCount:Call(achievements)))
        for index = 0, length - 1 do
            local meta = fields.achievementMeta:Call(achievements, index)
            local args = get(achievementMetaType, 'Args', meta)
            local value = args ~= nil and count(args) > 0 and tostring(item(args, 0)) or ''
            parts[#parts + 1] = tostring(get(achievementMetaType, 'HeadID', meta)) .. '=' .. value
        end
        return table.concat(parts, '|')
    end

    local function snapshot()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        if user == nil then return nil end
        local quest = user:GetQuest()
        if quest == nil then return nil end
        if sourceQuest ~= nil and sourceQuest ~= quest then pending = nil end
        sourceQuest = quest
        local jobs, metas, parts = {}, {}, {}
        local allJobs = get(questType, 'QuestJob', quest)
        local allMetas = get(questType, 'QuestMeta', quest)
        if allJobs == nil or allMetas == nil then return nil end
        for index = 0, count(allJobs) - 1 do
            local job = item(allJobs, index)
            local id = tostring(get(jobType, 'ID', job))
            local status = tonumber(tostring(get(jobType, 'Status', job)))
            jobs[id] = {status = status, valid = get(jobType, 'Valid', job)}
            parts[#parts + 1] = id .. ':' .. tostring(status) .. ':' .. tostring(jobs[id].valid)
        end
        for index = 0, count(allMetas) - 1 do
            local meta = item(allMetas, index)
            local id = tostring(get(metaType, 'JobID', meta))
            local value = tonumber(tostring(get(metaType, 'Meta', meta)))
            metas[id] = value
            parts[#parts + 1] = id .. '=' .. tostring(value)
        end
        return {jobs = jobs, metas = metas, signature = table.concat(parts, '|')}
    end

    local function syncModels(panel, data)
        local manager = panel:GetComponent('QuestSystemManagerView')
        if not alive(manager) then return false end
        local root = get(managerType, 'QuestSystemManager', manager)
        if root == nil then return false end
        local changed = false
        for _, listProperty in ipairs(lists) do
            local list = listProperty:Get(root, nil)
            if list ~= nil then
                for index = 0, count(list) - 1 do
                    local model = item(list, index)
                    local id = tostring(get(modelType, 'ID', model))
                    local job, meta = data.jobs[id], data.metas[id]
                    if job ~= nil then
                        if get(modelType, 'Status', model) ~= job.status then
                            property(modelType, 'Status'):Set(model, job.status, nil)
                            changed = true
                        end
                        if get(modelType, 'Valid', model) ~= job.valid then
                            property(modelType, 'Valid'):Set(model, job.valid, nil)
                            changed = true
                        end
                        if meta ~= nil and get(modelType, 'Meta', model) ~= meta then
                            property(modelType, 'Meta'):Set(model, meta, nil)
                            changed = true
                        end
                    end
                end
            end
        end
        return changed
    end

    local function repaint(panel)
        local current = tostring(fields.currentMode:Get(panel))
        if isAchievement(current) then
            fields.achievement:Call(panel)
        else
            local grid = fields.Current_Grid:Get(panel)
            if alive(grid) then fields.repaint:Call(panel, grid, true) end
        end
        fields.allButton:Call(panel)
    end

    local function restore(entry)
        if alive(entry.button) and entry.button.onClick == nil then
            entry.button.onClick = entry.originalClick
        end
        if alive(entry.listener) then entry.listener.onClick = entry.originalListener end
    end

    local function releaseButtons()
        for id, entry in pairs(entries) do
            restore(entry)
            entries[id] = nil
        end
    end

    local function targetsFor(panel, row, bulk, data)
        local ids = {}
        if row ~= nil then
            local model = get(viewType, 'QuestInfo', row)
            if model ~= nil then ids[1] = tostring(get(modelType, 'ID', model)) end
        elseif not bulk then
            ids[1] = tostring(fields.id:Get(panel))
        else
            local manager = panel:GetComponent('QuestSystemManagerView')
            if not alive(manager) then return ids end
            local root = get(managerType, 'QuestSystemManager', manager)
            local category = tonumber(tostring(fields.taskType:Get(panel)))
            local listName = ({[2] = 'DailyQuests', [6] = 'StoryQuest',
                [7] = 'ActivityQuest', [9] = 'ActivityDailyQuest'})[category]
            local tasks = listName ~= nil and get(managerModelType, listName, root) or nil
            if tasks ~= nil then
                for index = 0, count(tasks) - 1 do
                    local id = tostring(get(modelType, 'ID', item(tasks, index)))
                    if data.jobs[id] ~= nil and data.jobs[id].status == 0 then ids[#ids + 1] = id end
                end
            end
        end
        return ids
    end

    local function bind(button, panel, row, bulk, seen)
        if not active(button) or not button.isEnabled then return end
        local id = button:GetInstanceID()
        seen[id] = true
        local entry = entries[id]
        if entry ~= nil then
            if button.onClick ~= nil then
                entry.originalClick = button.onClick
                button.onClick = nil
            end
            entry.listener.onClick = entry.callback
            return
        end
        local listener = UIEventListener.Get(button.gameObject)
        local click = button.onClick
        if click == nil or click.Count == 0 then return end
        -- An existing UIEventListener handler belongs to another preserved
        -- script. Do not replace it or look up its nested delegate type, which
        -- is in the APK's firstpass assembly and not in Assembly-CSharp.
        if listener.onClick ~= nil then return end
        entry = {button = button, listener = listener, originalClick = click, originalListener = listener.onClick}
        entry.callback = function(go)
            local now = UnityEngine.Time.realtimeSinceStartup
            if pending ~= nil or rewardVisible() then
                UnityEngine.Debug.Log('ONLINE_TASK_DUPLICATE_BLOCKED')
                return
            end
            local protocol = fields.protocol:Call()
            if protocol ~= nil and tonumber(tostring(fields.count:Call(protocol))) > 0 then
                refreshQueued = true
                return
            end
            local data = snapshot()
            if data == nil then refreshQueued = true; return end
            local ids = targetsFor(panel, row, bulk, data)
            if #ids == 0 then refreshQueued = true; return end
            for _, jobID in ipairs(ids) do
                if data.jobs[jobID] == nil or data.jobs[jobID].status ~= 0 then
                    refreshQueued = true
                    return
                end
            end
            pending = {ids = ids, started = now}
            local ok, err = pcall(function()
                -- The preserved EventDelegate list is invoked once. Never call
                -- ExecuteFinishiQuest/AddLoot/ShowAwards a second time in Lua.
                EventDelegate.Execute(entry.originalClick)
            end)
            if not ok then pending = nil; error(err) end
            UnityEngine.Debug.Log('ONLINE_TASK_CLAIM_STARTED ' .. table.concat(ids, ','))
        end
        button.onClick = nil
        listener.onClick = entry.callback
        entries[id] = entry
    end

    local function bindButtons(panel)
        local seen = {}
        bind(fields.buttonFinish:Get(panel), panel, nil, false, seen)
        bind(fields.getAllBtn:Get(panel), panel, nil, true, seen)
        local rows = panel:GetComponentsInChildren(rowType)
        for index = 0, rows.Length - 1 do
            local row = rows[index]
            if active(row) then bind(fields.rowButton:Get(row), panel, row, false, seen) end
        end
        for id, entry in pairs(entries) do
            if not seen[id] then restore(entry); entries[id] = nil end
        end
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25
        setup()
        local protocol = fields.protocol:Call()
        local busy = protocol ~= nil and tonumber(tostring(fields.count:Call(protocol))) > 0
        -- Observe requests even while gameplay hides the task panel. A completed
        -- action invalidates the task view; our own query must not loop itself.
        if wasBusy and not busy and not fetching then refreshQueued = true end
        wasBusy = busy
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(panelType)
        if not active(panel) then
            releaseButtons()
            panelID, mode, signature, repaintAt = nil, nil, nil, nil
            fetching = false
            return
        end
        local newID, newMode = panel:GetInstanceID(), tostring(fields.currentMode:Get(panel))
        if panelID ~= newID or mode ~= newMode then
            releaseButtons()
            panelID, mode, signature = newID, newMode, nil
            refreshQueued = true
            nextMainlineFetch = now
        end
        -- Reopening the page during an outstanding claim must restore the
        -- same click guard before the queue-idle early return.
        if not isAchievement(mode) then bindButtons(panel) end
        -- Native marks jobs claimed before its request is sent. Do not refresh
        -- models, rows or popup children while that sequence/animation is active.
        local popup = rewardVisible()
        if busy or popup then return end
        local achievements = isAchievement(mode)
        local data = not achievements and snapshot() or nil
        if not achievements and data == nil then return end
        if pending ~= nil then
            local complete = true
            for _, id in ipairs(pending.ids) do
                if data == nil or data.jobs[id] == nil or data.jobs[id].status ~= 1 then complete = false end
            end
            local manager = panel:GetComponent('QuestSystemManagerView')
            local root = alive(manager) and get(managerType, 'QuestSystemManager', manager) or nil
            local result = root ~= nil and tonumber(tostring(get(managerModelType, 'QuestResult', root))) or -1
            if complete and result == 0 and now - pending.started >= 0.5 then
                pending = nil
                -- Native claim settlement updates the claimed job only. Fetch
                -- the authoritative successor status before displaying its row.
                refreshQueued = true
                UnityEngine.Debug.LogWarning('ONLINE_TASK_CLAIM_SETTLED')
            elseif now - pending.started >= 15 then
                pending = nil
                refreshQueued = true
                -- Timeout does not grant anything or automatically resend a claim.
            end
        end
        if pending ~= nil then return end
        local newSignature
        if achievements then newSignature = achievementSignature() else newSignature = data.signature end
        -- The source jobs are immutable between signatures. Avoid reflecting
        -- all seven pooled model collections four times a second while idle.
        local modelsChanged = not achievements and signature ~= newSignature and syncModels(panel, data) or false
        if newSignature ~= nil and (signature ~= newSignature or modelsChanged) then
            local first = signature == nil
            signature = newSignature
            -- Native tab navigation already draws the first page. Re-layout
            -- only for a changed model or a later authoritative update.
            if not first or modelsChanged then repaint(panel) end
        end
        local mainline = mode == 'MainLine' or tonumber(mode) == 1
        -- Story targets and chained rewards can change without a pushed QuestJob
        -- notification. Query only while this original page is visible, and only
        -- while the native message queue and reward settlement are idle.
        if (mainline or achievements) and now >= nextMainlineFetch and not fetching then refreshQueued = true end
        if refreshQueued and pending == nil and not busy and not fetching then
            refreshQueued = false
            fetching = true
            send:Call(tolua.createinstance(achievements and achievementMessageType or messageType))
            repaintAt = now + 1
            nextMainlineFetch = now + MAINLINE_REFRESH_INTERVAL
            UnityEngine.Debug.LogWarning('ONLINE_TASK_FETCH ' .. mode)
        end
        if repaintAt ~= nil and now >= repaintAt and not busy then
            repaintAt = nil
            fetching = false
            nextMainlineFetch = now + MAINLINE_REFRESH_INTERVAL
            -- ReFreshGrid resets the scroll bar and hides selected-row details.
            -- The signature/model-change path above already repaints changed
            -- jobs. An unchanged response must preserve the player's position.
            if mainline then
                local ready, claimed = 0, 0
                local manager = panel:GetComponent('QuestSystemManagerView')
                local root = alive(manager) and get(managerType, 'QuestSystemManager', manager) or nil
                local story = get(managerModelType, 'StoryQuest', root)
                if story ~= nil then
                    for index = 0, count(story) - 1 do
                        local status = tonumber(tostring(get(modelType, 'Status', item(story, index))))
                        if status == 0 then ready = ready + 1 elseif status == 1 then claimed = claimed + 1 end
                    end
                end
                UnityEngine.Debug.LogWarning('ONLINE_MAINLINE_TASK_SYNC ready=' .. ready .. ' claimed=' .. claimed)
            end
        end
        if achievements then releaseButtons(); return end
        bindButtons(panel)
    end

    UpdateBeat:Add(function()
        local ok, err = pcall(tick)
        if not ok then
            pcall(releaseButtons)
            nextCheck = UnityEngine.Time.realtimeSinceStartup + 5
            if nextCheck - lastErrorAt >= 30 then
                lastErrorAt = nextCheck
                UnityEngine.Debug.LogError('ONLINE_TASK_LIVE_ERROR ' .. tostring(err))
            end
        end
    end)
end
