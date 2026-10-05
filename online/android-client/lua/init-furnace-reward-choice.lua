-- Furnace only: distinct purchase identities and a direct final-slot completion.
-- Keep the original protobuf parser, wallet, confirmation panel and reward UI.
do
    local F, entry, ready, reported = 65535, nil, false, false
    local nextScan = 0
    local syncDirty, syncRequest, nextSync = false, nil, 0
    local phase = 'initializing'
    local r = {}
    local function alive(value) return value ~= nil and not value:Equals(nil) end
    local function active(value) return alive(value) and value.gameObject.activeInHierarchy end
    local function number(value) return tonumber(tostring(value)) end
    local function same(a, b) return a == b or (a ~= nil and b ~= nil and System.Object.ReferenceEquals(a, b)) end
    local function warning(text) NetworkAlertUI.TryShowWarningTipBox(text) end
    local function report(err)
        if not reported then
            reported = true
            local detail = tostring(err or 'unknown error'):gsub('[%c]', ' '):sub(1, 200)
            UnityEngine.Debug.LogError('ONLINE_FURNACE_REWARD_CHOICE_FAILED phase=' .. phase .. ' ' .. detail)
        end
    end

    local function setup()
        phase = 'setup.reflection'
        require 'tolua.reflection'
        phase = 'setup.assembly'
        tolua.loadassembly('Assembly-CSharp')
        local function checked(key, target, lookup)
            phase = 'setup.' .. key
            local okay, value = pcall(lookup)
            if not okay then error('lookup ' .. key .. ' ' .. target .. ': ' .. tostring(value), 0) end
            if value == nil then error('missing ' .. key .. ' ' .. target, 0) end
            return value
        end
        local function kind(key, name)
            return checked(key, name, function() return typeof(name) end)
        end
        local function field(key, owner, name)
            return checked(key, tostring(owner) .. '.' .. name,
                function() return tolua.getfield(owner, name, F) end)
        end
        local function property(key, owner, name)
            return checked(key, tostring(owner) .. '.' .. name,
                function() return tolua.getproperty(owner, name, F) end)
        end
        local function method(key, owner, name, types)
            return checked(key, tostring(owner) .. '.' .. name, function()
                if types == nil then return tolua.gettypemethod(owner, name, F) end
                return tolua.gettypemethod(owner, name, F, System.Type.DefaultBinder, types, nil)
            end)
        end
        r.panel = kind('panelType', 'WaterBell.ProjX.View.Panel.SettlementBuyItemPanel')
        local mode = kind('modeType', 'WaterBell.ProjX.Playmode.WeaponDailyMode')
        local baseMode = kind('baseModeType', 'WaterBell.ProjX.Playmode.BasicPlayMode')
        local basePanel = kind('basePanelType', 'WaterBell.ProjX.View.Panel.UIPanelBase')
        local container = kind('containerType', 'WaterBell.ProjX.View.Panel.UIPanelSingleContainer')
        local row = kind('rowType', 'WaterBell.ProjX.View.Panel.SBIP_ItemData')
        local data = kind('dataType', 'WaterBell.ProjX.View.Panel.UIDataBase')
        r.message = kind('messageType', 'WaterBell.ProjX.Data.NetIO.ChooseMaterials')
        r.inventory = kind('inventoryType', 'WaterBell.ProjX.Data.NetIO.BackpackGetAllItemsLogic')
        local messageBase = kind('messageBaseType', 'WaterBell.ProjX.Data.NetIO.NetMsgBase')
        local manager = kind('managerType', 'WaterBell.ProjX.Data.NetIO.ProtocolManager')
        local battleResult = kind('battleResultType', 'BattleResult')
        local transform = kind('transformType', 'UnityEngine.Transform')
        local guid = kind('guidType', 'System.Guid')
        for _, name in ipairs({'chooseButton','rawList','buyStateList','mode','isSelectRunning',
                               'itemContainer','currentRandomLootID'}) do
            r[name] = field(name, r.panel, name)
        end
        r.args = field('args', messageBase, 'argumentDic')
        r.send = method('send', manager, 'SendNormalMassage', {messageBase})
        r.manager = method('manager', manager, 'GetInstance')
        r.enough = method('enough', mode, 'IsEnoughDiamondGetWeaponMaterail')
        r.price = method('price', mode, 'GetCurrentWeaponMaterailNeedDiamond')
        r.times = property('times', mode, 'ChooseMateriaTime')
        r.result = method('result', baseMode, 'GetBattleResult')
        r.resultID = field('resultID', battleResult, 'currentRandomLootID')
        r.nativeSuccess = method('nativeSuccess', r.panel, '<OnBuyButtonClick>m__5')
        r.select = method('select', r.panel, '<GetChooseResult>m__3', {transform})
        r.complete = method('complete', r.panel, '<GetChooseResult>m__4', {transform})
        r.children = property('children', container, 'Children')
        r.rowData = property('rowData', basePanel, 'Data')
        r.rowID = field('rowID', data, 'id')
        r.isBuy = field('isBuy', row, 'isBuy')
        r.guid = method('guid', guid, 'NewGuid')
        ready = true
        reported = false
        phase = 'ready'
        UnityEngine.Debug.LogWarning('ONLINE_FURNACE_REWARD_CHOICE_READY 155')
    end

    local function syncInventory(now)
        if not ready or not syncDirty or syncRequest ~= nil or now < nextSync then return end
        phase = 'inventory.create'
        local request = tolua.createinstance(r.inventory)
        syncDirty, syncRequest, nextSync = false, request, now + 0.1
        request.OnSuccessfulDelegate = function()
            if same(syncRequest, request) then syncRequest = nil
            else syncDirty = true end
            -- The original full parser has already replaced item quantities.
            -- A reward parsed while this request was in flight sets syncDirty
            -- again, so the next scan fetches a newer authoritative snapshot.
        end
        local function failure()
            if not same(syncRequest, request) then return end
            syncDirty, syncRequest = true, nil
            nextSync = UnityEngine.Time.realtimeSinceStartup + 5
        end
        request.OnFailedDelegate = failure
        request.OnErrorDelegate = failure
        request.OnTimeOutDelegate = failure
        request.OnInternalErrorDelegate = failure
        phase = 'inventory.send'
        local okay, err = pcall(function() r.send:Call(r.manager:Call(), request) end)
        if not okay then failure(); report(err) end
    end

    local function queueInventorySync()
        syncDirty = true
        local okay, err = pcall(syncInventory, UnityEngine.Time.realtimeSinceStartup)
        if not okay then
            nextSync = UnityEngine.Time.realtimeSinceStartup + 5
            report(err)
        end
    end

    local function pool(panel)
        local raw, bought = r.rawList:Get(panel), r.buyStateList:Get(panel)
        if raw == nil or bought == nil or raw.Count ~= bought.Count or raw.Count == 0 then return nil end
        local ids, remaining, unique = {}, 0, {}
        for index = 0, raw.Count - 1 do
            local id = tostring(raw[index])
            if unique[id] then return nil end
            unique[id], ids[#ids + 1] = true, id
            if not bought[index] then remaining = remaining + 1 end
        end
        table.sort(ids)
        return table.concat(ids, ','), remaining
    end

    local function finalTarget(panel, wanted)
        local container = r.itemContainer:Get(panel)
        if not alive(container) then return nil end
        local children = r.children:Get(container, nil)
        if children == nil then return nil end
        for index = 0, children.Count - 1 do
            local child = children[index]
            local data = alive(child) and r.rowData:Get(child, nil) or nil
            if data ~= nil and tostring(r.rowID:Get(data)) == tostring(wanted) and not r.isBuy:Get(data) then
                return child.transform
            end
        end
        return nil
    end

    local function release(current)
        if alive(current.panel) then r.isSelectRunning:Set(current.panel, false) end
        current.sending = false
    end

    local function purchase(current, signature, remaining, price)
        phase = 'purchase.validate'
        if current ~= entry or not active(current.panel) or current.sending then return end
        local currentPool, count = pool(current.panel)
        if currentPool ~= signature or count ~= remaining or count == 0 then return end
        local mode = r.mode:Get(current.panel)
        if mode == nil or number(r.enough:Call(mode)) ~= 0 then warning('钻石不足'); return end
        if number(r.price:Call(mode)) ~= price then return end
        local pending = current.pending
        if pending == nil then
            pending = {identity='furnace-' .. tostring(r.guid:Call()), signature=signature}
            current.pending = pending
        elseif pending.signature ~= signature then return end
        phase = 'purchase.create'
        local request = tolua.createinstance(r.message)
        local args = r.args:Get(request)
        args['idempotency'], args['choicePool'] = pending.identity, signature
        current.request = request
        current.sending = true
        r.isSelectRunning:Set(current.panel, true)
        request.OnSuccessfulDelegate = function()
            -- Native ChooseMaterials parses an additive local item update even
            -- for a replay. Always refresh, including completed late replies.
            queueInventorySync()
            if pending.completed then return end
            pending.completed = true
            current.pending, current.sending = nil, false
            -- Unlike native GetchooseMaterial, advance the local wallet and
            -- purchase count only after the authoritative purchase succeeded.
            local player = UserInfo.GetInstance():GetPlayer()
            player:ConsumeDiamond(price)
            r.times:Set(mode, number(r.times:Get(mode, nil)) + 1, nil)
            if not active(current.panel) then return end
            local result = r.result:Call(mode)
            local wanted = r.resultID:Get(result)
            if remaining == 1 then
                local target = finalTarget(current.panel, wanted)
                if not alive(target) then
                    phase = 'purchase.finalTarget'; release(current); report('last-slot target missing'); return
                end
                -- Native PlayAnim gives a sole target a zero-second tween and
                -- installs callbacks afterwards. Complete this one-slot case
                -- through the exact native mask/buy-state/refresh callbacks.
                r.currentRandomLootID:Set(current.panel, wanted)
                r.select:Call(current.panel, target)
                r.complete:Call(current.panel, target)
            else
                r.nativeSuccess:Call(current.panel)
            end
        end
        local function failure()
            if pending.completed or not same(current.request, request) then return end
            release(current)
            -- Keep the identity for an uncertain response so another tap can
            -- replay the same transaction without charging again.
        end
        request.OnFailedDelegate = failure
        request.OnErrorDelegate = failure
        request.OnTimeOutDelegate = failure
        request.OnInternalErrorDelegate = failure
        phase = 'purchase.send'
        local okay, err = pcall(function() r.send:Call(r.manager:Call(), request) end)
        if not okay then failure(); report(err) end
    end

    local function choose(current)
        if current ~= entry or not active(current.panel) or current.sending or
                r.isSelectRunning:Get(current.panel) then return end
        local signature, remaining = pool(current.panel)
        if signature == nil or remaining == 0 then return end
        local mode = r.mode:Get(current.panel)
        if mode == nil then return end
        if number(r.enough:Call(mode)) ~= 0 then warning('钻石不足'); return end
        local price = number(r.price:Call(mode))
        if price == nil or price <= 0 then return end
        WaterBell.ProjX.View.Panel.ConfirmPanel.GetInstance():OpenPanel('购买额外奖励',
            '花费' .. tostring(price) .. '钻石随机获得1个刻印碎片',
            function()
                local okay, err = pcall(purchase, current, signature, remaining, price)
                if not okay then release(current); report(err) end
            end, nil)
    end

    local function restore()
        if entry == nil then return end
        if alive(entry.button) and entry.button.onClick == nil then entry.button.onClick = entry.originalClick end
        if alive(entry.listener) then entry.listener.onClick = entry.originalListener end
        entry = nil
    end

    local function tick()
        if not ready then setup() end
        syncInventory(UnityEngine.Time.realtimeSinceStartup)
        phase = 'scan.panel'
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(r.panel)
        if not active(panel) then restore(); return end
        local button = r.chooseButton:Get(panel)
        if not alive(button) then return end
        if entry ~= nil and (not same(entry.panel, panel) or not same(entry.button, button)) then restore() end
        if entry == nil then
            local listener = UIEventListener.Get(button.gameObject)
            entry = {panel=panel, button=button, listener=listener,
                originalClick=button.onClick, originalListener=listener.onClick, sending=false}
            local current = entry
            entry.gate = function()
                phase = 'click.choose'
                local okay, err = pcall(choose, current)
                if not okay then report(err) end
            end
        elseif button.onClick ~= nil then
            entry.originalClick = button.onClick
        end
        button.onClick = nil
        entry.listener.onClick = entry.gate
    end

    UpdateBeat:Add(function()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextScan then return end
        nextScan = now + 0.1
        local okay, err = pcall(tick)
        if not okay then
            nextScan = now + 5
            pcall(restore); report(err)
        end
    end)
end
