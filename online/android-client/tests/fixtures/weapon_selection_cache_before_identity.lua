-- WWR weapon selection cache persistence v1.
-- Native SwitchWeapon changes the live team but SelectCards reloads weapon cache.
-- Persist a validated change inside the click event, before another UI action.
do
    local stateKey = '__WWRWeaponSelectionCachePersistenceV1'
    if rawget(_G, stateKey) == nil then
        local selectorType, buttonField, weaponField, boxIndexField, unlockField
        local currentField, dataField, dataModeField, restrictedField
        local sidField, ridField, selectedWeaponField
        local getManager, getMode, cacheSave, getWeaponData
        local weaponIDProperty, servantIDProperty, unlockedProperty
        local entries, reported = {}, {}

        local function log(message)
            pcall(function() UnityEngine.Debug.Log('WWR_WEAPON_CACHE_' .. message) end)
        end

        local function reportOnce(reason)
            if not reported[reason] then
                reported[reason] = true
                log(reason)
            end
        end

        local function alive(value)
            return value ~= nil and not value:Equals(nil)
        end

        local function same(left, right)
            return left == right or (left ~= nil and right ~= nil and left:Equals(right))
        end

        local function sameID(left, right)
            return left ~= nil and right ~= nil and tostring(left) == tostring(right)
        end

        local function positiveID(value)
            local number = value ~= nil and tonumber(tostring(value)) or nil
            return number ~= nil and number > 0
        end

        local function isTrue(value)
            return value == true or tostring(value) == 'True' or tostring(value) == 'true'
        end

        local function currentMode()
            -- Match SelectWeaponSingle.SwitchWeapon's actual native getter chain.
            local manager = getManager:Call()
            if not alive(manager) then return nil end
            return getMode:Call(manager)
        end

        local function arraysAt(mode, slot)
            local sids = sidField:Get(mode)
            local rids = ridField:Get(mode)
            local weapons = selectedWeaponField:Get(mode)
            if sids == nil or rids == nil or weapons == nil or slot < 0 or
                    slot >= sids.Length or slot >= rids.Length or slot >= weapons.Length then
                return nil
            end
            return sids[slot], rids[slot], weapons[slot]
        end

        local function snapshot(entry)
            if not entry.ready or not alive(entry.selector) or not alive(entry.button) or
                    not isTrue(unlockField:Get(entry.selector)) then return nil end
            local target = weaponField:Get(entry.selector)
            if not positiveID(target) then return nil end
            local panel = currentField:Get(nil)
            if not alive(panel) then return nil end
            local data = dataField:Get(panel)
            if data == nil then return nil end
            local mode = currentMode()
            if mode == nil or not same(dataModeField:Get(data), mode) then return nil end
            local restricted = restrictedField:Get(data)
            if restricted == nil then return nil end
            local slot = tonumber(boxIndexField:Get(entry.selector)) - restricted.Count
            if slot ~= math.floor(slot) then return nil end
            local sid, rid, oldWeapon = arraysAt(mode, slot)
            if not positiveID(sid) or rid == nil or oldWeapon == nil then return nil end
            return { mode = mode, slot = slot, sid = sid, rid = rid,
                     target = target, oldWeapon = oldWeapon }
        end

        local function persist(before)
            if before == nil then return end
            local mode = currentMode()
            if mode == nil or not same(mode, before.mode) then
                log('SKIPPED_MODE_CHANGED')
                return
            end
            local sid, rid, weapon = arraysAt(mode, before.slot)
            if not sameID(sid, before.sid) or not sameID(rid, before.rid) or
                    not sameID(weapon, before.target) then
                log('SKIPPED_NATIVE_REJECTED')
                return
            end
            if sameID(before.oldWeapon, weapon) then return end
            -- Native SwitchWeapon checks this same owned weapon collection/unlock.
            -- Recheck after its callback; never cache a locked or unrelated weapon.
            local owned = getWeaponData:Call(before.sid, before.target)
            if owned == nil or
                    not sameID(weaponIDProperty:Get(owned, nil), before.target) or
                    not sameID(servantIDProperty:Get(owned, nil), before.sid) or
                    not isTrue(unlockedProperty:Get(owned, nil)) then
                log('SKIPPED_NOT_UNLOCKED')
                return
            end
            cacheSave:Call(mode)
            log('SAVED')
        end

        local function detach(entry)
            entry.ready, entry.before = false, nil
            if entry.list ~= nil then
                if entry.preDelegate ~= nil then entry.list:Remove(entry.preDelegate) end
                if entry.postDelegate ~= nil then entry.list:Remove(entry.postDelegate) end
            end
        end

        local function orderCallbacks(entry)
            local list = entry.list
            if not list:Contains(entry.preDelegate) or not list:Contains(entry.postDelegate) then
                return false
            end
            -- Preserve every original delegate and its relative order. Only move
            -- our observers, including when native UI replaces/rebinds callbacks.
            if not same(list[0], entry.preDelegate) then
                list:Remove(entry.preDelegate)
                list:Insert(0, entry.preDelegate)
            end
            if not same(list[list.Count - 1], entry.postDelegate) then
                list:Remove(entry.postDelegate)
                list:Add(entry.postDelegate)
            end
            return true
        end

        local function bind(selector)
            local button = buttonField:Get(selector)
            if not alive(button) or button.onClick == nil then return end
            local id, list = selector:GetInstanceID(), button.onClick
            local entry = entries[id]
            if entry ~= nil then
                if same(entry.selector, selector) and same(entry.button, button) and
                        same(entry.list, list) and entry.ready and orderCallbacks(entry) then return end
                detach(entry)
                entries[id] = nil
            end
            -- Awake installs native SwitchWeapon first. Do not attach to a list
            -- that has not received its native callback yet.
            if list.Count == 0 then return end
            entry = { selector = selector, button = button, list = list, ready = false }
            entries[id] = entry
            local success = pcall(function()
                entry.preCallback = EventDelegate.Callback(function()
                    entry.before = nil
                    local ok, before = pcall(snapshot, entry)
                    if ok then entry.before = before else reportOnce('SNAPSHOT_FAILED') end
                end)
                entry.postCallback = EventDelegate.Callback(function()
                    local before = entry.before
                    entry.before = nil
                    -- Native hides/reuses the selector during SwitchWeapon. Use
                    -- the pre-click fields; do not require it still to be active.
                    if entry.ready then
                        local ok = pcall(persist, before)
                        if not ok then reportOnce('SAVE_FAILED') end
                    end
                end)
                entry.preDelegate = EventDelegate.Add(list, entry.preCallback)
                if entry.preDelegate == nil then error('Missing pre-click delegate') end
                list:Remove(entry.preDelegate)
                list:Insert(0, entry.preDelegate)
                entry.postDelegate = EventDelegate.Add(list, entry.postCallback)
                if entry.postDelegate == nil then error('Missing post-click delegate') end
                entry.ready = true
            end)
            if success then
                log('BOUND')
            else
                pcall(detach, entry)
                entries[id] = nil
                reportOnce('BIND_FAILED')
            end
        end

        local function discover()
            for id, entry in pairs(entries) do
                if not alive(entry.selector) or not alive(entry.button) then
                    pcall(detach, entry)
                    entries[id] = nil
                end
            end
            -- Discovery runs every frame to catch newly created controls before
            -- the first release/click. It never reads or persists team selection.
            local selectors = UnityEngine.Object.FindObjectsOfType(selectorType)
            if selectors == nil then return end
            for index = 0, selectors.Length - 1 do
                local selector = selectors[index]
                if alive(selector) then bind(selector) end
            end
        end

        local function setup()
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            selectorType = typeof('SelectWeaponSingle')
            local managerType = typeof('WaterBell.ProjX.Playmode.PlayModeMngr')
            local modeType = typeof('WaterBell.ProjX.Playmode.BasicPlayMode')
            local panelType = typeof('WaterBell.ProjX.View.Panel.SelectCardsController')
            local dataType = typeof('SelectCardsData')
            local ownedType = typeof('WaterBell.ProjX.Data.Entity.ObservableServantWeapon')
            buttonField = tolua.getfield(selectorType, 'weaponBtn', 65535)
            weaponField = tolua.getfield(selectorType, 'wp', 65535)
            boxIndexField = tolua.getfield(selectorType, 'weaponBoxIndex', 65535)
            unlockField = tolua.getfield(selectorType, 'unlock', 65535)
            currentField = tolua.getfield(panelType, 'current', 65535)
            dataField = tolua.getfield(panelType, 'currentData', 65535)
            dataModeField = tolua.getfield(dataType, 'currmode', 65535)
            restrictedField = tolua.getfield(dataType, 'restrictedServants', 65535)
            sidField = tolua.getfield(modeType, 'selectedSvCardIDArr', 65535)
            ridField = tolua.getfield(modeType, 'selectedSvBelongToRoleArr', 65535)
            selectedWeaponField = tolua.getfield(modeType, 'selectedSvWeaponIDArr', 65535)
            getManager = tolua.gettypemethod(managerType, 'GetExistedInstance', 65535)
            getMode = tolua.gettypemethod(managerType, 'GetCurrPlayMode', 65535)
            cacheSave = tolua.gettypemethod(modeType, 'CacheSave', 65535)
            getWeaponData = tolua.gettypemethod(dataType, 'GetWeaponData', 65535)
            weaponIDProperty = tolua.getproperty(ownedType, 'WeaponCardID', 65535)
            servantIDProperty = tolua.getproperty(ownedType, 'ServantCardID', 65535)
            unlockedProperty = tolua.getproperty(ownedType, 'IsUnLock', 65535)
            local required = { selectorType, managerType, modeType, panelType, dataType, ownedType,
                buttonField, weaponField, boxIndexField, unlockField, currentField, dataField,
                dataModeField, restrictedField, sidField, ridField, selectedWeaponField,
                getManager, getMode, cacheSave, getWeaponData,
                weaponIDProperty, servantIDProperty, unlockedProperty }
            for index = 1, 24 do
                if required[index] == nil then error('Missing weapon cache reflection target') end
            end
            if EventDelegate == nil or EventDelegate.Callback == nil or EventDelegate.Add == nil then
                error('Missing native EventDelegate bridge')
            end
        end

        local success = pcall(function()
            setup()
            UpdateBeat:Add(function()
                local ok = pcall(discover)
                if not ok then reportOnce('DISCOVERY_FAILED') end
            end)
            rawset(_G, stateKey, true)
            log('READY')
        end)
        if not success then reportOnce('INIT_FAILED') end
    end
end
