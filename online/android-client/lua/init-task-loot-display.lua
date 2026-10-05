-- The preserved ARM64 UserInfoHelper.LootToDrawResultData emits LootGuildInc
-- twice (0x3f91db0 and 0x3f920b0). Keep one display row, not their sum.
-- Native AddLoot and the authoritative server wallet remain untouched.
do
    local initialized, taskType, containerType, rawType, lootType
    local kinds, fields = {}, {}
    local nextRetry, lastError = 0, -100
    local bulkOpenPanel, bulkOpenAt

    local function visible(panel)
        return panel ~= nil and not panel:Equals(nil) and panel.gameObject.activeInHierarchy
    end

    local function setup()
        if initialized then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        taskType = typeof('WaterBell.ProjX.View.Panel.TaskPanelController')
        containerType = typeof('WaterBell.ProjX.View.Panel.UIPanelSingleContainer')
        rawType = typeof('WaterBell.ProjX.View.Panel.UIRawResData')
        lootType = typeof('WaterBell.ProjX.View.Panel.UILootItemData')
        fields.count = tolua.getproperty(typeof('System.Collections.ICollection'), 'Count', 65535)
        fields.item = tolua.getmethod(typeof('System.Collections.IList'), 'get_Item', typeof('System.Int32'))
        fields.remove = tolua.getmethod(typeof('System.Collections.IList'), 'RemoveAt', typeof('System.Int32'))
        fields.originType = tolua.getfield(rawType, 'OriginType', 65535)
        fields.originID = tolua.getfield(rawType, 'OriginID', 65535)
        fields.originValue = tolua.getfield(rawType, 'OriginValue', 65535)
        fields.originNum = tolua.getfield(rawType, 'OriginNum', 65535)
        fields.lootCount = tolua.getfield(lootType, 'count', 65535)
        fields.children = tolua.getproperty(containerType, 'Children', 65535)
        fields.grid = tolua.getfield(containerType, 'grid', 65535)
        fields.waiting = tolua.getmethod(typeof('UnityEngine.MonoBehaviour'), 'IsInvoking', typeof('System.String'))
        fields.invalidate = tolua.getmethod(typeof('UIWidget'), 'Invalidate', typeof('System.Boolean'))
        for _, name in ipairs({'GetAwardsPanel', 'GetLootsPanel'}) do
            local kind = typeof('WaterBell.ProjX.View.Panel.' .. name)
            kinds[#kinds + 1] = {
                kind = kind,
                list = tolua.getfield(kind, 'dataList', 65535),
                container = tolua.getfield(kind, 'lootContainer', 65535),
                itemCount = tolua.getfield(kind, 'itemCount', 65535),
                bulk = name == 'GetLootsPanel',
                background = tolua.getfield(kind, name == 'GetLootsPanel' and 'box' or 'bgAnim', 65535),
            }
        end
        for name, field in pairs(fields) do
            if field == nil then error('Task loot reflection missing: ' .. name) end
        end
        for _, kind in ipairs(kinds) do
            if kind.list == nil or kind.container == nil or kind.itemCount == nil then
                error('Task loot panel fields unavailable')
            end
        end
        initialized = true
        UnityEngine.Debug.LogWarning('ONLINE_TASK_LOOT_READY 139')
    end

    local function count(list) return fields.count:Get(list, nil) end
    local function item(list, index) return fields.item:Call(list, index) end

    local function repair(panel, kind)
        local list = kind.list:Get(panel)
        local container = kind.container:Get(panel)
        if list == nil or not visible(container) then return end
        local children = fields.children:Get(container, nil)
        local length = count(list)
        if children == nil then return end
        -- Bulk: original OpenPanel invokes creation after 0.5 seconds. Adjust
        -- only its input list while the native container is still empty.
        -- Single: children already exist, but no sequence exists until the
        -- original 1.5-second invocation. Never remove a tween's live target.
        if kind.bulk then
            if count(children) ~= 0 then return end
        elseif not fields.waiting:Call(panel, 'ShowLootOneByOne') or count(children) ~= length then
            return
        end
        local seen, remove = {}, {}
        for index = 0, length - 1 do
            local data = item(list, index)
            local resType = tostring(fields.originType:Get(data))
            if resType == 'Guild' or resType == '19' then
                local key = tostring(fields.originID:Get(data)) .. '/' ..
                    tostring(fields.originValue:Get(data)) .. '/' ..
                    tostring(fields.originNum:Get(data)) .. '/' ..
                    tostring(fields.lootCount:Get(data))
                if seen[key] then remove[#remove + 1] = index else seen[key] = true end
            end
        end
        if #remove == 0 then return end
        for index = #remove, 1, -1 do
            local duplicate = remove[index]
            if not kind.bulk then
                local duplicateObject = item(children, duplicate).gameObject
                duplicateObject:SetActive(false)
                fields.remove:Call(children, duplicate)
                UnityEngine.Object.Destroy(duplicateObject)
            end
            fields.remove:Call(list, duplicate)
        end
        local oldItemCount = tonumber(tostring(kind.itemCount:Get(panel)))
        local newItemCount = math.max(1, math.min(5, count(list)))
        kind.itemCount:Set(panel, newItemCount)
        local background = kind.background:Get(panel)
        if background ~= nil and not background:Equals(nil) then
            if kind.bulk then
                local length = count(list)
                background:SetDimensions(math.max(800, 200 + 150 * math.min(length, 6)),
                    200 + 150 * math.min(3, math.floor(length / 7) + 1))
            elseif oldItemCount ~= newItemCount then
                background:Play('box_' .. tostring(newItemCount), 0, 0)
            end
        end
        local grid = fields.grid:Get(container)
        if grid ~= nil and not grid:Equals(nil) then grid:Reposition() end
        UnityEngine.Debug.LogWarning('ONLINE_TASK_LOOT_DEDUP ' .. tostring(#remove))
    end

    local function reopenBackground(panel, kind, now)
        if bulkOpenPanel ~= panel then
            bulkOpenPanel, bulkOpenAt = panel, now + 0.5
        end
        if bulkOpenAt == nil or now < bulkOpenAt then return end
        bulkOpenAt = nil
        local background = kind.background:Get(panel)
        if background == nil or background:Equals(nil) or background.alpha <= 0 then return end
        -- Open animates the sprite color directly; reopening can leave NGUI's
        -- visibility/finalAlpha cache at the previous Close result. Recompute
        -- that cache only after the preserved 0.333-second opening has finished.
        -- This never sets parent/self alpha, depth, animation, or reward count.
        if background.finalAlpha == 0 then
            fields.invalidate:Call(background, false)
            UnityEngine.Debug.LogWarning('ONLINE_TASK_LOOT_BACKGROUND_REOPENED ' .. tostring(background.finalAlpha))
        end
    end

    UpdateBeat:Add(function()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextRetry then return end
        local ok, err = pcall(function()
            setup()
            if not visible((WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(taskType)) then return end
            for _, kind in ipairs(kinds) do
                local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(kind.kind)
                if visible(panel) then
                    if kind.bulk then reopenBackground(panel, kind, now) end
                    repair(panel, kind)
                elseif kind.bulk then
                    bulkOpenPanel, bulkOpenAt = nil, nil
                end
            end
        end)
        if not ok then
            nextRetry = now + 5
            if now - lastError >= 30 then
                lastError = now
                UnityEngine.Debug.LogError('ONLINE_TASK_LOOT_ERROR ' .. tostring(err))
            end
        end
    end)
end
