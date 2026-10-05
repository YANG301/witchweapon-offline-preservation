-- Restore the original ShopItemInfo slider after the offline author's native
-- GetMaxNumber was replaced with a constant one. Keep the original widgets,
-- price labels, drag callbacks, BuyAction and authoritative count protocol.
do
    local initialized, itemType, panelType, sourceType
    local fields, wallet, sourceGood, drag, sourceNum = {}, nil, nil, nil, nil
    local nextCheck, lastErrorAt = 0, -100
    local lastIdentity, lastSignature, previousMax = nil, nil, 1
    local phase = 'initializing'
    local retryAt = 0

    local function alive(value) return value ~= nil and not value:Equals(nil) end
    local function number(value) return tonumber(tostring(value)) end
    local function reset() lastIdentity, lastSignature, previousMax = nil, nil, 1 end
    local function setup()
        if initialized then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        itemType = typeof('ShopItemInfo')
        panelType = typeof('NewShopPanelControl')
        sourceType = typeof('WaterBell.ProjX.Data.Entity.ShopGood')
        for _, name in ipairs({'itemId','shopId','setId','price1','price2','num1','num2',
                              'maxNumber','slider','sliderWidget'}) do
            fields[name] = tolua.getfield(itemType, name, 65535)
            if fields[name] == nil then error('Shop quantity field missing: ' .. name) end
        end
        fields.detail = tolua.getfield(panelType, 'ShopItemInfoView', 65535)
        fields.bigSet = tolua.getfield(panelType, 'currentBigSetID', 65535)
        -- This ToLua version derives Call's argument count from the lookup
        -- types, not MethodInfo. Preserve the private method's int signature.
        wallet = tolua.gettypemethod(itemType, 'GetCurrentPriceNumber', 65535,
            System.Type.DefaultBinder, {typeof('System.Int32')}, nil)
        drag = tolua.gettypemethod(itemType, 'Drag', 65535)
        -- Use the generated static wrapper with its exact three arguments;
        -- reflection must not insert a dummy receiver for a static method.
        sourceGood = WaterBell.ProjX.Data.Entity.ShopInfoHelper.GetShopGoodByID
        sourceNum = tolua.getproperty(sourceType, 'Num', 65535)
        if wallet == nil or drag == nil or sourceGood == nil or sourceNum == nil or
                fields.detail == nil or fields.bigSet == nil then
            error('Shop quantity reflection methods unavailable')
        end
        initialized = true
        UnityEngine.Debug.LogWarning('ONLINE_SHOP_BATCH_READY 77')
    end
    local function tick()
        setup()
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(panelType)
        if not alive(panel) or not panel.gameObject.activeInHierarchy then reset(); return end
        local detail = fields.detail:Get(panel)
        if not alive(detail) or not detail.gameObject.activeInHierarchy then reset(); return end
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.1
        local goodID, shopID, setID = fields.itemId:Get(detail), fields.shopId:Get(detail), fields.setId:Get(detail)
        if tostring(goodID) == '0' then return end
        phase = 'fetching original goods'
        local goods = ManagerCsv.GetInstance():GetGoods(goodID)
        local shop = ManagerCsv.GetInstance():GetShop(shopID)
        local source = sourceGood(setID, shopID, goodID)
        if goods == nil or shop == nil or source == nil then return end
        phase = 'reading goods fields'
        if fields.singleLimit == nil then
            local kind = goods:GetType()
            fields.singleLimit = tolua.getfield(kind, 'single_purchase_limit', 65535)
            fields.goodsPrice1 = tolua.getfield(kind, 'price1', 65535)
            fields.goodsPrice2 = tolua.getfield(kind, 'price2', 65535)
            if fields.singleLimit == nil or fields.goodsPrice1 == nil or fields.goodsPrice2 == nil then
                error('Original goods quantity fields unavailable')
            end
        end
        local stock = number(sourceNum:Get(source, nil))
        -- This client has a Goods CSV wrapper, but no TypeCsvShop wrapper.
        -- Read the preserved fields by reflection rather than Lua member lookup.
        if fields.currency == nil then
            phase = 'reading shop currency field'
            -- typeof(string) only resolves registered ToLua wrappers here;
            -- TypeCsvShop has none, so use the actual returned object's type.
            fields.currency = tolua.getfield(shop:GetType(), 'price_type', 65535)
            if fields.currency == nil then error('Original shop currency field unavailable') end
        end
        local currency = number(fields.currency:Get(shop))
        local maximum, balances = 1, ''
        local bigSet = tostring(fields.bigSet:Get(panel))
        local permitted = number(fields.singleLimit:Get(goods)) ~= 1 and currency ~= 99 and
                          bigSet ~= '47000008' and (stock < 0 or stock >= 2)
        if permitted then
            phase = 'calculating original wallet limit'
            local function affordable(currency, price)
                local balance = number(wallet:Call(detail, currency))
                balances = balances .. ':' .. tostring(currency) .. ':' .. tostring(balance) .. ':' .. tostring(price)
                if price <= 0 then return 1 end
                return math.max(0, math.floor(balance / price))
            end
            local amount
            if number(fields.goodsPrice1:Get(goods)) ~= 0 then
                amount = affordable(number(fields.price1:Get(detail)), number(fields.num1:Get(detail)))
                if number(fields.goodsPrice2:Get(goods)) ~= 0 then
                    amount = math.min(amount, affordable(number(fields.price2:Get(detail)), number(fields.num2:Get(detail))))
                end
            else
                amount = affordable(currency, number(fields.num1:Get(detail)))
            end
            maximum = math.max(1, math.min(stock < 0 and 20 or stock, amount))
        end
        local identity = tostring(detail:GetInstanceID()) .. ':' .. tostring(setID) .. ':' ..
                         tostring(shopID) .. ':' .. tostring(goodID)
        local signature = identity .. ':' .. tostring(stock) .. ':' .. tostring(maximum) .. balances
        local widget = fields.sliderWidget:Get(detail)
        local slider = fields.slider:Get(detail)
        local show = permitted and maximum >= 2
        local resetByNative = number(fields.maxNumber:Get(detail)) ~= maximum or widget.gameObject.activeSelf ~= show
        if identity ~= lastIdentity or signature ~= lastSignature or resetByNative then
            phase = 'updating native slider'
            local chosen = identity == lastIdentity and math.floor(1 + slider.value * (previousMax - 1)) or 1
            chosen = math.max(1, math.min(chosen, maximum))
            fields.maxNumber:Set(detail, maximum)
            widget.gameObject:SetActive(show)
            slider.value = maximum > 1 and (chosen - 1) / (maximum - 1) or 0
            drag:Call(detail)
            UnityEngine.Debug.Log('ONLINE_SHOP_BATCH item=' .. tostring(goodID) ..
                ' stock=' .. tostring(stock) .. ' max=' .. tostring(maximum) .. ' visible=' .. tostring(show))
            lastIdentity, lastSignature, previousMax = identity, signature, maximum
        end
    end
    UpdateBeat:Add(function()
        if UnityEngine.Time.realtimeSinceStartup < retryAt then return end
        local ok, err = pcall(tick)
        if not ok then
            local now = UnityEngine.Time.realtimeSinceStartup
            nextCheck = now + 5
            retryAt = nextCheck
            if now - lastErrorAt >= 5 then
                UnityEngine.Debug.LogError('ONLINE_SHOP_BATCH ' .. phase .. ': ' .. tostring(err))
                lastErrorAt = now
            end
        end
    end)
end
