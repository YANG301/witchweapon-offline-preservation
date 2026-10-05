-- Cache scene lookups used by our UI repairs, without replacing Unity's API.
-- Keep inspecting a cached component each frame so a reused panel opens at once.
-- A missing/inactive component is searched again within 0.1 seconds; destruction
-- invalidates it immediately. Do not cache hierarchies or reward/model contents.
do
    local cache, searches, hits, skipped = {}, 0, 0, 0
    local now = function() return UnityEngine.Time.realtimeSinceStartup end
    local nativeFind = UnityEngine.Object.FindObjectOfType
    local function alive(value) return value ~= nil and not value:Equals(nil) end
    local probe = {}
    local sceneIDs = {
        ['WaterBell.ProjX.View.Panel.TaskPanelController'] = 18,
        ['WaterBell.ProjX.View.Panel.MapPanelControl'] = 2,
        ['WaterBell.ProjX.View.Panel.SelectLevelDetail'] = 3,
        ['WaterBell.ProjX.View.Panel.ClimbTowerLevelDetail'] = 30,
        ['DailyPanelControl'] = 15,
        ['TrialSelectLevel'] = 15,
        ['NewShopPanelControl'] = 19,
        ['WaterBell.ProjX.View.Panel.MailPanelController'] = 7,
        ['WaterBell.ProjX.View.Panel.GuildStateControl'] = 23,
        ['WaterBell.ProjX.View.Panel.GuildMercenaryControl'] = 23,
        ['WaterBell.ProjX.View.Panel.UserSettingControl'] = 25,
        ['WaterBell.ProjX.View.Panel.MainScenePanel'] = 11,
        ['VipPanel'] = 33,
    }
    local scenes = {}
    function probe.SceneShown(id)
        local time = now()
        local entry = scenes[id]
        if entry ~= nil and entry.time == time then return entry.shown end
        local frame = WaterBell and WaterBell.ProjX and WaterBell.ProjX.View and WaterBell.ProjX.View.UIFrame
        local manager = frame and frame.UISceneManager and frame.UISceneManager.getInstance()
        -- Some UI types are deliberately absent before the login assemblies
        -- load. Preserve normal behavior until the original manager is ready.
        local ok, shown = pcall(function() return manager == nil or manager:CheckSceneIsShow(id) end)
        if not ok then shown = true end
        if entry == nil then entry = {}; scenes[id] = entry end
        entry.time, entry.shown = time, shown
        return shown
    end
    function probe.Find(kind)
        local entry = cache[kind]
        local time = now()
        if entry == nil then
            entry = {nextSearch = 0, scene = sceneIDs[tostring(kind)]}
            cache[kind] = entry
        end
        if entry.scene ~= nil and not probe.SceneShown(entry.scene) then
            entry.nextSearch = 0
            skipped = skipped + 1
            return nil
        end
        if entry.object ~= nil then
            if alive(entry.object) then
                if entry.object.gameObject.activeInHierarchy then
                    hits = hits + 1
                    return entry.object
                end
            else
                entry.object, entry.nextSearch = nil, 0
            end
        end
        if time < entry.nextSearch then hits = hits + 1; return nil end
        entry.nextSearch = time + 0.1
        searches = searches + 1
        entry.object = nativeFind(kind)
        return entry.object
    end
    -- These two startup samples diagnose lookup rates and listener growth.
    -- There is no per-frame output, network request, GC or frame-rate override.
    local start, sample = nil, 1
    local checkpoints = {30, 120}
    local function measure()
        if start == nil then start = now(); return end
        local elapsed = now() - start
        if elapsed < checkpoints[sample] then return end
        local kinds = 0
        for _ in pairs(cache) do kinds = kinds + 1 end
        UnityEngine.Debug.LogWarning('WWR_RUNTIME_UI_SAMPLE seconds=' .. math.floor(elapsed) ..
            ' searches=' .. searches .. ' hits=' .. hits .. ' skipped=' .. skipped .. ' kinds=' .. kinds ..
            ' updateListeners=' .. UpdateBeat:Count() .. ' lateListeners=' .. LateUpdateBeat:Count())
        sample = sample + 1
        if sample > #checkpoints then UpdateBeat:Remove(measure) end
    end
    probe.FindObjectOfType = probe.Find
    WWRRuntimeUI = probe
    UpdateBeat:Add(measure)
    UnityEngine.Debug.LogWarning('WWR_RUNTIME_UI_READY 151')
end
