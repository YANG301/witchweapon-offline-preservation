-- WWR optional entry visibility v1. Hide only the redundant guide-task button.
-- New-witch badges, first-login lessons and the task system remain independent.
do
    local function install()
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        local guideType = typeof('ButtonTaskGuide')
        local mainType = typeof('WaterBell.ProjX.View.Panel.MainScenePanel')
        local vipType = typeof('VipPanel')
        local guideButton = tolua.getfield(guideType, 'button', 65535)
        local mainButton = tolua.getfield(mainType, 'GuideTaskBtn', 65535)
        local vipButton = tolua.getfield(vipType, 'goShopBtn', 65535)
        local vipCaption = tolua.getfield(vipType, 'closeShopTitle', 65535)
        assert(guideType and guideButton and mainButton and vipButton and vipCaption,
            'Optional entry targets missing')
        local reported = false
        local hidden = {}
        local nextGuideSearch, scanUntil, lastScene = 0, 0, nil
        local managedHash, hashContains, hashItem
        local managedLookup = pcall(function()
            local managerType = tolua.findtype('ButtonManager')
            managedHash = tolua.getfield(managerType, '_hash', 65535)
            assert(managedHash)
        end)
        local spriteType, colliderType = typeof('UISprite'), typeof('UnityEngine.Collider')
        local function alive(value) return value ~= nil and not value:Equals(nil) end
        local function hide(button)
            if not alive(button) then return end
            local go = button.gameObject
            local id = button:GetInstanceID()
            local entry = hidden[id]
            if entry == nil or not alive(entry.button) then
                entry = {button = button,
                    sprites = go:GetComponentsInChildren(spriteType, true),
                    colliders = go:GetComponentsInChildren(colliderType, true)}
                hidden[id] = entry
            end
            -- Persistent renderer/collider suppression prevents the native
            -- ButtonManager's reparent/SetActive calls from flashing a frame.
            for i = 0, entry.sprites.Length - 1 do
                local sprite = entry.sprites[i]
                if alive(sprite) and sprite.enabled then sprite.enabled = false end
            end
            for i = 0, entry.colliders.Length - 1 do
                local collider = entry.colliders[i]
                if alive(collider) and collider.enabled then collider.enabled = false end
            end
            if button.isEnabled then button.isEnabled = false end
            if go.activeSelf then go:SetActive(false) end
        end
        local function guides(objects)
            for i = 0, objects.Length - 1 do hide(guideButton:Get(objects[i])) end
        end
        local function tick()
            for id, entry in pairs(hidden) do
                if not alive(entry.button) then hidden[id] = nil else hide(entry.button) end
            end
            local now = UnityEngine.Time.realtimeSinceStartup
            -- ButtonManager reparents one cached Transform; read that cache
            -- without GetButton, which would instantiate a button itself.
            -- A new cached button is suppressed in the same LateUpdate frame.
            if managedLookup then
                local ok, failure = pcall(function()
                    local hash = managedHash:Get(nil)
                    if hash ~= nil and hashContains == nil then
                        -- ToLua requires a userdata for System.Object arguments.
                        -- The actual Dictionary<string,Transform> overloads
                        -- accept native Lua strings without boxing allocations.
                        local dictionaryType = hash:GetType()
                        hashContains = tolua.getmethod(dictionaryType, 'ContainsKey', typeof('System.String'))
                        hashItem = tolua.getmethod(dictionaryType, 'get_Item', typeof('System.String'))
                        assert(hashContains and hashItem)
                    end
                    if hash ~= nil and hashContains:Call(hash, 'ButtonTaskGuide') then
                        local target = hashItem:Call(hash, 'ButtonTaskGuide')
                        if alive(target) then
                            local controller = target:GetComponent('ButtonTaskGuide')
                            if alive(controller) then hide(guideButton:Get(controller)) end
                        end
                    end
                end)
                if not ok then
                    managedLookup = false
                    UnityEngine.Debug.LogWarning('WWR_OPTIONAL_CACHE_FALLBACK ' .. tostring(failure))
                end
            end
            local frame = WaterBell.ProjX.View.UIFrame
            local manager = frame and frame.UISceneManager.getInstance()
            if manager ~= nil then
                local state = manager:GetCurrentUISceneState()
                local scene = state ~= nil and state.SceneID or nil
                if scene ~= lastScene then
                    lastScene, scanUntil = scene, now + 0.5
                end
            end
            -- Retain a discovery fallback for independent clones. Scan each
            -- transition frame; steady pages need only two searches a second.
            -- Unsupported reflection keeps the previous full-frame protection.
            if not managedLookup or now <= scanUntil or now >= nextGuideSearch then
                guides(UnityEngine.Object.FindObjectsOfType(guideType))
                nextGuideSearch = now + 0.5
            end
            local main = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(mainType)
            if alive(main) then hide(mainButton:Get(main)) end
            local vip = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(vipType)
            if alive(vip) and vip.gameObject.activeInHierarchy then
                local button, caption = vipButton:Get(vip), vipCaption:Get(vip)
                if alive(button) then
                    -- Keep the original clickable shop entry. The native
                    -- activity-time check displays the closed-shop message.
                    if not button.gameObject.activeSelf then button.gameObject:SetActive(true) end
                    if not button.isEnabled then button.isEnabled = true end
                end
                if alive(caption) then
                    if caption.activeSelf then caption:SetActive(false) end
                end
            end
        end
        -- The shared prefab can be loaded outside the lobby and cloned by
        -- story/witch panels. Hide cached instances as well as active ones.
        guides(UnityEngine.Resources.FindObjectsOfTypeAll(guideType))
        LateUpdateBeat:Add(function()
            local ok, err = pcall(tick)
            if not ok and not reported then
                reported = true
                UnityEngine.Debug.LogError('WWR_OPTIONAL_ENTRIES ' .. tostring(err))
            end
        end)
        UnityEngine.Debug.LogWarning('WWR_OPTIONAL_ENTRIES_READY 147 cache=' .. tostring(managedLookup))
    end
    local ok, err = pcall(install)
    if not ok then UnityEngine.Debug.LogError('WWR_OPTIONAL_ENTRIES_INIT ' .. tostring(err)) end
end
