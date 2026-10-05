-- Local test build only. Append this block to the live lua.ab/init.lua when
-- tracing the Resource menu. It reads shop state and emits short text lines;
-- it does not change any UI element, inventory or network request.
do
    local ok, err = pcall(function()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')

        local shopType = typeof('NewShopPanelControl')
        local bigSetField = tolua.getfield(shopType, 'currentBigSetID', 65535)
        local currentGridField = tolua.getfield(shopType, 'currentGrid', 65535)
        local previous = ''
        local nextTick = 0

        local function node(shop, path)
            local object = shop.transform:Find(path)
            if object == nil then return 'missing' end
            return tostring(object.gameObject.activeSelf) .. '/' ..
                   tostring(object.gameObject.activeInHierarchy) .. '/' ..
                   tostring(object.childCount)
        end

        local function setState(id)
            local okay, state = pcall(function()
                local info = UserInfo.GetInstance():GetShopAllSets():GetShopSetByID(id)
                if info == nil then return 'missing' end
                return tostring(info.IsOpen) .. '/' ..
                       tostring(info:CanShow()) .. '/' ..
                       tostring(info.Shops.Count)
            end)
            if okay then return state end
            return 'lookup-error:' .. tostring(state)
        end

        UpdateBeat:Add(function()
            local success, reason = pcall(function()
                local now = UnityEngine.Time.realtimeSinceStartup
                if now < nextTick then return end
                nextTick = now + 0.5
                local shop = UnityEngine.Object.FindObjectOfType(shopType)
                if shop == nil or not shop.gameObject.activeInHierarchy then
                    previous = ''
                    return
                end
                local id = tostring(bigSetField:Get(shop))
                if id ~= '47000001' and id ~= '47000002' and
                   id ~= '47000003' and id ~= '47000004' then return end
                local grid = currentGridField:Get(shop)
                local gridState = grid == nil and 'missing' or
                    (tostring(grid.gameObject.activeInHierarchy) .. '/' ..
                     tostring(grid.transform.childCount))
                local line = 'big=' .. id ..
                    ' resource=' .. node(shop, 'Center/View/ResouceScrollView') ..
                    ' table=' .. node(shop, 'Center/Table') ..
                    ' grid=' .. gridState ..
                    ' set28=' .. setState(44000028) ..
                    ' set09=' .. setState(44000009)
                if line ~= previous then
                    UnityEngine.Debug.Log('RESOURCE_TAB_DIAG ' .. line)
                    previous = line
                end
            end)
            if not success then
                UnityEngine.Debug.LogError('RESOURCE_TAB_DIAG error ' .. tostring(reason))
                nextTick = UnityEngine.Time.realtimeSinceStartup + 5
            end
        end)
    end)
    if not ok then
        UnityEngine.Debug.LogError('RESOURCE_TAB_DIAG init_error ' .. tostring(err))
    end
end
