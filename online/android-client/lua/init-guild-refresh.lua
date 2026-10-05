-- Guild UI is created after MainScenePanel is hidden. Register at Lua startup
-- so the listener survives scene changes and only works while guild UI is open.
do
    local panelType, redraw, requestType, send, donationProperty
    local activePanel, lastDonation
    local nextCheck, redrawAt, finalRedrawAt = 0, 0, 0
    local errorReported = false

    local function setup()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        panelType = typeof('WaterBell.ProjX.View.Panel.GuildStateControl')
        redraw = tolua.gettypemethod(panelType, 'SetGuildLogUI', 65535)
        requestType = typeof('WaterBell.ProjX.Data.NetIO.GetUserGuildInfo')
        send = tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        donationProperty = tolua.getproperty(
            typeof('WaterBell.ProjX.Data.Entity.ObservablePlayerGuild'),
            'DonateCount', 65535)
        if panelType == nil or redraw == nil or requestType == nil or
                send == nil or donationProperty == nil then
            error('Guild refresh reflection target is missing')
        end
    end

    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextCheck then return end
        nextCheck = now + 0.25

        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(panelType)
        if panel == nil or panel:Equals(nil) or not panel.gameObject.activeInHierarchy then
            activePanel, lastDonation = nil, nil
            redrawAt, finalRedrawAt = 0, 0
            nextCheck = now + 1
            return
        end

        local guild = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance():GetGuild()
        if guild == nil then return end
        local donation = donationProperty:Get(guild, nil)
        if activePanel ~= panel then
            activePanel = panel
            lastDonation = donation
            UnityEngine.Debug.Log('ONLINE_GUILD_REFRESH_READY')
            return
        end

        local donationChanged = donation ~= lastDonation
        lastDonation = donation
        if donationChanged then
            send:Call(tolua.createinstance(requestType))
            redrawAt = now + 0.4
            finalRedrawAt = now + 1.5
            UnityEngine.Debug.Log('ONLINE_GUILD_REFRESH_DONATED')
        end
        if (redrawAt ~= 0 and now >= redrawAt) or
                (finalRedrawAt ~= 0 and now >= finalRedrawAt) then
            redraw:Call(panel)
            if redrawAt ~= 0 and now >= redrawAt then redrawAt = 0 end
            if finalRedrawAt ~= 0 and now >= finalRedrawAt then finalRedrawAt = 0 end
            UnityEngine.Debug.Log('ONLINE_GUILD_REFRESH_REPAINTED')
        end
    end

    local ok, err = pcall(function()
        setup()
        UpdateBeat:Add(function()
            local success, tickError = pcall(tick)
            if not success then
                if not errorReported then
                    errorReported = true
                    UnityEngine.Debug.LogError('ONLINE_GUILD_REFRESH ' .. tostring(tickError))
                end
                nextCheck = UnityEngine.Time.realtimeSinceStartup + 5
            end
        end)
    end)
    if not ok then
        UnityEngine.Debug.LogError('ONLINE_GUILD_REFRESH_INIT ' .. tostring(err))
    end
end
