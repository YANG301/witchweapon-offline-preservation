-- Public settings identity and original account-centre presentation.
-- Never overwrite the internal role ID or grant an unverified-email reward.
do
    local panelType, componentType, iconType, fields = nil, nil, nil, {}
    local nextTick, nextFetch, errorAt = 0, 0, -100
    local request, requestedRole, requestAt, cachedRole, cachedRid
    local buttons, ridLabels, lastPanel, lastUserVisible = {}, {}, nil, false
    local emailRole, emailPanel, emailComponent, emailState, emailRequest, emailRequestRole
    local emailRequestKind, emailRequestAt, emailRequestGeneration
    local emailGeneration, emailNextStatus, emailCooldownUntil = 0, 0, 0
    local emailVisible, emailOpen = false, false
    local postHeaders, mailType, mailSend
    local renderEmail, startEmailRequest
    local emailPath = 'Center/right/View/userView/CnTable/Table/email/'

    local function alive(value) return value ~= nil and not value:Equals(nil) end
    local function setup()
        if panelType ~= nil then return end
        require 'tolua.reflection'
        tolua.loadassembly('Assembly-CSharp')
        local target = typeof('WaterBell.ProjX.View.Panel.UserSettingControl')
        local found = {}
        for _, name in ipairs({'Id', 'GoWitchWeaponBtn', 'copyBtn', 'components',
                'EmailSendBtn', 'EmailBindBtn', 'EmailInputEm', 'EmailInputPw',
                'EmailInputCode', 'emailWaitTimer', 'serviceDeclare'}) do
            found[name] = tolua.getfield(target, name, 65535)
            if found[name] == nil then error('Settings field unavailable: ' .. name) end
        end
        componentType = typeof('UserSettingComponent')
        iconType = typeof('UserIconPrefab')
        found.iconRid = tolua.getfield(iconType, 'RidText', 65535)
        found.componentText = tolua.getfield(componentType, 'text', 65535)
        found.componentButton = tolua.getfield(componentType, 'btn', 65535)
        found.componentOpen = tolua.getfield(componentType, 'isOpen', 65535)
        found.emailForward = tolua.gettypemethod(componentType, 'AnimForward', 65535)
        found.emailReverse = tolua.gettypemethod(componentType, 'AnimReverse', 65535)
        if found.componentText == nil or found.componentButton == nil or
                found.componentOpen == nil or found.emailForward == nil or found.emailReverse == nil then
            error('Email component unavailable')
        end
        fields, panelType = found, target
        UnityEngine.Debug.LogWarning('ONLINE_SETTINGS_PROFILE_READY 119')
    end
    local function bind(button, callback)
        if not alive(button) then return end
        local id = button:GetInstanceID()
        local entry = buttons[id]
        if entry == nil then
            entry = {button = button, listener = UIEventListener.Get(button.gameObject), callback = callback}
            buttons[id] = entry
        end
        button.onClick = nil
        entry.listener.onClick = entry.callback
    end
    local function dispose()
        if request ~= nil then pcall(function() request:Dispose() end) end
        request, requestedRole = nil, nil
    end
    local function role()
        local user = WaterBell.ProjX.Data.Entity.UserInfo.GetInstance()
        local player = user ~= nil and user:GetPlayer() or nil
        return player ~= nil and tostring(player.RoleID) or nil
    end
    local function emailTip(message)
        NetworkAlertUI.TryShowWarningTipBox(message)
    end
    -- The shipped Lua bundle contains CJSON command-line helpers, but the
    -- native cjson module is not registered. Keep the flat status JSON
    -- decoder here, with no require or SDK wrapper dependency. Role IDs stay
    -- strings; UTF-8 text and JSON Unicode/surrogate escapes remain intact.
    local function decodeEmailJson(body)
        if type(body) ~= 'string' or #body > 65536 then error('Invalid email JSON body') end
        local position, length, slash = 1, #body, string.char(92)
        local function whitespace()
            while position <= length do
                local byte = body:byte(position)
                if byte ~= 32 and byte ~= 9 and byte ~= 10 and byte ~= 13 then break end
                position = position + 1
            end
        end
        local function utf8(code)
            if code < 128 then return string.char(code) end
            if code < 2048 then return string.char(192 + math.floor(code / 64), 128 + code % 64) end
            if code < 65536 then
                return string.char(224 + math.floor(code / 4096),
                    128 + math.floor(code / 64) % 64, 128 + code % 64)
            end
            return string.char(240 + math.floor(code / 262144),
                128 + math.floor(code / 4096) % 64, 128 + math.floor(code / 64) % 64, 128 + code % 64)
        end
        local function hex(at)
            local value = body:sub(at, at + 3)
            if #value ~= 4 or not value:match('^%x%x%x%x$') then error('Invalid JSON Unicode escape') end
            return tonumber(value, 16)
        end
        local escapes = {['"'] = '"', ['/'] = '/', b = string.char(8), f = string.char(12),
            n = string.char(10), r = string.char(13), t = string.char(9)}
        escapes[slash] = slash
        local function readString()
            if body:sub(position, position) ~= '"' then error('Expected JSON string') end
            position = position + 1
            local parts, start = {}, position
            while position <= length do
                local byte = body:byte(position)
                if byte == 34 then
                    parts[#parts + 1] = body:sub(start, position - 1)
                    position = position + 1
                    return table.concat(parts)
                elseif byte == 92 then
                    parts[#parts + 1] = body:sub(start, position - 1)
                    position = position + 1
                    local escape = body:sub(position, position)
                    if escape == 'u' then
                        local code = hex(position + 1)
                        position = position + 5
                        if code >= 55296 and code <= 56319 then
                            if body:sub(position, position + 1) ~= slash .. 'u' then error('Missing JSON low surrogate') end
                            local low = hex(position + 2)
                            if low < 56320 or low > 57343 then error('Invalid JSON low surrogate') end
                            code = 65536 + (code - 55296) * 1024 + low - 56320
                            position = position + 6
                        elseif code >= 56320 and code <= 57343 then error('Unexpected JSON low surrogate') end
                        parts[#parts + 1] = utf8(code)
                    else
                        if escapes[escape] == nil then error('Invalid JSON string escape') end
                        parts[#parts + 1] = escapes[escape]
                        position = position + 1
                    end
                    start = position
                elseif byte < 32 then error('Invalid JSON string control character')
                else position = position + 1 end
            end
            error('Unterminated JSON string')
        end
        local function digit()
            local byte = body:byte(position)
            return byte ~= nil and byte >= 48 and byte <= 57
        end
        local function readNumber()
            local start = position
            if body:sub(position, position) == '-' then position = position + 1 end
            if body:sub(position, position) == '0' then
                position = position + 1
                if digit() then error('Invalid JSON leading zero') end
            else
                if not digit() then error('Invalid JSON number') end
                repeat position = position + 1 until not digit()
            end
            if body:sub(position, position) == '.' then
                position = position + 1
                if not digit() then error('Invalid JSON number fraction') end
                repeat position = position + 1 until not digit()
            end
            local exponent = body:sub(position, position)
            if exponent == 'e' or exponent == 'E' then
                position = position + 1
                local sign = body:sub(position, position)
                if sign == '+' or sign == '-' then position = position + 1 end
                if not digit() then error('Invalid JSON number exponent') end
                repeat position = position + 1 until not digit()
            end
            local value = tonumber(body:sub(start, position - 1))
            if value == nil or value == math.huge or value == -math.huge then error('Invalid JSON number range') end
            return value
        end
        whitespace()
        if body:sub(position, position) ~= '{' then error('Expected email JSON object') end
        position = position + 1
        whitespace()
        local result, seen = {}, {}
        if body:sub(position, position) == '}' then position = position + 1
        else
            while true do
                local key = readString()
                if seen[key] then error('Duplicate email JSON key') end
                seen[key] = true
                whitespace()
                if body:sub(position, position) ~= ':' then error('Expected JSON colon') end
                position = position + 1
                whitespace()
                local value, first = nil, body:sub(position, position)
                if first == '"' then value = readString()
                elseif body:sub(position, position + 3) == 'true' then value = true; position = position + 4
                elseif body:sub(position, position + 4) == 'false' then value = false; position = position + 5
                elseif body:sub(position, position + 3) == 'null' then position = position + 4
                else value = readNumber() end
                result[key] = value
                whitespace()
                local separator = body:sub(position, position)
                position = position + 1
                if separator == '}' then break end
                if separator ~= ',' then error('Expected JSON object separator') end
                whitespace()
            end
        end
        whitespace()
        if position ~= length + 1 then error('Unexpected trailing JSON data') end
        return result
    end
    local function emailObject(path)
        if not alive(emailPanel) then return nil end
        local target = emailPanel.transform:Find(emailPath .. path)
        return alive(target) and target.gameObject or nil
    end
    local function emailLabel(path, text)
        local object = emailObject(path)
        if alive(object) then
            local label = object:GetComponent('UILabel')
            if alive(label) then label.text = text end
        end
    end
    local function emailActive(path, active)
        local object = emailObject(path)
        if alive(object) then object:SetActive(active) end
    end
    local function disposeEmailRequest()
        if emailRequest ~= nil then pcall(function() emailRequest:Dispose() end) end
        emailRequest, emailRequestRole, emailRequestKind, emailRequestGeneration = nil, nil, nil, nil
    end
    local function clearEmailSession()
        disposeEmailRequest()
        emailGeneration = emailGeneration + 1
        if alive(emailComponent) and emailOpen then
            pcall(function() fields.emailReverse:Call(emailComponent) end)
        end
        if alive(emailPanel) then
            local code = fields.EmailInputCode:Get(emailPanel)
            if alive(code) then code.value = '' end
            local input = fields.EmailInputEm:Get(emailPanel)
            if alive(input) then input.value, input.enabled = '', false end
        end
        emailRole, emailPanel, emailComponent, emailState = nil, nil, nil, nil
        emailVisible, emailOpen, emailCooldownUntil, emailNextStatus = false, false, 0, 0
    end
    local function currentEmailSession()
        if not emailVisible or not alive(emailPanel) or not alive(emailComponent) or
                not emailPanel.gameObject.activeInHierarchy or emailRole ~= role() then return false end
        local user = emailPanel.transform:Find('Center/right/View/userView')
        return alive(user) and user.gameObject.activeInHierarchy
    end
    local function preparePostHeaders()
        if postHeaders ~= nil then return postHeaders end
        tolua.loadassembly('UnityEngine')
        local formType = typeof('UnityEngine.WWWForm')
        local getter = tolua.gettypemethod(formType, 'get_headers', 65535)
        if getter == nil then error('WWW headers unavailable') end
        local headers = getter:Call(tolua.createinstance(formType))
        -- LuaMethod.Call accepts positional arguments using the Type[] supplied
        -- here. The flags-only overload leaves that list empty and rejects them.
        local setter = tolua.gettypemethod(headers:GetType(), 'set_Item',
            {typeof('System.String'), typeof('System.String')})
        if setter == nil then error('WWW header setter unavailable') end
        setter:Call(headers, 'Content-Type', 'application/json; charset=utf-8')
        postHeaders = headers
        return headers
    end
    local function syncRewardMail()
        if mailType == nil then
            mailType = typeof('WaterBell.ProjX.Data.NetIO.MailFatchAll')
            mailSend = tolua.gettypemethod(
                typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)
        end
        if mailType == nil or mailSend == nil then error('Email reward mail refresh unavailable') end
        -- Same native synchronization used by init-monthly-mail-refresh.lua.
        -- The reward stays in the game mailbox until the player claims it.
        mailSend:Call(tolua.createinstance(mailType))
    end
    local function maskedRegistrationEmail()
        local masked = emailState ~= nil and emailState.maskedEmail or nil
        if type(masked) ~= 'string' or masked == '' then return '注册邮箱读取中' end
        -- A malformed backend response must not accidentally expose the full address.
        if not masked:find('*', 1, true) then
            local first, domain = masked:match('^(.)[^@]*(@.+)$')
            return first ~= nil and (first .. '***' .. domain) or '注册邮箱已隐藏'
        end
        return masked
    end
    startEmailRequest = function(kind, code)
        if not currentEmailSession() or emailRequest ~= nil then return false end
        local now = UnityEngine.Time.realtimeSinceStartup
        local ok, result = pcall(function()
            if kind == 'status' then
                return UnityEngine.WWW('http://127.0.0.1:19878/role/email/status')
            end
            local bodyCode = code or ''
            if bodyCode ~= '' and (type(bodyCode) ~= 'string' or not bodyCode:match('^%d%d%d%d%d%d$')) then
                error('Invalid email verification code')
            end
            local body = kind == 'send' and '{}' or ('{"code":"' .. bodyCode .. '"}')
            local headers = preparePostHeaders()
            -- The original WWWWrap.CheckByteBuffer copies this Lua byte string
            -- into native byte[]. The non-empty JSON body always requests POST.
            return UnityEngine.WWW('http://127.0.0.1:19878/role/email/' .. kind, body, headers)
        end)
        emailNextStatus = now + 15
        if not ok then
            emailTip('邮箱请求组件暂不可用，请稍后重试')
            UnityEngine.Debug.LogError('ONLINE_SETTINGS_EMAIL_TRANSPORT ' .. tostring(result))
            return false
        end
        emailRequest, emailRequestKind, emailRequestRole = result, kind, emailRole
        emailRequestAt, emailRequestGeneration = now, emailGeneration
        return true
    end
    local function emailUnavailable()
        local message = emailState ~= nil and emailState.message or nil
        emailTip(type(message) == 'string' and message ~= '' and message or '邮箱验证服务暂不可用，请稍后重试')
    end
    local sendBlockMessages = {
        day_account = {'今日已发送', '今日已发送验证码，请明天再试'},
        day_ip = {'明天再试', '当前IP今日已发送验证码，请明天再试'},
        day_service = {'明天再试', '今日验证码邮件额度已用完，请明天再试'},
        month = {'下月再试', '本月验证码邮件额度已用完，请下月再试'},
        temporary = {'稍后再试', '验证码发送暂时受限，请稍后再试'},
        service = {'暂不可用', '邮箱验证服务暂不可用，请稍后再试'},
        verified = {'已验证', '注册邮箱已验证'},
    }
    local function sendBlockText(short)
        if emailState == nil then
            return short and '读取中' or '正在读取邮箱发送状态，请稍候'
        end
        local messages = sendBlockMessages[emailState.sendBlockedReason]
        if messages ~= nil then return messages[short and 1 or 2] end
        return short and '稍后再试' or '验证码暂不可发送，请稍后再试'
    end
    local function sendEmailCode()
        if not currentEmailSession() then return end
        if emailRequest ~= nil then emailTip('邮箱请求处理中，请稍候'); return end
        if emailState == nil then
            startEmailRequest('status')
            emailTip('正在读取注册邮箱，请稍后再发送验证码')
            return
        end
        if emailState.verified then emailTip('注册邮箱已验证'); return end
        if not emailState.serviceReady then emailUnavailable(); return end
        if not emailState.sendAllowed then emailTip(sendBlockText(false)); return end
        -- No automatic send/retry: only this user click can create a send request.
        startEmailRequest('send')
    end
    local function verifyEmailCode()
        if not currentEmailSession() then return end
        if emailRequest ~= nil then emailTip('邮箱请求处理中，请稍候'); return end
        if emailState == nil then startEmailRequest('status'); emailTip('邮箱验证状态正在读取'); return end
        if emailState.verified and emailState.rewardSent then
            emailTip('100张祈愿塔罗牌已发送至游戏邮件，请到邮件中领取')
            return
        end
        if emailState.verified then
            -- A verified account may retry the same persisted reward-mail operation.
            startEmailRequest('verify', '')
            return
        end
        if not emailState.serviceReady then emailUnavailable(); return end
        local input = fields.EmailInputCode:Get(emailPanel)
        local code = alive(input) and input.value or ''
        if type(code) ~= 'string' or not code:match('^%d%d%d%d%d%d$') then
            emailTip('请输入邮件中的6位验证码')
            return
        end
        startEmailRequest('verify', code)
    end
    local function toggleEmail()
        if not currentEmailSession() then return end
        emailOpen = not emailOpen
        if emailOpen then fields.emailForward:Call(emailComponent)
        else fields.emailReverse:Call(emailComponent) end
        renderEmail(UnityEngine.Time.realtimeSinceStartup)
        if emailOpen and emailRequest == nil and
                UnityEngine.Time.realtimeSinceStartup >= emailNextStatus then startEmailRequest('status') end
    end
    renderEmail = function(now)
        if not currentEmailSession() then return end
        local state, busy = emailState, emailRequest ~= nil
        local verified = state ~= nil and state.verified == true
        local rewarded = verified and state.rewardSent == true
        local sendAllowed = state ~= nil and state.serviceReady and state.sendAllowed and not verified
        -- Native binding status can be stale. Only these UI fields are corrected;
        -- Player.RoleID, loginEmail and the native account model are never changed.
        if fields.componentOpen:Get(emailComponent) ~= emailOpen then
            if emailOpen then fields.emailForward:Call(emailComponent)
            else fields.emailReverse:Call(emailComponent) end
        end
        emailActive('Container/InputPassward', false)
        emailActive('Container/InputEmail', true)
        emailActive('Container/InputCode', not verified)
        local codeInput = fields.EmailInputCode:Get(emailPanel)
        if alive(codeInput) then codeInput.enabled = not verified and not busy end
        local input = fields.EmailInputEm:Get(emailPanel)
        if alive(input) then
            input.enabled = false
            input.value = maskedRegistrationEmail()
            local collider = input.gameObject:GetComponent('BoxCollider')
            if alive(collider) then collider.enabled = false end
        end
        emailLabel('Container/InputEmail/Label', maskedRegistrationEmail())
        -- The original hidden phone reward label/sprite is reused in this header.
        -- Item 40350003 uses its existing Item40_200s currency icon.
        emailActive('EmailReward', true)
        emailLabel('EmailReward', '×100')
        local header = fields.componentText:Get(emailComponent)
        if alive(header) then
            if rewarded then header.text = '奖励已发'
            elseif verified then header.text = '已验证'
            elseif state == nil then header.text = '读取中'
            elseif not state.serviceReady then header.text = '暂不可用'
            else header.text = '验证奖励' end
        end
        local button = fields.componentButton:Get(emailComponent)
        if alive(button) then button.enabled, button.isEnabled = true, true; bind(button, toggleEmail) end
        local send = fields.EmailSendBtn:Get(emailPanel)
        if alive(send) then
            send.enabled, send.isEnabled = true, not busy and sendAllowed
            send.gameObject:SetActive(sendAllowed)
            bind(send, sendEmailCode)
        end
        emailActive('Container/waitTime', not verified and not sendAllowed)
        local timer = fields.emailWaitTimer:Get(emailPanel)
        if alive(timer) then timer.text = busy and '处理中' or sendBlockText(true) end
        emailLabel('Container/sendBtn/Sprite/Label', busy and '处理中' or '发送验证码')
        local verify = fields.EmailBindBtn:Get(emailPanel)
        if alive(verify) then
            verify.enabled, verify.isEnabled = true, not busy and not rewarded
            verify.gameObject:SetActive(true)
            bind(verify, verifyEmailCode)
        end
        emailLabel('Container/bindBtn/Sprite/Label',
            busy and '处理中' or (rewarded and '已完成' or (verified and '补发奖励' or '验证绑定')))
    end
    local function pollEmailRequest(now)
        if emailRequest == nil then return end
        if emailRequestRole ~= role() or emailRequestGeneration ~= emailGeneration or not currentEmailSession() then
            disposeEmailRequest()
            return
        end
        if not emailRequest.isDone then
            if now - emailRequestAt > 20 then
                disposeEmailRequest()
                emailState = nil
                emailNextStatus = now + 15
                emailTip('邮箱请求超时，请稍后重试')
            end
            return
        end
        local kind, issuedRole = emailRequestKind, emailRequestRole
        local transportOk = emailRequest.error == nil or emailRequest.error == ''
        local textOk, body = pcall(function() return emailRequest.text end)
        disposeEmailRequest()
        emailNextStatus = now + 10
        local decoded, data = pcall(decodeEmailJson, textOk and body or '')
        -- Input/configuration failures can precede the backend's role lookup.
        -- Show their message, but never cache an identity-less response as state.
        if decoded and type(data) == 'table' and data.roleId == '' and not transportOk then
            emailState = nil
            emailTip(type(data.message) == 'string' and data.message ~= '' and data.message or
                '邮箱请求未完成，请稍后重试')
            return
        end
        if not decoded or type(data) ~= 'table' or type(data.roleId) ~= 'string' or
                data.roleId ~= issuedRole or data.roleId ~= role() or
                type(data.verified) ~= 'boolean' or type(data.rewardSent) ~= 'boolean' or
                type(data.serviceReady) ~= 'boolean' or type(data.sendAllowed) ~= 'boolean' or
                type(data.sendBlockedReason) ~= 'string' then
            emailState = nil
            emailTip(transportOk and '邮箱返回状态无法确认，请重新打开个人中心' or '邮箱验证服务暂不可用，请稍后重试')
            return
        end
        emailState = data
        -- This may reach the next Beijing day or billing month. Keep the server
        -- deadline intact; it controls a status refresh, never an automatic send.
        local cooldown = math.max(0, tonumber(data.cooldownSeconds) or 0)
        emailCooldownUntil = not data.verified and not data.sendAllowed and cooldown > 0 and (now + cooldown) or 0
        if kind == 'verify' and data.verified and data.rewardSent then
            local code = fields.EmailInputCode:Get(emailPanel)
            if alive(code) then code.value = '' end
            local refreshed = pcall(syncRewardMail)
            emailTip('邮箱验证成功，100张祈愿塔罗牌已发送至游戏邮件，请到邮件中领取')
            if not refreshed then UnityEngine.Debug.LogWarning('ONLINE_SETTINGS_EMAIL_MAIL_REFRESH_RETRY_ON_OPEN') end
        elseif kind ~= 'status' then
            local message = type(data.message) == 'string' and data.message ~= '' and data.message or nil
            emailTip(message or (kind == 'send' and transportOk and '验证码已发送，请查收注册邮箱' or '邮箱请求未完成，请稍后重试'))
        end
    end
    local function updateEmail(panel, component, userVisible, now)
        local currentRole = role()
        if not userVisible or not alive(component) or currentRole == nil or currentRole == '0' then
            if emailVisible then clearEmailSession() end
            return
        end
        if not emailVisible or emailPanel ~= panel or emailRole ~= currentRole then
            clearEmailSession()
            emailPanel, emailComponent, emailRole = panel, component, currentRole
            emailVisible, emailOpen = true, false
            fields.emailReverse:Call(component)
            emailNextStatus = now
        end
        pollEmailRequest(now)
        renderEmail(now)
        if emailRequest == nil and now >= emailNextStatus then
            if emailState == nil then startEmailRequest('status')
            elseif emailCooldownUntil > 0 and now >= emailCooldownUntil then
                -- One read-only refresh at expiry, still using the existing
                -- 10/15-second request gate. Only a user click may call send.
                if startEmailRequest('status') then emailCooldownUntil = 0 end
            end
        end
    end
    local function updateRid(panel, now)
        local currentRole = role()
        if currentRole == nil or currentRole == '0' then return end
        if request ~= nil and requestedRole ~= currentRole then dispose() end
        if cachedRole ~= currentRole then
            cachedRid, cachedRole, ridLabels = nil, currentRole, {}
        end
        if request ~= nil then
            if request.isDone then
                local ok = request.error == nil or request.error == ''
                local body = ok and request.text or ''
                local rid = body:match('"rid"%s*:%s*(%d+)')
                local ridRole = body:match('"roleId"%s*:%s*"(%d+)"')
                if rid ~= nil and rid:match('^[1-9]%d%d%d%d%d$') and ridRole == currentRole then
                    cachedRid = rid
                    UnityEngine.Debug.LogWarning('ONLINE_SETTINGS_PUBLIC_RID ' .. rid)
                end
                dispose()
                nextFetch = now + 10
            elseif now - requestAt > 15 then
                dispose()
                nextFetch = now + 10
            end
        end
        local label = fields.Id:Get(panel)
        if alive(label) then label.text = cachedRid or '读取中' end
        -- The original collection and customer-service views have separate RID labels.
        -- Keep both public without mutating Player.RoleID or the native network model.
        local labels = panel.gameObject:GetComponentsInChildren(typeof('UILabel'), true)
        if labels ~= nil then
            for i = 0, labels.Length - 1 do
                local item = labels[i]
                local text = alive(item) and item.text or ''
                if alive(item) then
                    local id = item:GetInstanceID()
                    if text:find(currentRole, 1, true) then
                        ridLabels[id] = {label = item, format = text:gsub(currentRole, '{PUBLIC_RID}')}
                    end
                    local entry = ridLabels[id]
                    if entry ~= nil then
                        item.text = entry.format:gsub('{PUBLIC_RID}', cachedRid or '读取中')
                    end
                end
            end
        end
        -- The avatar card is instantiated by the original view manager, outside
        -- the controller's hierarchy. Only its own player's RID label is touched.
        local icons = UnityEngine.Object.FindObjectsOfType(iconType)
        if icons ~= nil and fields.iconRid ~= nil then
            for i = 0, icons.Length - 1 do
                local item = fields.iconRid:Get(icons[i])
                if alive(item) then
                    local id = item:GetInstanceID()
                    local text = item.text or ''
                    if text:find(currentRole, 1, true) then
                        ridLabels[id] = {label = item, format = text:gsub(currentRole, '{PUBLIC_RID}')}
                    end
                    local entry = ridLabels[id]
                    if entry ~= nil then item.text = entry.format:gsub('{PUBLIC_RID}', cachedRid or '读取中') end
                end
            end
        end
        bind(fields.copyBtn:Get(panel), function()
            if cachedRid ~= nil and cachedRole == role() then
                NGUITools.clipboard = cachedRid
                NetworkAlertUI.TryShowWarningTipBox('已复制 RID ' .. cachedRid)
            else NetworkAlertUI.TryShowWarningTipBox('RID 正在读取，请稍后重试') end
        end)
        if cachedRid == nil and request == nil and now >= nextFetch then
            request = UnityEngine.WWW('http://127.0.0.1:19878/role/publicRid')
            requestedRole, requestAt = currentRole, now
            nextFetch = now + 10
        end
    end
    local function tick()
        local now = UnityEngine.Time.realtimeSinceStartup
        if now < nextTick then return end
        nextTick = now + 0.2
        setup()
        local panel = (WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(panelType)
        if not alive(panel) or not panel.gameObject.activeInHierarchy then
            if emailVisible then clearEmailSession() end
            dispose()
            nextTick, lastUserVisible = now + 0.5, false
            for id, entry in pairs(buttons) do
                if not alive(entry.button) then buttons[id] = nil end
            end
            return
        end
        updateRid(panel, now)
        bind(fields.GoWitchWeaponBtn:Get(panel), function()
            UnityEngine.Application.OpenURL('https://www.witchweapon.wiki')
        end)
        local function setLabel(path, text)
            local target = panel.transform:Find(path)
            if alive(target) then
                local label = target.gameObject:GetComponent('UILabel')
                if alive(label) then label.text = text end
            end
        end
        setLabel('Center/right/View/serviceView/RemindText', '账号如遇到问题，请到测试群反馈。\n玩家QQ群：1078249413')
        setLabel('Center/right/View/serviceView/RemindText/Label (2)', '本游戏完全免费，没有任何付费内容')
        setLabel('Center/right/View/serviceView/GoWebBtn/Sprite/Label (1)', 'www.witchweapon.wiki')
        local components = fields.components:Get(panel)
        local componentOfEmail
        if components ~= nil then
            for i = 0, components.Length - 1 do
                local component = components[i]
                if alive(component) then
                    if component.gameObject.name == 'telephone' or component.gameObject.name == 'idCard' then
                        component.gameObject:SetActive(false)
                    elseif component.gameObject.name == 'email' then
                        component.gameObject:SetActive(true)
                        componentOfEmail = component
                    end
                end
            end
        end
        local user = panel.transform:Find('Center/right/View/userView')
        local userVisible = alive(user) and user.gameObject.activeInHierarchy
        updateEmail(panel, componentOfEmail, userVisible, now)
        if lastPanel ~= panel or (userVisible and not lastUserVisible) then
            local tableTransform = panel.transform:Find('Center/right/View/userView/CnTable/Table')
            if alive(tableTransform) then
                local table = tableTransform.gameObject:GetComponent('UITable')
                if alive(table) then table:Reposition() end
            end
        end
        lastPanel, lastUserVisible = panel, userVisible
    end
    UpdateBeat:Add(function()
        local ok, err = pcall(tick)
        local now = UnityEngine.Time.realtimeSinceStartup
        if not ok and now - errorAt > 30 then
            errorAt = now
            UnityEngine.Debug.LogError('ONLINE_SETTINGS_PROFILE ' .. tostring(err))
        end
    end)
end
