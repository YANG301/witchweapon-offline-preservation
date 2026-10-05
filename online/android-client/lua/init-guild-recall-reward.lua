-- Restore the original guild recall award panel after the authoritative wallet
-- has been refreshed. The old GuildInfo response does not update Player.
do
    local nextCheck, lastErrorAt = 0, -100
    local guildType, awardsType, controllerType, roleType
    local beforeGuild, beforeGold, recalledServant, awardItems
    local send, showReward, closeBlank
    local pending, dismissed

    local function setup()
        if guildType ~= nil then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        guildType = typeof('WaterBell.ProjX.View.Panel.GuildMercenaryControl')
        awardsType = typeof('WaterBell.ProjX.View.Panel.GetAwardsPanel')
        controllerType = typeof('GuildMercenaryManagerController')
        roleType = typeof('WaterBell.ProjX.Data.NetIO.RoleGetRoleInfoLogic')
        beforeGuild = tolua.getfield(controllerType, 'beforeGuildCurrency', 65535)
        beforeGold = tolua.getfield(controllerType, 'beforeGold', 65535)
        recalledServant = tolua.getfield(controllerType, 'removeSV', 65535)
        awardItems = tolua.getfield(awardsType, 'dataList', 65535)
        send = tolua.gettypemethod(
            typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        showReward = tolua.gettypemethod(awardsType, 'ShowGuildServantReward', 65535)
        closeBlank = tolua.gettypemethod(awardsType, 'DirectClosePanel', 65535)
        if guildType == nil or awardsType == nil or roleType == nil or
            beforeGuild == nil or beforeGold == nil or recalledServant == nil or
            awardItems == nil or send == nil or showReward == nil or
            closeBlank == nil then
            error('Guild recall reward reflection target is missing')
        end
    end

    local function visible(panel)
        return panel ~= nil and not panel:Equals(nil) and
            panel.gameObject.activeInHierarchy
    end

    local function wallet()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        local player = user ~= nil and user:GetPlayer() or nil
        if player == nil then return nil, nil end
        return tonumber(tostring(player.GuildCurrency)),
            tonumber(tostring(player.Gold))
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.2
        setup()

        local guildPanel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(guildType)
        if not visible(guildPanel) then
            pending, dismissed = nil, nil
            nextCheck = now + 0.6
            return
        end
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(awardsType)
        if not visible(panel) then
            pending, dismissed = nil, nil
            nextCheck = now + 0.6
            return
        end

        -- Other reward dialogs use the same original panel. Touch only the
        -- empty dialog created by GuildMercenaryControl.GetReward.
        local list = awardItems:Get(panel)
        local count = list ~= nil and tonumber(tostring(list.Count)) or nil
        if count ~= 0 then
            pending = nil
            return
        end
        local view = guildPanel.view
        local model = view ~= nil and view.GuildMercenaryManager or nil
        local controller = model ~= nil and model.Controller or nil
        if controller == nil then return end
        local servant = tonumber(tostring(recalledServant:Get(controller)))
        if servant == nil or servant <= 0 then return end
        if tonumber(tostring(model.RemoveMercenaryReward)) ~= 0 or
            tonumber(tostring(model.RemoveMecGoldReward)) ~= 0 then return end
        if dismissed == panel then return end

        if pending == nil or pending.panel ~= panel or pending.servant ~= servant then
            local guildBalance = tonumber(tostring(beforeGuild:Get(controller)))
            local goldBalance = tonumber(tostring(beforeGold:Get(controller)))
            if guildBalance == nil or goldBalance == nil then return end
            pending = { panel = panel, servant = servant, guild = guildBalance,
                gold = goldBalance, deadline = now + 12 }
            send:Call(tolua.createinstance(roleType))
            UnityEngine.Debug.Log('ONLINE_GUILD_RECALL_WALLET_REFRESH')
            return
        end

        local guildBalance, goldBalance = wallet()
        if guildBalance ~= nil and goldBalance ~= nil then
            local guildReward = guildBalance - pending.guild
            local goldReward = goldBalance - pending.gold
            if guildReward > 0 or goldReward > 0 then
                -- Only the server-owned balances determine the reward. Never
                -- change the wallet locally or display an invented amount.
                if guildReward < 0 then guildReward = 0 end
                if goldReward < 0 then goldReward = 0 end
                dismissed = panel
                pending = nil
                showReward:Call(panel, guildReward, goldReward)
                UnityEngine.Debug.Log('ONLINE_GUILD_RECALL_REWARD_SHOWN')
                return
            end
        end
        if now >= pending.deadline then
            -- An immediate recall may genuinely have no accrued income. Do
            -- not leave the player trapped in an empty award animation.
            dismissed = panel
            pending = nil
            closeBlank:Call(panel)
            local box = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(
                typeof('WaterBell.ProjX.View.Panel.NetworkWatingBoxBase'))
            if visible(box) then box:ShowTips('本次召回暂无可领取的支援收益') end
            UnityEngine.Debug.Log('ONLINE_GUILD_RECALL_NO_REWARD')
        end
    end

    UpdateBeat:Add(function()
        local ok, err = pcall(tick)
        if not ok then
            local now = UnityEngine.Time.realtimeSinceStartup
            nextCheck = now + 3
            if now - lastErrorAt >= 30 then
                lastErrorAt = now
                UnityEngine.Debug.LogError('ONLINE_GUILD_RECALL_REWARD ' .. tostring(err))
            end
        end
    end)
end
