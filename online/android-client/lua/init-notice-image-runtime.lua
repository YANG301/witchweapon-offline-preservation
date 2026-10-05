-- Reuse the original announcement image and scrolling content. Assets are read
-- only from the verified updater overlay, with the same asset inside full APKs.
do
    local KEY = '__WWRCommunityNoticeImageV1'
    if rawget(_G, KEY) == nil then
        local state = {nextTick = 0, nextFind = 0, errorAt = -100}
        rawset(_G, KEY, state)
        local fields, types, loaders
        local BUNDLE = 'assetbundle/config/community_notice_image.ab'
        local TEXTURE = 'assets/community/notice_thanks_avatars.png'
        local FOOTER = '用户阅读本协议后'
        local function alive(value) return value ~= nil and not value:Equals(nil) end
        local function shown(value) return alive(value) and value.gameObject.activeInHierarchy end
        local function setup()
            if fields ~= nil then return end
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            -- This client exposes AssetBundle from its original UnityEngine
            -- assembly. Newer Unity layouts split it into a module, which is
            -- optional here; the reflected type/methods validate real support.
            pcall(function() tolua.loadassembly('UnityEngine') end)
            pcall(function() tolua.loadassembly('UnityEngine.CoreModule') end)
            pcall(function() tolua.loadassembly('UnityEngine.AssetBundleModule') end)
            local foundTypes = {notice = typeof('UIAnnouncement'),
                texture = typeof('UnityEngine.Texture2D'), label = typeof('UILabel')}
            local foundFields = {
                image = tolua.getfield(foundTypes.notice, '_viewImage', 65535),
                body = tolua.getfield(foundTypes.notice, '_viewLabel', 65535),
                scroll = tolua.getfield(foundTypes.notice, '_viewScrollView', 65535),
            }
            for _, name in ipairs({'image', 'body', 'scroll'}) do
                if foundFields[name] == nil then error('Announcement member missing: ' .. name) end
            end
            local bundleType = typeof('UnityEngine.AssetBundle')
            local foundLoaders = {
                file = tolua.getmethod(bundleType, 'LoadFromFile', typeof('System.String')),
                asset = tolua.getmethod(bundleType, 'LoadAsset', typeof('System.String'), typeof('System.Type')),
                exists = tolua.getmethod(typeof('System.IO.File'), 'Exists', typeof('System.String')),
            }
            for _, name in ipairs({'file', 'asset', 'exists'}) do
                if foundLoaders[name] == nil then error('Announcement loader missing: ' .. name) end
            end
            types, fields, loaders = foundTypes, foundFields, foundLoaders
            UnityEngine.Debug.Log('WWR_NOTICE_IMAGE_READY 191')
        end
        local function loadTexture()
            if alive(state.texture) then return state.texture end
            if state.bundle == nil then
                local path = UnityEngine.Application.persistentDataPath .. '/' .. BUNDLE
                if loaders.exists:Call(path) then
                    state.bundle = loaders.file:Call(path)
                    state.source = 'signed-overlay'
                else
                    if state.apkRequest == nil then
                        local uri = UnityEngine.Application.streamingAssetsPath .. '/' .. BUNDLE
                        if string.find(uri, '://', 1, true) == nil then uri = 'file://' .. uri end
                        state.apkRequest = UnityEngine.WWW(uri)
                        state.source = 'bundled-apk'
                    end
                    if not state.apkRequest.isDone then return nil end
                    if state.apkRequest.error ~= nil and tostring(state.apkRequest.error) ~= '' then
                        local message = tostring(state.apkRequest.error)
                        state.apkRequest:Dispose()
                        state.apkRequest = nil
                        error('Announcement image read failed: ' .. message)
                    end
                    state.bundle = state.apkRequest.assetBundle
                end
                if not alive(state.bundle) then error('Announcement image bundle missing') end
            end
            state.texture = loaders.asset:Call(state.bundle, TEXTURE, types.texture)
            if not alive(state.texture) then error('Announcement texture missing') end
            if state.apkRequest ~= nil then
                state.apkRequest:Dispose()
                state.apkRequest = nil
            end
            UnityEngine.Debug.Log('WWR_NOTICE_IMAGE_LOADED ' .. tostring(state.source))
            return state.texture
        end
        local function splitFooter(text)
            local at = string.find(text, FOOTER, 1, true)
            if at == nil then return text, nil end
            -- The dedicated line is plain text. Never print a marker or resize
            -- the whole agreement merely to reduce the last sentence.
            local body = text:sub(1, at - 1):gsub('%s+$', '')
            local tail = text:sub(at):gsub('%s+$', '')
            return body, tail
        end
        local function notice(now)
            if not shown(state.panel) then
                if now < state.nextFind then return end
                state.nextFind = now + 1
                state.panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(types.notice)
                state.lastText, state.lastBody, state.basePosition = nil, nil, nil
                state.body, state.image, state.footer = nil, nil, nil
                if not shown(state.panel) then return end
            end
            local panel = state.panel
            if not alive(state.body) or not alive(state.image) then
                state.body = fields.body:Get(panel)
                state.image = fields.image:Get(panel)
                local node = panel.transform:Find('Center/scrollView/UserAgreementFinePrint')
                state.footer = alive(node) and node:GetComponent(types.label) or nil
            end
            local body, image, footer = state.body, state.image, state.footer
            if not alive(body) or not alive(image) then return end
            local raw = body.text or ''
            if state.basePosition == nil then
                local p = body.transform.localPosition
                state.basePosition = UnityEngine.Vector3(p.x, p.y, p.z)
            end
            if raw == state.lastBody then raw = state.lastText end
            if raw == nil then return end
            if raw == state.lastText and not state.imagePending then return end
            -- Update notes may mention the thanks list, but only that notice's
            -- exact first-line title should activate its image.
            local firstLine = (raw:match('^[^\r\n]*') or ''):gsub('^%s+', ''):gsub('%s+$', '')
            local thankYou = firstLine == '感谢名单'
            local content, finePrint = splitFooter(raw)
            if thankYou then
                -- Keep the notice title for selection, but do not repeat it
                -- between the avatar image and its short acknowledgement.
                content = (content:match('^[^\r\n]*[\r\n]+(.*)$') or ''):gsub('^%s+', '')
            end
            if state.lastText ~= raw or state.lastThankYou ~= thankYou then
                state.lastText, state.lastBody, state.lastThankYou = raw, content, thankYou
                body.text = content
                if alive(footer) then
                    footer.text = finePrint or ''
                    footer.gameObject:SetActive(finePrint ~= nil)
                end
                image.gameObject:SetActive(false)
                state.imagePending = thankYou
                body.transform.localPosition = state.basePosition
                local scroll = fields.scroll:Get(panel)
                if alive(scroll) then scroll:ResetPosition() end
            end
            if thankYou then
                local texture = loadTexture()
                if alive(texture) then
                    local width = 911
                    local height = math.max(1, math.floor(width * texture.height / texture.width + 0.5))
                    -- The original UITexture wrapper accepts a Texture2D as a
                    -- Texture. LuaProperty.Set instead calls ChangeType and
                    -- rejects that inheritance conversion on this client.
                    image.mainTexture = texture
                    image.width, image.height = width, height
                    local p = image.transform.localPosition
                    image.transform.localPosition = UnityEngine.Vector3(state.basePosition.x, 275, p.z)
                    image.gameObject:SetActive(true)
                    local b = state.basePosition
                    body.transform.localPosition = UnityEngine.Vector3(b.x, 275 - height, b.z)
                    state.imagePending = false
                end
            elseif image.gameObject.activeSelf then image.gameObject:SetActive(false) end
        end
        LateUpdateBeat:Add(function()
            local now = UnityEngine.Time.realtimeSinceStartup
            if not shown(state.panel) and now < state.nextTick then return end
            if not shown(state.panel) then state.nextTick = now + 1 end
            local ok, err = pcall(function() setup(); notice(now) end)
            if not ok and now - state.errorAt > 30 then
                state.errorAt = now
                UnityEngine.Debug.LogWarning('WWR_NOTICE_IMAGE_ERROR ' .. tostring(err))
            end
        end)
    end
end
