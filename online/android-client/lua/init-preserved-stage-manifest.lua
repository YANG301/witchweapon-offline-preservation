-- WWR preserved stage dependency manifest v1.
-- The signed updater accepts .ab files. Keep the original central bundle intact
-- and install a manifest whose only replaced entries are the five old maps.
do
    local key = '__WWRPreservedStageManifestV1'
    if rawget(_G, key) == nil then
        local state = { ready = false, nextAttempt = 0, errorReported = false }
        rawset(_G, key, state)
        local function install()
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            local bundleType = typeof('UnityEngine.AssetBundle')
            local manifestType = typeof('UnityEngine.AssetBundleManifest')
            local loaderType = typeof('GLoader')
            local field = tolua.getfield(loaderType, '_manifest', 65535)
            if field == nil then error('GLoader manifest field missing') end
            if state.manifest == nil then
                local loadFile = tolua.getmethod(bundleType, 'LoadFromFile', typeof('System.String'))
                local loadAsset = tolua.getmethod(bundleType, 'LoadAsset', typeof('System.String'), typeof('System.Type'))
                local exists = tolua.getmethod(typeof('System.IO.File'), 'Exists', typeof('System.String'))
                if loadFile == nil or loadAsset == nil or exists == nil then error('AssetBundle loading methods missing') end
                local path = UnityEngine.Application.persistentDataPath .. '/assetbundle/config/preserved_stage_manifest.ab'
                if exists:Call(path) then
                    state.bundle = loadFile:Call(path)
                    state.source = 'signed-overlay'
                else
                    -- A future full APK includes the same .ab under assets.
                    -- Android streamingAssetsPath is a jar URL; WWW supports
                    -- that URL without treating it as a filesystem pathname.
                    if state.apkRequest == nil then
                        local uri = UnityEngine.Application.streamingAssetsPath .. '/assetbundle/config/preserved_stage_manifest.ab'
                        if string.find(uri, '://', 1, true) == nil then uri = 'file://' .. uri end
                        state.apkRequest = UnityEngine.WWW(uri)
                        state.source = 'bundled-apk'
                    end
                    if not state.apkRequest.isDone then return end
                    if state.apkRequest.error ~= nil and tostring(state.apkRequest.error) ~= '' then
                        local message = tostring(state.apkRequest.error)
                        state.apkRequest:Dispose()
                        state.apkRequest = nil
                        error('Bundled preserved dependency read failed: ' .. message)
                    end
                    state.bundle = state.apkRequest.assetBundle
                end
                if state.bundle == nil or state.bundle:Equals(nil) then error('Preserved dependency bundle missing') end
                state.manifest = loadAsset:Call(state.bundle, 'AssetBundleManifest', manifestType)
                if state.manifest == nil or state.manifest:Equals(nil) then error('Preserved dependency manifest missing') end
                if state.apkRequest ~= nil then
                    state.apkRequest:Dispose()
                    state.apkRequest = nil
                end
            end
            local current = field:Get(nil)
            if not System.Object.ReferenceEquals(current, state.manifest) then
                field:Set(nil, state.manifest)
            end
            if not state.ready then
                state.ready = true
                UnityEngine.Debug.Log('WWR_PRESERVED_STAGE_MANIFEST_READY 5 ' .. tostring(state.source))
            end
        end
        UpdateBeat:Add(function()
            local now = UnityEngine.Time.realtimeSinceStartup
            if now < state.nextAttempt then return end
            state.nextAttempt = now + (state.ready and 1 or 0.5)
            local ok, err = pcall(install)
            if not ok and not state.errorReported then
                state.errorReported = true
                UnityEngine.Debug.LogWarning('WWR_PRESERVED_STAGE_MANIFEST_ERROR ' .. tostring(err))
            end
        end)
    end
end
