-- Append this block to lua.ab/init.lua. The original shop and mail UI remain in use.
-- Fetch once after a monthly-card buy and once when the original mail panel opens.
do
    local nextCheck = 0
    local armedUntil = 0
    local lastErrorAt = -100
    local lastRequestAt = -100
    local mailWasVisible = false
    local previous = {}
    local lastFetch = {}
    local shopType, bigSetField, mailPanelType, mailType, sendMethod
    local goods = {45820001, 45820006}

    local function initialize()
        if shopType ~= nil then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        local typeOfShop = typeof('NewShopPanelControl')
        local fieldOfBigSet = tolua.getfield(typeOfShop, 'currentBigSetID', 65535)
        local typeOfMailPanel = typeof('WaterBell.ProjX.View.Panel.MailPanelController')
        local typeOfMail = typeof('WaterBell.ProjX.Data.NetIO.MailFatchAll')
        local methodOfSend = tolua.gettypemethod(
            typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        if typeOfShop == nil or fieldOfBigSet == nil or
            typeOfMailPanel == nil or typeOfMail == nil or methodOfSend == nil then
            error('monthly mail reflection unavailable')
        end
        shopType, bigSetField, mailPanelType, mailType, sendMethod =
            typeOfShop, fieldOfBigSet, typeOfMailPanel, typeOfMail, methodOfSend
    end

    local function stockFor(shelf, goodID)
        local good = shelf:GetGoodByID(goodID)
        if good == nil then return nil end
        return tonumber(good.Num)
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25
        initialize()

        local mailPanel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(mailPanelType)
        local mailVisible = mailPanel ~= nil and not mailPanel:Equals(nil)
            and mailPanel.gameObject.activeInHierarchy
        local mailOpened = mailVisible and not mailWasVisible
        mailWasVisible = mailVisible

        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(shopType)
        local visible = panel ~= nil and not panel:Equals(nil)
            and panel.gameObject.activeInHierarchy
            and tostring(bigSetField:Get(panel)) == '47000016'
        if visible then armedUntil = now + 10 end
        local purchaseEdge = false
        if now > armedUntil then
            previous = {}
        else
            local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
            local sets = user ~= nil and user:GetShopAllSets() or nil
            local set = sets ~= nil and sets:GetShopSetByID(44000022) or nil
            local shelf = set ~= nil and set:GetShopByID(4502990008) or nil
            if shelf ~= nil then
                for _, goodID in ipairs(goods) do
                    local stock = stockFor(shelf, goodID)
                    if stock ~= nil then
                        local before = previous[goodID]
                        -- Only the confirmed native 1-to-0 stock edge counts.
                        if before ~= nil and before > 0 and stock == 0
                            and now - (lastFetch[goodID] or -100) >= 30 then
                            lastFetch[goodID] = now
                            purchaseEdge = true
                        end
                        previous[goodID] = stock
                    end
                end
            end
        end

        -- A purchase always needs a post-commit fetch. Opening the inbox soon
        -- after that fetch reuses its in-flight response; an earlier inbox
        -- fetch never suppresses a later purchase.
        if purchaseEdge or (mailOpened and now - lastRequestAt >= 2) then
            lastRequestAt = now
            local message = tolua.createinstance(mailType)
            sendMethod:Call(message)
            UnityEngine.Debug.Log('ONLINE_MONTH_CARD_MAIL_REFRESH')
        end
    end

    UpdateBeat:Add(function()
        local ok, err = pcall(tick)
        if not ok then
            local now = UnityEngine.Time.realtimeSinceStartup
            nextCheck = now + 5
            if now - lastErrorAt >= 30 then
                lastErrorAt = now
                UnityEngine.Debug.LogError('ONLINE_MONTH_CARD_MAIL_REFRESH ' .. tostring(err))
            end
        end
    end)
end
