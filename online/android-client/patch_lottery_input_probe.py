"""Append a read-only input/star-state probe to the test APK's init.lua."""

import hashlib

import UnityPy

MARKER = "-- BEGIN CODEX LOTTERY INPUT PROBE"
BLOCK = r'''
-- BEGIN CODEX LOTTERY INPUT PROBE
do
    local setupOk = pcall(function()
        local input = UnityEngine.Input
        local time = UnityEngine.Time
        local F = 65535
        local nextLog = 0
        local frames, touchFrames, mouseFrames, mouseUpFrames = 0, 0, 0, 0
        local runtimeErrorLogged = false
        local reflectOk = pcall(function()
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            tolua.loadassembly('Assembly-CSharp-firstpass')
        end)
        local function field(typeName, fieldName, instance)
            return tolua.getfield(typeof(typeName), fieldName, F):Get(instance)
        end
        local function starState()
            if not reflectOk then return 'module', -1, -1, -1, false, -1 end
            local stage = 'universe'
            local ok, stars, activeStars, connected, completed, drawCount = pcall(function()
                local universe = field('WaterBell.ProjX.View.Panel.LotteryUniverse', 'current', nil)
                local starTotal, activeTotal, connectTotal, complete = -1, -1, -1, false
                if universe and not universe:Equals(nil) then
                    stage = 'stars'
                    local array = field('WaterBell.ProjX.View.Panel.LotteryUniverse', 'stars', universe)
                    if array then
                        starTotal, activeTotal = array.Length, 0
                        for i = 0, array.Length - 1 do
                            local star = array[i]
                            if star and star.gameObject and star.gameObject.activeInHierarchy then
                                activeTotal = activeTotal + 1
                            end
                        end
                    end
                    stage = 'connected'
                    local list = field('WaterBell.ProjX.View.Panel.LotteryUniverse', 'connectStarList', universe)
                    if list then connectTotal = list.Count end
                    stage = 'complete'
                    complete = field('WaterBell.ProjX.View.Panel.LotteryUniverse', 'connectStarComplete', universe)
                end
                stage = 'drawInfo'
                local drawInfo = field('WaterBell.ProjX.View.Panel.LotteryNewPanel', 'currentDrawInfo', nil)
                local count = -1
                if drawInfo then
                    stage = 'drawCount'
                    count = field('WaterBell.ProjX.View.Panel.DrawInfo', 'drawCountType', drawInfo)
                end
                return starTotal, activeTotal, connectTotal, complete, count
            end)
            if not ok then return stage, -1, -1, -1, false, -1 end
            return 'ready', stars, activeStars, connected, completed, drawCount
        end
        local function readField(typeName, fieldName, instance)
            local ok, value = pcall(function() return field(typeName, fieldName, instance) end)
            if not ok then return false, nil end
            return true, value
        end
        local function readProperty(typeName, propertyName, instance)
            local ok, value = pcall(function()
                return tolua.getproperty(typeof(typeName), propertyName, F):Get(instance, {})
            end)
            if not ok then return false, nil end
            return true, value
        end
        local function readCanDraw(state)
            local ok, value = pcall(function()
                local typeArg = typeof('DrawArgu')
                local constructor = tolua.getconstructor(typeArg,
                    typeof('System.Int32'), typeof('System.Int64'))
                if not constructor then return 'constructor-missing' end
                local arg = constructor:Call(state, 0)
                local method = tolua.getmethod(
                    typeof('WaterBell.ProjX.Data.Entity.UserInfoHelper'),
                    'CanDraw', typeArg)
                if not method then return 'method-missing' end
                local errorText = method:Call(arg)
                if errorText == nil then return 'null' end
                return tostring(errorText):sub(1, 80):gsub('[\r\n]', ' ')
            end)
            return ok and tostring(value) or 'reflection-error'
        end
        local function freeLimit()
            local ok, value = pcall(function()
                local method = tolua.getmethod(
                    typeof('WaterBell.ProjX.Data.Entity.UserInfoHelper'),
                    'FreeGoldDrawMaxTime')
                return method and method:Call() or 'method-missing'
            end)
            return ok and tostring(value) or 'reflection-error'
        end
        local function extraState()
            if not reflectOk then return ' detail=module' end
            local parts = {}
            local infoOk, info = readField('WaterBell.ProjX.View.Panel.LotteryNewPanel',
                'currentDrawInfo', nil)
            parts[#parts + 1] = 'drawInfo=' .. (infoOk and tostring(info ~= nil) or 'error')
            if infoOk and info then
                local infoType = 'WaterBell.ProjX.View.Panel.DrawInfo'
                for _, name in ipairs({'state', 'isFree', 'canFree', 'cacheFree',
                    'freeCount', 'freeCountMax', 'needCurrency', 'drawCurrency',
                    'luckDrawType', 'cardPoolType'}) do
                    local ok, value = readField(infoType, name, info)
                    parts[#parts + 1] = name .. '=' .. (ok and tostring(value) or 'error')
                end
            end
            local panelOk, panel = readField('WaterBell.ProjX.View.Panel.LotteryNewPanel',
                'current', nil)
            local debugOk, debugValue = readField(
                'WaterBell.ProjX.View.Panel.LotteryNewPanel', 'IsDebug', nil)
            parts[#parts + 1] = 'LotteryIsDebug=' ..
                (debugOk and tostring(debugValue) or 'error')
            if panelOk and panel then
                local panelDebugOk, panelDebugValue = readField(
                    'WaterBell.ProjX.View.Panel.LotteryNewPanel', 'm_IsDebug', panel)
                parts[#parts + 1] = 'panelIsDebug=' ..
                    (panelDebugOk and tostring(panelDebugValue) or 'error')
                local playerOk, player = readField('WaterBell.ProjX.View.Panel.LotteryNewPanel',
                    'playerInfo', panel)
                parts[#parts + 1] = 'playerInfo=' .. (playerOk and tostring(player ~= nil) or 'error')
                if playerOk and player then
                    local playerType = 'WaterBell.ProjX.Data.Entity.ObservablePlayer'
                    for _, name in ipairs({'gold', 'diamond', 'drawCurrency',
                        'freeGoldDrawTime', 'freeRMBDrawTime', 'canFreeDraw',
                        'cdGoldDraw'}) do
                        local ok, value = readField(playerType, name, player)
                        parts[#parts + 1] = 'player_' .. name .. '=' ..
                            (ok and tostring(value) or 'error')
                    end
                    parts[#parts + 1] = 'freeGoldDrawMaxTime=' .. freeLimit()
                end
            else
                parts[#parts + 1] = 'panel=' .. (panelOk and 'absent' or 'error')
            end
            local universeOk, universe = readField('WaterBell.ProjX.View.Panel.LotteryUniverse',
                'current', nil)
            if universeOk and universe then
                local universeType = 'WaterBell.ProjX.View.Panel.LotteryUniverse'
                for _, name in ipairs({'state', 'drawView', 'OnConnectComplete',
                    'currentTweener', 'canDirectShowResult'}) do
                    local ok, value = readField(universeType, name, universe)
                    if name == 'drawView' or name == 'OnConnectComplete' or
                        name == 'currentTweener' then
                        parts[#parts + 1] = name .. '=' .. (ok and tostring(value ~= nil) or 'error')
                    else
                        parts[#parts + 1] = name .. '=' .. (ok and tostring(value) or 'error')
                    end
                end
                local viewOk, view = readField(universeType, 'drawView', universe)
                if viewOk and view then
                    local boundOk, bound = readField('ViewBase', '_bound', view)
                    local modelOk, model = readField('ViewBase', '_Model', view)
                    parts[#parts + 1] = 'drawViewBound=' ..
                        (boundOk and tostring(bound) or 'error')
                    parts[#parts + 1] = 'drawViewModel=' ..
                        (modelOk and tostring(model ~= nil) or 'error')
                    local targetOk, targets = readField('ViewBase',
                        'targetCommand', view)
                    parts[#parts + 1] = 'viewTargetCommandCount=' ..
                        (targetOk and targets and tostring(targets.Count) or
                            (targetOk and 'null' or 'error'))
                    if modelOk and model then
                        local commandOk, command = readField(
                            'DrawSystemManagerViewModelBase', '_Draw', model)
                        local modelBoundOk, modelBound = readField(
                            'ViewModel', '_isBound', model)
                        parts[#parts + 1] = 'drawCommand=' ..
                            (commandOk and tostring(command ~= nil) or 'error')
                        parts[#parts + 1] = 'drawModelBound=' ..
                            (modelBoundOk and tostring(modelBound) or 'error')
                        local mapOk, commandMap = readField('ViewModel',
                            '_commands', model)
                        parts[#parts + 1] = 'modelCommandMapCount=' ..
                            (mapOk and commandMap and tostring(commandMap.Count) or
                                (mapOk and 'null' or 'error'))
                        if mapOk and commandMap then
                            local containsOk, contains = pcall(function()
                                return commandMap:ContainsKey('Draw')
                            end)
                            parts[#parts + 1] = 'modelHasDrawKey=' ..
                                (containsOk and tostring(contains) or 'error')
                        end
                    end
                end
            else
                parts[#parts + 1] = 'universe=' .. (universeOk and 'absent' or 'error')
            end
            local serverOk, serverTime = readProperty('GUtilTime', 'serverTime', nil)
            local formatOk, serverFormat = readProperty('GUtilTime',
                'serverTimeFormat', nil)
            parts[#parts + 1] = 'serverTime=' ..
                (serverOk and tostring(serverTime) or 'error')
            parts[#parts + 1] = 'serverTimeFormat=' ..
                (formatOk and tostring(serverFormat) or 'error')
            local executorType = 'WaterBell.ProjX.Guide.GuideLessonExecutor'
            local executorOk, executor = readField(executorType, '_instance', nil)
            parts[#parts + 1] = 'guideExecutor=' ..
                (executorOk and tostring(executor ~= nil) or 'error')
            if executorOk and executor then
                local runningOk, running = readField(executorType,
                    'isLessonRunning', executor)
                parts[#parts + 1] = 'guideRunning=' ..
                    (runningOk and tostring(running) or 'error')
            end
            local recorderType = 'WaterBell.ProjX.Guide.GuideLessonProgressRecorder'
            local recorderOk, recorder = readField(recorderType, '_instance', nil)
            parts[#parts + 1] = 'guideRecorder=' ..
                (recorderOk and tostring(recorder ~= nil) or 'error')
            local triggerType = 'WaterBell.ProjX.Guide.DataModel.LessonTrigger'
            local guideIdOk, guideId = readField(triggerType,
                'GuideDraw_MainRecID', nil)
            parts[#parts + 1] = 'guideDrawID=' ..
                (guideIdOk and tostring(guideId) or 'error')
            if recorderOk and recorder then
                local mainOk, mainId = readField(recorderType, 'mainRecID', recorder)
                parts[#parts + 1] = 'mainRecID=' ..
                    (mainOk and tostring(mainId) or 'error')
                local triggerOk, trigger = pcall(function()
                    local method = tolua.getmethod(typeof(recorderType),
                        'GetLessonTriggerByRecID', typeof('System.Int32'))
                    return method and method:Call(recorder, guideId) or nil
                end)
                parts[#parts + 1] = 'guideDrawTrigger=' ..
                    (triggerOk and tostring(trigger ~= nil) or 'error')
                if triggerOk and trigger then
                    local recOk, recState = readField(triggerType,
                        '_recState', trigger)
                    parts[#parts + 1] = 'guideDrawRecState=' ..
                        (recOk and tostring(recState) or 'error')
                end
            end
            if infoOk and info and universeOk and universe then
                local stateOk, drawState = readField('WaterBell.ProjX.View.Panel.DrawInfo',
                    'state', info)
                if stateOk then parts[#parts + 1] = 'CanDraw=' .. readCanDraw(drawState) end
            end
            return table.concat(parts, ' ')
        end
        UpdateBeat:Add(function()
            local runtimeOk = pcall(function()
                frames = frames + 1
                local touchOk, touch = pcall(function() return input.touchCount end)
                local mouseOk, mouse = pcall(function() return input.GetMouseButton(0) end)
                local mouseUpOk, mouseUp = pcall(function() return input.GetMouseButtonUp(0) end)
                local simulateOk, simulate = pcall(function() return input.simulateMouseWithTouches end)
                if touchOk and type(touch) == 'number' and touch > 0 then touchFrames = touchFrames + 1 end
                if mouseOk and mouse then mouseFrames = mouseFrames + 1 end
                if mouseUpOk and mouseUp then mouseUpFrames = mouseUpFrames + 1 end
                local now = time.realtimeSinceStartup
                if now < nextLog then return end
                nextLog = now + 2
                local reflectStage, stars, activeStars, connected, completed, drawCount = starState()
                local detailOk, detail = pcall(extraState)
                UnityEngine.Debug.Log('WW-LOTTERY-LUA frames=' .. frames ..
                    ' touchFrames=' .. touchFrames .. ' mouseFrames=' .. mouseFrames ..
                    ' mouseUpFrames=' .. mouseUpFrames ..
                    ' touchApi=' .. tostring(touchOk) ..
                    ' mouseApi=' .. tostring(mouseOk) ..
                    ' mouseUpApi=' .. tostring(mouseUpOk) ..
                    ' simulated=' .. (simulateOk and tostring(simulate) or 'unknown') ..
                    ' reflectStage=' .. reflectStage ..
                    ' stars=' .. tostring(stars) ..
                    ' activeStars=' .. tostring(activeStars) ..
                    ' connected=' .. tostring(connected) ..
                    ' complete=' .. tostring(completed) ..
                    ' drawCount=' .. tostring(drawCount) ..
                    (detailOk and detail or ' detail=error'))
                frames, touchFrames, mouseFrames, mouseUpFrames = 0, 0, 0, 0
            end)
            if not runtimeOk and not runtimeErrorLogged then
                runtimeErrorLogged = true
                pcall(function() UnityEngine.Debug.LogError('WW-LOTTERY-LUA runtime-error') end)
            end
        end)
    end)
    if not setupOk then
        pcall(function() UnityEngine.Debug.LogError('WW-LOTTERY-LUA setup-error') end)
    end
end
-- END CODEX LOTTERY INPUT PROBE
'''


