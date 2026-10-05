-- Keep the original witch level-up particles below their actual NGUI XP draw
-- calls. Prefab queues are only defaults: NGUI creates materials at runtime.
do
    local settlementType, rendererType, widgetType
    local cardsField, expField, effectField, drawField, meshField
    local dynamicMaterial, materialQueue, sharedMaterials, sortingLayer, sortingOrder
    local getChildren
    local current, bindings, savedMaterials, savedRenderers
    local nextSearch, nextError, reported = 0, 0, false

    local function alive(value)
        return value ~= nil and not value:Equals(nil)
    end

    local function number(value)
        return tonumber(tostring(value))
    end

    local function setup()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        -- These engine types live outside Assembly-CSharp in this Unity 2017
        -- player. Unregistered renderer types cannot be found until loaded.
        tolua.loadassembly('UnityEngine.CoreModule')
        tolua.loadassembly('UnityEngine.ParticleSystemModule')
        local function checkedType(name)
            local value = typeof(name)
            if value == nil then error('Missing runtime type: ' .. name) end
            return value
        end
        settlementType = checkedType('WaterBell.ProjX.View.Panel.SettlementUI')
        local cardType = checkedType('WaterBell.ProjX.View.Panel.SeetlementWatchmenUI')
        widgetType = checkedType('UIWidget')
        rendererType = checkedType('UnityEngine.ParticleSystemRenderer')
        cardsField = tolua.getfield(settlementType, 'servantPhotoList', 65535)
        expField = tolua.getfield(cardType, 'expBar', 65535)
        effectField = tolua.getfield(cardType, 'levelUpAnim', 65535)
        drawField = tolua.getfield(widgetType, 'drawCall', 65535)
        meshField = tolua.getfield(checkedType('UIDrawCall'), 'mRenderer', 65535)
        dynamicMaterial = tolua.getproperty(checkedType('UIDrawCall'), 'dynamicMaterial', 65535)
        materialQueue = tolua.getproperty(checkedType('UnityEngine.Material'), 'renderQueue', 65535)
        local renderType = checkedType('UnityEngine.Renderer')
        sharedMaterials = tolua.getproperty(renderType, 'sharedMaterials', 65535)
        sortingLayer = tolua.getproperty(renderType, 'sortingLayerID', 65535)
        sortingOrder = tolua.getproperty(renderType, 'sortingOrder', 65535)
        getChildren = tolua.getmethod(checkedType('UnityEngine.GameObject'),
            'GetComponentsInChildren', checkedType('System.Type'), checkedType('System.Boolean'))
        if settlementType == nil or rendererType == nil or widgetType == nil or
            cardsField == nil or expField == nil or effectField == nil or
            drawField == nil or meshField == nil or dynamicMaterial == nil or
            materialQueue == nil or sharedMaterials == nil or sortingLayer == nil or
            sortingOrder == nil or getChildren == nil or LateUpdateBeat == nil then
            error('Settlement effect reflection target is missing')
        end
    end

    local function restore()
        if savedMaterials ~= nil then
            for _, saved in pairs(savedMaterials) do
                if alive(saved.value) then materialQueue:Set(saved.value, saved.queue, nil) end
            end
        end
        if savedRenderers ~= nil then
            for _, saved in pairs(savedRenderers) do
                if alive(saved.value) then
                    sortingLayer:Set(saved.value, saved.layer, nil)
                    sortingOrder:Set(saved.value, saved.order, nil)
                end
            end
        end
        current, bindings, savedMaterials, savedRenderers = nil, nil, nil, nil
        reported = false
    end

    local function bind(panel)
        local cards = cardsField:Get(panel)
        if cards == nil or number(cards.Count) == 0 then return false end
        local found = {}
        for index = 0, number(cards.Count) - 1 do
            local card = cards[index]
            local exp = alive(card) and expField:Get(card) or nil
            local effect = alive(card) and effectField:Get(card) or nil
            if alive(exp) and alive(effect) then
                local widgets = getChildren:Call(exp.gameObject, widgetType, true)
                local renderers = getChildren:Call(effect.gameObject, rendererType, true)
                if number(widgets.Length) > 0 and number(renderers.Length) > 0 then
                    found[#found + 1] = { widgets = widgets, renderers = renderers }
                end
            end
        end
        if #found == 0 then return false end
        current, bindings, savedMaterials, savedRenderers = panel, found, {}, {}
        return true
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextError then return end
        if not alive(current) or not current.gameObject.activeInHierarchy then
            if current ~= nil then restore() end
            if now < nextSearch then return end
            nextSearch = now + 0.2
            local panel = UnityEngine.Object.FindObjectOfType(settlementType)
            if not alive(panel) or not panel.gameObject.activeInHierarchy or not bind(panel) then return end
        end

        -- Use the final materials and sorting settings of both the fill and
        -- its frame, after NGUI has built its draw calls. Never edit UI batches.
        local queue, layer, order
        for _, binding in ipairs(bindings) do
            for i = 0, number(binding.widgets.Length) - 1 do
                local widget = binding.widgets[i]
                if alive(widget) then
                    local draw = drawField:Get(widget)
                    if alive(draw) then
                        local material, mesh = dynamicMaterial:Get(draw, nil), meshField:Get(draw)
                        if alive(material) and alive(mesh) then
                            local q = number(materialQueue:Get(material, nil))
                            local l, o = number(sortingLayer:Get(mesh, nil)), number(sortingOrder:Get(mesh, nil))
                            if q ~= nil and q >= 2502 and (queue == nil or q < queue) then
                                queue, layer, order = q, l, o
                            end
                        end
                    end
                end
            end
        end
        if queue == nil or layer == nil or order == nil then return end
        local desired, before, previousOrder, count = queue - 1, nil, nil, 0
        for _, binding in ipairs(bindings) do
            for i = 0, number(binding.renderers.Length) - 1 do
                local renderer = binding.renderers[i]
                if alive(renderer) then
                    local key = tostring(renderer:GetInstanceID())
                    local oldLayer = number(sortingLayer:Get(renderer, nil))
                    local oldOrder = number(sortingOrder:Get(renderer, nil))
                    if savedRenderers[key] == nil then
                        savedRenderers[key] = { value = renderer, layer = oldLayer, order = oldOrder }
                    end
                    if oldLayer ~= layer then sortingLayer:Set(renderer, layer, nil) end
                    if oldOrder ~= order then sortingOrder:Set(renderer, order, nil) end
                    local materials = sharedMaterials:Get(renderer, nil)
                    for j = 0, number(materials.Length) - 1 do
                        local material = materials[j]
                        if alive(material) then
                            local id = tostring(material:GetInstanceID())
                            local oldQueue = number(materialQueue:Get(material, nil))
                            if savedMaterials[id] == nil then
                                savedMaterials[id] = { value = material, queue = oldQueue }
                            end
                            before = before or oldQueue
                            previousOrder = previousOrder or oldOrder
                            if oldQueue ~= desired then materialQueue:Set(material, desired, nil) end
                            count = count + 1
                        end
                    end
                end
            end
        end
        if not reported and count > 0 then
            reported = true
            UnityEngine.Debug.Log('ONLINE_SETTLEMENT_EFFECT_ORDER ui=' .. tostring(queue) ..
                ' before=' .. tostring(before) .. ' after=' .. tostring(desired) ..
                ' previousOrder=' .. tostring(previousOrder) .. ' uiOrder=' .. tostring(order) ..
                ' layer=' .. tostring(layer) .. ' renderers=' .. tostring(count))
        end
    end

    local ok, err = pcall(function()
        setup()
        LateUpdateBeat:Add(function()
            local success, failure = pcall(tick)
            if not success then
                restore()
                nextError = UnityEngine.Time.realtimeSinceStartup + 2
                UnityEngine.Debug.LogError('ONLINE_SETTLEMENT_EFFECT_ORDER ' .. tostring(failure))
            end
        end)
        UnityEngine.Debug.Log('ONLINE_SETTLEMENT_EFFECT_ORDER_READY 53')
    end)
    if not ok then UnityEngine.Debug.LogError('ONLINE_SETTLEMENT_EFFECT_ORDER_INIT ' .. tostring(err)) end
end
