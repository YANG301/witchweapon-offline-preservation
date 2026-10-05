local this = {}

local UIFrame = WaterBell.ProjX.View.UIFrame
local hiddenScenes = { UIFrame.UISceneID.MAIN_SCENE_NEW:ToInt() }
local check, current

-- MainScenePanel stays loaded beneath the guild page. Observe only the guild
-- page's existing model; issue one native refresh after this player donates.
local guildPanelType, guildPanelField, redrawMethod, requestType, sendMethod
local watchedPanel, lastDonation, lastLogCount, lastLogID
local nextGuildCheck, redrawAt = 0, 0
local guildPatchErrorShown = false

local function initGuildReflection()
    if guildPanelField ~= nil then return end
    require 'tolua.reflection'
    tolua.loadassembly('Assembly-CSharp')
    guildPanelType = typeof('WaterBell.ProjX.View.Panel.GuildStateControl')
    guildPanelField = tolua.getfield(guildPanelType, 'current')
    redrawMethod = tolua.gettypemethod(guildPanelType, 'SetGuildLogUI', 65535)
    requestType = typeof('WaterBell.ProjX.Data.NetIO.GetUserGuildInfo')
    sendMethod = tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
end

local function guildTick()
    local now = UnityEngine.Time.realtimeSinceStartup
    if now < nextGuildCheck then return end
    nextGuildCheck = now + 0.25
    initGuildReflection()
    local panel = guildPanelField:Get(nil)
    -- The original client leaves the static `current` unset on some entry
    -- paths. The active Unity component is still present in the guild scene.
    if panel == nil or panel:Equals(nil) then
        panel = UnityEngine.Object.FindObjectOfType(guildPanelType)
    end
    if panel == nil or panel:Equals(nil) or not panel.gameObject.activeInHierarchy then
        watchedPanel, lastDonation, lastLogCount, lastLogID = nil, nil, nil, nil
        redrawAt = 0
        return
    end

    local guild = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance():GetGuild()
    if guild == nil or guild.GuildInfo == nil then return end
    local logs = guild.GuildInfo.GuildLogs
    local count = logs == nil and 0 or logs.Count
    local newest = 0
    if count > 0 then
        local readOK, id = pcall(function() return tonumber(tostring(logs[0].Id)) end)
        if readOK and id ~= nil then newest = id end
    end
    local donation = guild.DonateCount

    if watchedPanel ~= panel then
        watchedPanel, lastDonation, lastLogCount, lastLogID = panel, donation, count, newest
        UnityEngine.Debug.Log('ONLINE_GUILD_REFRESH_READY')
        return
    end
    local donationChanged = donation ~= lastDonation
    local logChanged = count ~= lastLogCount or newest ~= lastLogID
    lastDonation, lastLogCount, lastLogID = donation, count, newest
    if donationChanged then
        -- The mutation reply has completed. Fetch the authoritative guild once,
        -- then let the native parser update the model used by the original UI.
        local message = tolua.createinstance(requestType)
        sendMethod:Call(message)
        redrawAt = now + 0.4
    end
    if logChanged or (redrawAt ~= 0 and now >= redrawAt) then
        redrawMethod:Call(panel)
        redrawAt = 0
    end
end

function this:OnEnable(obj)
    check = true
end

function this:Start(obj)
    current = obj
    UpdateBeat:Add(this.UpdateBeat, this)
end

function this:OnDisable(obj)
    check = false
end

function this:OnDestroy()
    UpdateBeat:Remove(this.UpdateBeat, this)
    check, current, watchedPanel = nil, nil, nil
end

function this.UpdateBeat()
    local ok, err = pcall(guildTick)
    if not ok and not guildPatchErrorShown then
        guildPatchErrorShown = true
        UnityEngine.Debug.LogError('ONLINE_GUILD_REFRESH ' .. tostring(err))
    end
    if not ok then nextGuildCheck = UnityEngine.Time.realtimeSinceStartup + 5 end
    if not check then return end
    for _, scene in ipairs(hiddenScenes) do
        if UIFrame.UISceneManager.getInstance():CheckSceneIsShow(scene) then
            if current.activeSelf then current:SetActive(false) end
        end
    end
end

return this