def _text(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def patch(raw: bytes) -> bytes:
    bundle = UnityPy.load(raw)
    before = {}
    changed = 0
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        script = tree["m_Script"]
        before[obj.path_id] = hashlib.sha256(_text(script).encode("utf-8")).digest()
        if tree["m_Name"] != "init.lua":
            continue
        text = _text(script)
        if MARKER in text or "UpdateBeat:Add(function()" not in text:
            raise ValueError("Unexpected or already patched init.lua")
        replacement = text + BLOCK
        tree["m_Script"] = replacement.encode("utf-8") if isinstance(script, bytes) else replacement
        obj.save_typetree(tree)
        changed += 1
    if changed != 1:
        raise ValueError("Expected one init.lua TextAsset")
    output = bundle.file.save(packer="original")
    verified = UnityPy.load(output)
    seen = 0
    for obj in verified.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        script = _text(tree["m_Script"])
        if tree["m_Name"] == "init.lua":
            if script.count(MARKER) != 1 or not script.endswith(BLOCK):
                raise ValueError("Probe did not round-trip")
            seen += 1
        elif hashlib.sha256(script.encode("utf-8")).digest() != before[obj.path_id]:
            raise ValueError("Another Lua TextAsset changed")
    if seen != 1:
        raise ValueError("Patched init.lua not found after save")
    return output
