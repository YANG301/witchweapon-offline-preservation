-- Local test client only. This block is appended to the already-running
-- lua.ab/init.lua; the archived shop Patch scripts are not bound to this UI.
do
    local function install()
    require 'tolua.reflection'
    tolua.loadassembly('Assembly-CSharp')
    tolua.loadassembly('Assembly-CSharp-firstpass')
    UnityEngine.Debug.LogWarning('LOCAL_SHOP_PRESENTATION star_ready 99')
    local shopType = typeof('NewShopPanelControl')
    local itemType = typeof('ShopItemInfo')
    local flags = 65535
    local nextTick = 0
    local retryAt = 0
    local hiddenCounter = nil
    local reportedCounterMissing = false
    local shopFields = {}
    local itemFields = {}
    local cardDataField, cardSetField = nil, nil
    local starPage, starCount, starQueued, starRequest = nil, nil, false, nil
    local starDeadline, starRetryAt, starToken = 0, 0, 0
    local starCtor, starSync, starDraw, starModel, starController
    local starIds = {
        ['47000020'] = '44000047|44000048|44000049|44000050|44000051',
        ['47000019'] = '44000042|44000043|44000044|44000045|44000046|44000052|44000053|44000054',
    }
    local giftSets = { ['47000002'] = true, ['47000016'] = true }
    local yuanSets = {
        ['47000001'] = true, ['47000002'] = true, ['47000016'] = true,
    }
    local function field(type, name, object)
        local cache = type == shopType and shopFields or itemFields
        local handle = cache[name]
        if handle == nil then
            handle = tolua.getfield(type, name, flags)
            cache[name] = handle
        end
        return handle:Get(object)
    end

    local function setYuan(sprite, label)
        if sprite == nil or label == nil then return end
        -- The original NewResBar atlas contains this RMB icon; both card and
        -- detail sprites reference that atlas. Prices stay at server-side 0.
        if sprite.spriteName ~= 'Currency_Icon_RMB' then
            sprite.spriteName = 'Currency_Icon_RMB'
        end
        if label.text ~= '0' then label.text = '0' end
    end

    local function refreshCards(shop)
        local grid = field(shopType, 'currentGrid', shop)
        if grid == nil then return end
        local transform = grid.transform
        for index = 0, transform.childCount - 1 do
            local card = transform:GetChild(index)
            local icon = card:Find('Mid/p1Icon')
            local value = card:Find('Mid/p1Val')
            if icon ~= nil and value ~= nil then
                setYuan(icon:GetComponent('UISprite'),
                        value:GetComponent('UILabel'))
            end
        end
    end

    local function refreshDetail(shop, setID)
        local detail = field(shopType, 'ShopItemInfoView', shop)
        -- All published goods in the virtual RMB categories have a server
        -- price of zero. The price icon visible in the detail view belongs to
        -- goldIcon, while goldIcon1 is hidden in this layout.
        if detail == nil or not detail.gameObject.activeInHierarchy then return end
        if setID == '47000001' then
            -- The original resource detail keeps this populated label hidden.
            -- Show the six reviewed, per-product recharge descriptions.
            local description = field(itemType, 'resouceDesc', detail)
            if description ~= nil and description.text ~= '' and
                    not description.gameObject.activeSelf then
                description.gameObject:SetActive(true)
            end
        end
        setYuan(field(itemType, 'goldIcon1', detail),
                field(itemType, 'goldValue1', detail))
        local priceRoot = field(itemType, 'goldIcon', detail)
        setYuan(priceRoot:GetComponent('UISprite'),
                field(itemType, 'sellGold', detail))
    end

    local function refreshCounter(shop, setID)
        if giftSets[setID] then
            -- The live CN shop creates its extra resource summary under the
            -- otherwise empty Center/Table. The top global resource bar is
            -- outside this panel and remains visible.
            local counter = hiddenCounter
            if counter == nil or counter:Equals(nil) then
                counter = shop.transform:Find('Center/Table')
            end
            if counter == nil then
                if not reportedCounterMissing then
                    UnityEngine.Debug.Log('LOCAL_SHOP_PRESENTATION gift_counter_not_found')
                    reportedCounterMissing = true
                end
            else
                if reportedCounterMissing then
                    UnityEngine.Debug.Log('LOCAL_SHOP_PRESENTATION gift_counter_found')
                    reportedCounterMissing = false
                end
                if counter.gameObject.activeSelf then
                    counter.gameObject:SetActive(false)
                    hiddenCounter = counter
                end
            end
        else
            if setID == '47000020' or setID == '47000019' then
                -- Category changes can outlive the visibility-tracking table.
                -- Restore the original exchange wallet by its current owner.
                local counter = shop.transform:Find('Center/Table')
                if counter ~= nil and not counter.gameObject.activeSelf then
                    counter.gameObject:SetActive(true)
                end
            end
            if hiddenCounter ~= nil then
                if not hiddenCounter:Equals(nil) then
                    hiddenCounter.gameObject:SetActive(true)
                end
                hiddenCounter = nil
            end
            reportedCounterMissing = false
        end
    end

    local function refreshExchange(shop, setID)
        if setID == '47000020' then
            -- The original five-slot Star shelf has a 150-dust manual
            -- refresh, but this client hides FreshView after loading it.
            -- Its native button still opens the original confirmation flow.
            local fresh = field(shopType, 'FreshView', shop)
            if fresh ~= nil and not fresh.gameObject.activeSelf then
                fresh.gameObject:SetActive(true)
            end
        end
        -- GoodInfo.Num is a stock badge on the card. The wish shop has no
        -- stock concept; the purchase quantity controls are elsewhere.
        if setID == '47000008' then
            local grid = field(shopType, 'currentGrid', shop)
            if grid ~= nil then
                local transform = grid.transform
                for index = 0, transform.childCount - 1 do
                    local stock = transform:GetChild(index):Find('Mid/Num')
                    if stock ~= nil and stock.gameObject.activeSelf then
                        stock.gameObject:SetActive(false)
                    end
                end
            end
        end
    end

    -- Resource, sundry and recharge have no Gift subtabs. Native DrawButtonSub
    -- retains the previous Gift buttons for a frame when switching categories.
    -- Run this small visibility guard every frame, before the slower card pass.
    local hiddenSubTabs = {}
    local subTabPaths = {'btnList/BottomLeft', 'DefultShop/leftBottom'}
    local function refreshNavigation(shop, setID)
        local simple = setID == '47000001' or setID == '47000003' or
                       setID == '47000004'
        for _,path in ipairs(subTabPaths) do
            local node = shop.transform:Find(path)
            if node ~= nil then
                if simple then
                    if node.gameObject.activeSelf then
                        node.gameObject:SetActive(false)
                        hiddenSubTabs[path] = true
                    end
                elseif setID == '47000020' or setID == '47000019' or
                       hiddenSubTabs[path] then
                    node.gameObject:SetActive(true)
                    hiddenSubTabs[path] = nil
                end
            end
        end
        -- Refresh belongs to sundry (and the original star exchange). Do not
        -- let its prefab default or a previous page show it in other categories.
        if setID ~= '47000004' and setID ~= '47000020' then
            local fresh = field(shopType, 'FreshView', shop)
            if fresh ~= nil and fresh.gameObject.activeSelf then
                fresh.gameObject:SetActive(false)
            end
        end
        -- These shelves have no per-item limit. The protocol still carries a
        -- positive compatibility Number; never present it as actual stock.
        local innerSet = tostring(field(shopType, 'currentSetID', shop))
        local unlimited = setID == '47000003' or setID == '47000008' or
            (setID == '47000005' and innerSet == '44000002')
        if unlimited or setID == '47000019' then
            local grid = field(shopType, 'currentGrid', shop)
            if grid ~= nil then
                local transform = grid.transform
                for index = 0, transform.childCount - 1 do
                    local card = transform:GetChild(index)
                    local hide = unlimited
                    if setID == '47000019' then
                        local item = card:GetComponent('WaterBell.ProjX.View.Panel.UIShopItemSpriteEx')
                        if item ~= nil then
                            if cardDataField == nil then
                                cardDataField = tolua.getfield(item:GetType(), 'itemData', flags)
                            end
                            local data = cardDataField:Get(item)
                            if data ~= nil then
                                if cardSetField == nil then
                                    cardSetField = tolua.getfield(data:GetType(), 'shopSetID', flags)
                                end
                                local shelf = tonumber(tostring(cardSetField:Get(data)))
                                hide = shelf ~= nil and shelf >= 44000042 and shelf <= 44000046
                            end
                        end
                    end
                    local badge = card:Find('Mid/Num')
                    if hide and badge ~= nil and badge.gameObject.activeSelf then
                        badge.gameObject:SetActive(false)
                    elseif not hide and setID == '47000019' and badge ~= nil then
                        local label = badge:GetComponent('UILabel')
                        if label ~= nil and label.text ~= '' and not badge.gameObject.activeSelf then
                            badge.gameObject:SetActive(true)
                        end
                    end
                end
            end
        end
    end

    -- Native ManualFresh sends one SetInfo ID. After the server rotates the
    -- whole page, fetch the other slots through the original read-only message
    -- and rebuild the existing model; never send extra paid refresh requests.
    local function syncStarPage(shop, setID, now)
        local ids = starIds[setID]
        if ids == nil then starPage, starCount = nil, nil; return end
        local info = UserInfo.GetInstance():GetShopAllSets():GetShopSetByID(44000047)
        local count = info and tonumber(tostring(info.RefreshCount)) or nil
        if starPage ~= setID then
            starPage, starCount, starQueued = setID, count, true
        elseif setID == '47000020' and count ~= nil and starCount ~= nil and count > starCount then
            starCount, starQueued = count, true
        end
        if starRequest ~= nil then
            if now < starDeadline then return end
            starToken = starToken + 1
            starRequest, starQueued, starRetryAt = nil, true, now + 5
        end
        if not starQueued or now < starRetryAt then return end
        local manager = WaterBell.ProjX.Data.NetIO.ProtocolManager.GetInstance()
        if manager:CheckNormalMsg() then return end
        if starCtor == nil or starModel == nil or starController == nil or starSync == nil or starDraw == nil then
            starCtor = tolua.getconstructor(tolua.findtype('WaterBell.ProjX.Data.NetIO.GetSetData'), typeof('System.String'))
            starModel = tolua.getproperty(tolua.findtype('ShopSystemManagerViewBase'), 'ShopSystemManager', flags)
            starController = tolua.getproperty(tolua.findtype('ShopSystemManagerViewModel'), 'Controller', 20)
            starSync = tolua.gettypemethod(tolua.findtype('ShopSystemManagerController'), 'RefreshManagerShopSet', flags,
                System.Type.DefaultBinder, {tolua.findtype('ShopSystemManagerViewModel'), typeof('System.String')}, nil)
            local nativeIds = WaterBell.ProjX.Data.Entity.ShopInfoHelper.GetShopSetListInBigSet(tonumber(setID))
            if nativeIds == nil then error('Original star shop IDs unavailable') end
            starDraw = tolua.gettypemethod(shopType, 'GetShopState', flags,
                System.Type.DefaultBinder, {nativeIds:GetType()}, nil)
            if starCtor == nil or starSync == nil or starDraw == nil or starModel == nil or starController == nil then
                error('Original star shop synchronization methods unavailable')
            end
        end
        local request = starCtor:Call(ids)
        starToken = starToken + 1
        local token = starToken
        starRequest, starDeadline, starQueued = request, now + 15, false
        request.OnSuccessfulDelegate = function()
            if token ~= starToken then return end
            starRequest = nil
            local current = UserInfo.GetInstance():GetShopAllSets():GetShopSetByID(44000047)
            starCount = current and tonumber(tostring(current.RefreshCount)) or nil
            if shop == nil or shop:Equals(nil) or not shop.gameObject.activeInHierarchy or
                    tostring(field(shopType, 'currentBigSetID', shop)) ~= setID then return end
            local step = 'model'
            local ok, err = pcall(function()
                local view = field(shopType, 'view', shop)
                if view == nil or view:Equals(nil) then error('Shop view unavailable') end
                local model = starModel:Get(view, nil)
                if model == nil then error('Shop model unavailable') end
                local controller = starController:Get(model, nil)
                if controller == nil then error('Shop controller unavailable') end
                -- Update the model through its controller. The native command
                -- wrapper expects a pending UI-command list, which this
                -- read-only synchronization does not create.
                step = 'sync'
                starSync:Call(controller, model, ids)
                step = 'draw'
                local nativeIds = WaterBell.ProjX.Data.Entity.ShopInfoHelper.GetShopSetListInBigSet(tonumber(setID))
                if nativeIds == nil or field(shopType, 'currentGrid', shop) == nil then
                    error('Current star shop grid unavailable')
                end
                -- Redraw only the current shelf. Reopening the category also
                -- touches optional layouts absent from this CN shop prefab.
                starDraw:Call(shop, nativeIds)
            end)
            if not ok then
                starQueued, starRetryAt = true, UnityEngine.Time.realtimeSinceStartup + 5
                UnityEngine.Debug.LogError('ONLINE_STAR_SYNC ' .. step .. ' ' .. tostring(err))
            else UnityEngine.Debug.LogWarning('ONLINE_STAR_SYNC_OK ' .. setID .. ' refresh=' .. tostring(starCount)) end
        end
        request.OnFailedDelegate = function(text)
            if token ~= starToken then return end
            starRequest, starQueued, starRetryAt = nil, true, UnityEngine.Time.realtimeSinceStartup + 5
            UnityEngine.Debug.LogError('ONLINE_STAR_SYNC_FAILED ' .. tostring(text))
        end
        manager:SendNormalMassage(request)
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        local shop = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(shopType)
        if shop == nil or not shop.gameObject.activeInHierarchy then
            hiddenCounter = nil
            hiddenSubTabs = {}
            starPage, starCount = nil, nil
            return
        end
        local setID = tostring(field(shopType, 'currentBigSetID', shop))
        if setID == '0' then return end
        refreshNavigation(shop, setID)
        if now < nextTick then return end
        nextTick = now + 0.1
        syncStarPage(shop, setID, now)
        refreshCounter(shop, setID)
        refreshExchange(shop, setID)
        if yuanSets[setID] then
            refreshCards(shop)
            refreshDetail(shop, setID)
        end
    end

    UpdateBeat:Add(function()
        if UnityEngine.Time.realtimeSinceStartup < retryAt then return end
        local ok, err = pcall(tick)
        if not ok then
            UnityEngine.Debug.LogError('LOCAL_SHOP_PRESENTATION ' .. tostring(err))
            nextTick = UnityEngine.Time.realtimeSinceStartup + 5
            retryAt = nextTick
        end
    end)
    end
    local ok, err = pcall(install)
    if not ok then
        UnityEngine.Debug.LogError('LOCAL_SHOP_PRESENTATION init_error ' .. tostring(err))
    end
end
