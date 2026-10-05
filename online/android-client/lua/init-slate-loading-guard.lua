-- Slate challenges only. Append to the verified active init.lua; no reward request
-- is sent here. The original ChallengeMode victory path remains authoritative.
-- Battle layout is a clearly labelled temporary single-room configuration.
do
    local targets = {[3100005001]=true, [3100005002]=true, [3100005003]=true,
                     [3100005004]=true, [3100005005]=true}
    local STALL_SECONDS, MAX_LOAD_SECONDS = 90, 240
    local F, nextCheck, attempt, failedOnce = 65535, 0, nil, false
    local pendingWins = {}
    local r = {}

    local function number(value)
        return value ~= nil and tonumber(tostring(value)) or nil
    end
    local function getArg(args, key)
        if args ~= nil and args:ContainsKey(key) then return tostring(args[key]) end
        return nil
    end
    local function same(left, right)
        return left == right or (left ~= nil and right ~= nil and
               r.referenceEquals:Call(left, right))
    end
    local function alive(object)
        return object ~= nil and not tolua.isnull(object)
    end
    local function entries(dictionary)
        local result = {}
        if dictionary == nil then return result end
        local iterator = dictionary:GetEnumerator()
        while iterator:MoveNext() do
            result[#result + 1] = {key=iterator.Current.Key, value=iterator.Current.Value}
        end
        return result
    end

    local function initialize()
        if r.managerType ~= nil then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        tolua.loadassembly('Assembly-CSharp-firstpass')
        pcall(tolua.loadassembly, 'UnityEngine.CoreModule')
        pcall(tolua.loadassembly, 'UnityEngine')
        r.managerType = typeof('WaterBell.ProjX.Playmode.PlayModeMngr')
        r.modeType = typeof('WaterBell.ProjX.Playmode.BasicPlayMode')
        r.messageType = typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase')
        local collection = typeof('WaterBell.ProjX.Playmode.MngrCollection')
        local http = typeof('HTTP')
        local request = typeof('BestHTTP.HTTPRequest')
        local response = typeof('BestHTTP.HTTPResponse')
        local protocol = typeof('WaterBell.ProjX.Data.NetIO.ProtocolManager')
        r.getManager = tolua.gettypemethod(r.managerType, 'GetExistedInstance', F)
        r.currentMode = tolua.getfield(r.managerType, 'currPlayMode', F)
        r.getId = tolua.gettypemethod(r.modeType, 'GetInstanceID', F)
        r.getRestriction = tolua.gettypemethod(r.modeType, 'GetRestrictID', F)
        r.getMode = tolua.gettypemethod(r.modeType, 'GetModeType', F)
        r.state = tolua.getfield(r.modeType, 'state', F)
        r.collection = tolua.getfield(r.modeType, 'mc', F)
        r.preloading = tolua.getfield(r.modeType, 'preloadingData', F)
        r.progress = tolua.gettypemethod(typeof('BattlePreloadingData'), 'GetProgress', F)
        r.rootMono = tolua.getfield(collection, 'rootMono', F)
        r.rootNode = tolua.getfield(collection, 'rootNode', F)
        r.entityPool = tolua.getfield(collection, 'entityPool', F)
        r.dataStore = tolua.getfield(collection, 'dataStore', F)
        r.battleResult = tolua.getfield(collection, 'battleResult', F)
        r.resultPass = tolua.getfield(typeof('BattleResult'), 'Pass', F)
        r.resultLoot = tolua.getfield(typeof('BattleResult'), 'lootList', F)
        r.lootRmb = tolua.getproperty(typeof('Lootmod.LootList'), 'RmbInc', F)
        r.challengeState = tolua.getproperty(typeof('WaterBell.ProjX.Data.Entity.ObservablePlayer'), 'ChallengeState', F)
        r.roleInfoType = typeof('WaterBell.ProjX.Data.NetIO.RoleGetRoleInfoLogic')
        r.stopCoroutines = tolua.gettypemethod(typeof('UnityEngine.MonoBehaviour'), 'StopAllCoroutines', F)
        r.loadOut = tolua.gettypemethod(r.modeType, 'OnLoadOutBegin', F)
        r.loadOutState = tolua.getfield(typeof('WaterBell.ProjX.Playmode.PlayModeState'), 'LoadOut', F):Get(nil)
        r.httpRequests = tolua.getfield(http, 'dic', F)
        r.httpTags = tolua.getfield(http, 'tagDic', F)
        r.httpTimeouts = tolua.getfield(http, 'timeoutDic', F)
        r.requestState = tolua.getproperty(request, 'State', F)
        r.requestResponse = tolua.getproperty(request, 'Response', F)
        r.requestCallback = tolua.getproperty(request, 'Callback', F)
        r.statusCode = tolua.getproperty(response, 'StatusCode', F)
        r.abortRequest = tolua.gettypemethod(request, 'Abort', F)
        r.messageCode = tolua.getfield(r.messageType, 'code', F)
        r.messageArgs = tolua.getfield(r.messageType, 'argumentDic', F)
        r.messageUrl = tolua.getfield(r.messageType, 'url', F)
        r.initMessage = tolua.gettypemethod(r.messageType, 'InitParams', F)
        r.sendMessage = tolua.gettypemethod(r.messageType, 'SendMsg', F)
        r.getProtocol = tolua.gettypemethod(protocol, 'GetInstance', F)
        r.messagePool = tolua.getfield(protocol, 'MsgPool', F)
        r.referenceEquals = tolua.gettypemethod(typeof('System.Object'), 'ReferenceEquals', F)
        r.detailType = typeof('WaterBell.ProjX.View.Panel.SelectLevelDetail')
        r.detailId = tolua.getfield(r.detailType, 'instanceId', F)
        r.description = tolua.getfield(r.detailType, 'taskDescLabel', F)
        r.settlementType = typeof('WaterBell.ProjX.View.Panel.SettlementUI')
        r.settlementId = tolua.getfield(r.settlementType, 'instanceId', F)
        r.closeSettlement = tolua.gettypemethod(r.settlementType, 'ClosePanel', F)
        for key, value in pairs(r) do
            if value == nil then error('Missing slate reflection target ' .. key) end
        end
        local required = {'getManager','currentMode','getId','getRestriction','getMode','state',
            'collection','preloading','progress','rootMono','rootNode','entityPool','dataStore',
            'battleResult','resultPass','resultLoot','lootRmb','challengeState','roleInfoType',
            'stopCoroutines','loadOut','loadOutState','httpRequests','httpTags','httpTimeouts',
            'requestState','requestResponse','requestCallback','statusCode','abortRequest',
            'messageCode','messageArgs','messageUrl','initMessage','sendMessage','getProtocol',
            'messagePool','referenceEquals','detailType','detailId','description',
            'settlementType','settlementId','closeSettlement'}
        for _, key in ipairs(required) do
            if r[key] == nil then error('Missing slate reflection target ' .. key) end
        end
    end

    local function isAttemptMessage(message, current)
        local code = number(r.messageCode:Get(message))
        if code ~= 30058 and code ~= 30102 and code ~= 30104 and code ~= 30106 then return false end
        local args = r.messageArgs:Get(message)
        if code == 30106 then return getArg(args, 'challengeid') == tostring(current.restriction) end
        return getArg(args, 'instanceid') == tostring(current.id)
            or getArg(args, 'instanceID') == tostring(current.id)
            or getArg(args, 'instid') == tostring(current.id)
    end

    local function captureRequests(current)
        for _, entry in ipairs(entries(r.httpRequests:Get(nil))) do
            if number(r.messageCode:Get(entry.value)) == 30107 and
                    tostring(r.messageUrl:Get(entry.value)):match('challenge/combat/victory$') and
                    getArg(r.messageArgs:Get(entry.value), 'challengeid') == tostring(current.restriction) then
                current.victoryRequest = entry.key
                current.victoryMessage = entry.value
            end
            if isAttemptMessage(entry.value, current) then
                current.requests[entry.key] = entry.value
                if number(r.messageCode:Get(entry.value)) == 30058 then
                    current.startKey = getArg(r.messageArgs:Get(entry.value), 'idempotency')
                end
            end
        end
    end

    local function cancelServerAttempt(current)
        if current.cancelSent then return end
        local message = tolua.createinstance(r.messageType)
        r.initMessage:Call(message, 30107)
        local original = tostring(r.messageUrl:Get(message))
        local destination, replacements = original:gsub('challenge/combat/victory$', 'challenge/combat/cancel')
        if replacements ~= 1 then error('Unexpected slate cancellation route') end
        r.messageUrl:Set(message, destination)
        local args = r.messageArgs:Get(message)
        local player = UserInfo.GetInstance():GetPlayer()
        args['rid'] = tostring(player.roleID)
        args['instanceid'] = tostring(current.id)
        args['challengeid'] = tostring(current.restriction)
        if current.startKey ~= nil then args['battleStartKey'] = current.startKey end
        current.cancelMessage = message
        r.sendMessage:Call(message)
        current.cancelSent = true
    end

    local function refreshRole(current)
        if current.roleRefreshSent then return end
        current.roleRefresh = tolua.createinstance(r.roleInfoType)
        r.sendMessage:Call(current.roleRefresh)
        current.roleRefreshSent = true
    end

    local function handleVictoryFailure(current)
        if current.victoryHandled then return end
        current.victoryHandled = true
        if current.victoryRequest ~= nil then
            r.requestCallback:Set(current.victoryRequest, nil, nil)
            r.abortRequest:Call(current.victoryRequest)
            for _, field in ipairs({r.httpRequests, r.httpTags, r.httpTimeouts}) do
                local dictionary = field:Get(nil)
                if dictionary ~= nil then dictionary:Remove(current.victoryRequest) end
            end
        end
        local protocol = r.getProtocol:Call()
        local pool = protocol ~= nil and r.messagePool:Get(protocol) or nil
        for _, entry in ipairs(entries(pool)) do
            if same(entry.value, current.victoryMessage) then pool:Remove(entry.key) end
        end
        local player = UserInfo.GetInstance():GetPlayer()
        local states = r.challengeState:Get(player, nil)
        if states ~= nil and current.initialChallengeState ~= nil then
            states[current.restriction - 1] = current.initialChallengeState
        end
        local collection = r.collection:Get(current.mode)
        local result = collection ~= nil and r.battleResult:Get(collection) or nil
        local loot = result ~= nil and r.resultLoot:Get(result) or nil
        if loot ~= nil then r.lootRmb:Set(loot, current.initialRmb or 0, nil) end
        local panel = UnityEngine.Object.FindObjectOfType(r.settlementType)
        if alive(panel) and number(r.settlementId:Get(panel)) == current.id then
            r.closeSettlement:Call(panel, nil)
        end
        -- A timeout can hide a committed response. Read the authoritative role
        -- again; cancellation is read-only if this attempt already won.
        pcall(cancelServerAttempt, current)
        pcall(refreshRole, current)
        NetworkAlertUI.TryShowWarningTipBox('石板结算未获服务器确认，正在同步；到账以服务器记录为准。')
        UnityEngine.Debug.Log('ONLINE_SLATE_SETTLEMENT_UNCONFIRMED id=' .. tostring(current.id))
    end

    local function checkPendingVictories(now)
        for index = #pendingWins, 1, -1 do
            local current = pendingWins[index]
            if not current.victoryHandled then
                local request = current.victoryRequest
                local status = request ~= nil and number(r.requestState:Get(request, nil)) or nil
                local response = request ~= nil and r.requestResponse:Get(request, nil) or nil
                local httpStatus = response ~= nil and number(r.statusCode:Get(response, nil)) or nil
                if status == 4 or status == 6 or status == 7 or
                        (status == 3 and httpStatus ~= nil and httpStatus >= 400) then
                    handleVictoryFailure(current)
                elseif status == 3 and httpStatus ~= nil and httpStatus >= 200 and httpStatus < 300 then
                    current.victoryHandled = true
                    pcall(refreshRole, current)
                elseif now - current.victoryBegan >= 90 then
                    handleVictoryFailure(current)
                end
            end
            if current.victoryHandled then table.remove(pendingWins, index) end
        end
    end

    local function finishAttempt(current)
        if current == nil or current.closed or current.outcome == 'win' then return end
        pcall(cancelServerAttempt, current)
    end

    local function abandon(current, reason)
        if current.closed then return end
        current.closed = true
        captureRequests(current)
        -- Clear callbacks before Abort: a late HTTP completion must not parse its
        -- stage JSON or restricted role into a later attempt.
        for request, _ in pairs(current.requests) do
            r.requestCallback:Set(request, nil, nil)
            r.abortRequest:Call(request)
            for _, field in ipairs({r.httpRequests, r.httpTags, r.httpTimeouts}) do
                local dictionary = field:Get(nil)
                if dictionary ~= nil then dictionary:Remove(request) end
            end
        end
        local protocol = r.getProtocol:Call()
        local pool = protocol ~= nil and r.messagePool:Get(protocol) or nil
        for _, entry in ipairs(entries(pool)) do
            if isAttemptMessage(entry.value, current) then pool:Remove(entry.key) end
        end
        local collection = r.collection:Get(current.mode)
        local root = collection ~= nil and r.rootMono:Get(collection) or nil
        if alive(root) then r.stopCoroutines:Call(root) end
        if alive(current.manager) and not same(current.manager, root) then
            r.stopCoroutines:Call(current.manager)
        end
        local cancelOK = pcall(cancelServerAttempt, current)
        UnityEngine.Debug.Log('ONLINE_SLATE_LOAD_ABORT id=' .. tostring(current.id) ..
            ' reason=' .. reason .. ' cancelSent=' .. tostring(cancelOK))
        if alive(root) and alive(r.rootNode:Get(collection)) and
                r.entityPool:Get(collection) ~= nil and r.dataStore:Get(collection) ~= nil then
            r.state:Set(current.mode, r.loadOutState)
            r.loadOut:Call(current.mode)
            NetworkAlertUI.HideBlockAnima()
            NetworkAlertUI.TryShowWarningTipBox('石板加载失败，已退出本次战斗，请重新进入。')
        else
            -- Early startup can lack the return-scene infrastructure. Offer the
            -- original explicit restart dialog; never fabricate a victory.
            NetworkAlertUI.ShowRestart('石板加载失败，请重新进入游戏。')
        end
    end

    local function markTemporaryLayout()
        local detail = UnityEngine.Object.FindObjectOfType(r.detailType)
        if not alive(detail) or not targets[number(r.detailId:Get(detail))] then return end
        local label = r.description:Get(detail)
        local note = '临时战斗配置：单房间占位，原关卡布局尚未取得。'
        if alive(label) and not tostring(label.text):find(note, 1, true) then
            label.text = tostring(label.text) .. '\n' .. note
        end
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25
        initialize()
        checkPendingVictories(now)
        markTemporaryLayout()
        local manager = r.getManager:Call()
        local mode = alive(manager) and r.currentMode:Get(manager) or nil
        if mode == nil or not targets[number(r.getId:Call(mode))] or
                number(r.getMode:Call(mode)) ~= 7 then
            finishAttempt(attempt)
            attempt = nil
            return
        end
        local state = number(r.state:Get(mode))
        local id = number(r.getId:Call(mode))
        if attempt ~= nil and (not same(attempt.mode, mode) or attempt.id ~= id) then
            finishAttempt(attempt)
            attempt = nil
        end
        if state == 1 or state == 2 or state == 0 then
            finishAttempt(attempt)
            attempt = nil
            return
        end
        if attempt == nil and (state == 3 or state == 4 or state == 6 or state == 7) then
            attempt = {mode=mode, manager=manager, id=number(r.getId:Call(mode)),
                restriction=number(r.getRestriction:Call(mode)), requests={},
                began=now, lastProgress=now, progress=-1, closed=false}
            local player = UserInfo.GetInstance():GetPlayer()
            local flags = r.challengeState:Get(player, nil)
            attempt.initialChallengeState = flags ~= nil and flags[attempt.restriction - 1] or false
            local collection = r.collection:Get(mode)
            local result = collection ~= nil and r.battleResult:Get(collection) or nil
            local loot = result ~= nil and r.resultLoot:Get(result) or nil
            attempt.initialRmb = loot ~= nil and number(r.lootRmb:Get(loot, nil)) or 0
        end
        if attempt == nil then return end
        if attempt.closed then return end
        captureRequests(attempt)
        if state == 8 or attempt.victoryRequest ~= nil then
            if attempt.outcome ~= 'win' then
                attempt.outcome, attempt.victoryBegan = 'win', now
                pendingWins[#pendingWins + 1] = attempt
            end
            return
        end
        if state == 9 or state == 5 then
            attempt.outcome = 'lose'
            pcall(cancelServerAttempt, attempt)
            return
        end
        if state ~= 3 and state ~= 4 then return end
        for request, _ in pairs(attempt.requests) do
            local status = number(r.requestState:Get(request, nil))
            local response = r.requestResponse:Get(request, nil)
            if status == 4 or status == 6 or status == 7 or
                    (status == 3 and response ~= nil and number(r.statusCode:Get(response, nil)) >= 400) then
                abandon(attempt, 'http-failed'); return
            end
        end
        local data = r.preloading:Get(mode)
        local progress = data ~= nil and number(r.progress:Call(data)) or 0
        if progress ~= nil and progress > attempt.progress + 0.001 then
            attempt.progress, attempt.lastProgress = progress, now
        end
        if now - attempt.lastProgress >= STALL_SECONDS or now - attempt.began >= MAX_LOAD_SECONDS then
            abandon(attempt, 'load-timeout')
        end
    end

    local initialized, initError = pcall(initialize)
    if initialized then
        UpdateBeat:Add(function()
            local okay, errorText = pcall(tick)
            if not okay and not failedOnce then
                failedOnce = true
                UnityEngine.Debug.LogError('ONLINE_SLATE_GUARD_FAILED ' .. tostring(errorText))
            end
        end)
        UnityEngine.Debug.Log('ONLINE_SLATE_LOADING_GUARD_READY')
    else
        UnityEngine.Debug.LogError('ONLINE_SLATE_GUARD_INIT_FAILED ' .. tostring(initError))
    end
end
