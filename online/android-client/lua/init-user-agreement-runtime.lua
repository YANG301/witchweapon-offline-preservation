-- The signed updater intentionally excludes LoginMain, whose local/online
-- routing belongs to the installed APK. Apply only contract text and labels to
-- that preserved login UI, using its existing fields instead of scene scans.
do
    local KEY = '__WWRUserAgreementRuntimeV1'
    if rawget(_G, KEY) == nil then
        local state = {nextTick = 0, errorAt = -100, stage = 'startup'}
        rawset(_G, KEY, state)
        local BODY = @@AGREEMENT_BODY@@
        local FOOTER = @@AGREEMENT_FOOTER@@
        local SEGMENTS = {'noticeContent0', 'noticeContent123', 'noticeContent45',
            'noticeContent67', 'noticeContent8910', 'noticeContent11', 'noticeContent1213',
            'noticeContent1415', 'noticeContent16', 'noticeContent17', 'noticeContent181920',
            'noticeContent212223', 'noticeContent24252627', 'noticeContent2833', 'noticeContent34'}
        local r
        local function alive(value) return value ~= nil and not value:Equals(nil) end
        local function checkedType(name)
            state.stage = 'setup.type.' .. name
            local value = typeof(name)
            if value == nil then error('Agreement type missing: ' .. name) end
            return value
        end
        local function member(kind, owner, name)
            state.stage = 'setup.' .. kind .. '.' .. name
            local value
            if kind == 'field' then value = tolua.getfield(owner, name, 65535)
            elseif kind == 'property' then value = tolua.getproperty(owner, name, 65535)
            else value = tolua.gettypemethod(owner, name, 65535) end
            if value == nil then error('Agreement member missing: ' .. name) end
            return value
        end
        local function setup()
            if r ~= nil then return end
            state.stage = 'setup.assemblies'
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            pcall(function() tolua.loadassembly('UnityEngine') end)
            pcall(function() tolua.loadassembly('UnityEngine.CoreModule') end)
            local loginType = checkedType('WaterBell.ProjX.View.Panel.LoginFormal')
            local viewType, labelType = checkedType('GameClauseView'), checkedType('UILabel')
            local rectType, anchorType = checkedType('UIRect'), checkedType('UIRect+AnchorPoint')
            local widgetType = checkedType('UIWidget')
            local enumType, typeType, stringType = checkedType('System.Enum'),
                checkedType('System.Type'), checkedType('System.String')
            state.stage = 'setup.method.Enum.Parse'
            local parse = tolua.getmethod(enumType, 'Parse', typeType, stringType)
            if parse == nil then error('Agreement enum parser missing') end
            local found = {labelType = labelType,
                instance = member('method', loginType, 'GetInstance'),
                view = member('field', loginType, 'gameClauseView'),
                body = member('field', viewType, 'noticeContent'),
                title = member('field', viewType, 'noticeTitle'),
                overflow = member('property', labelType, 'overflowMethod'),
                pivot = member('property', widgetType, 'pivot'),
                update = member('field', rectType, 'updateAnchors'),
                left = member('field', rectType, 'leftAnchor'),
                right = member('field', rectType, 'rightAnchor'),
                top = member('field', rectType, 'topAnchor'),
                bottom = member('field', rectType, 'bottomAnchor'),
                target = member('field', anchorType, 'target'),
                relative = member('field', anchorType, 'relative'),
                absolute = member('field', anchorType, 'absolute'),
                reset = member('method', rectType, 'ResetAndUpdateAnchors')}
            local overflowType, pivotType, updateType = checkedType('UILabel+Overflow'),
                checkedType('UIWidget+Pivot'), checkedType('UIRect+AnchorUpdate')
            state.stage = 'setup.enum.ResizeHeight'
            found.resize = parse:Call(overflowType, 'ResizeHeight')
            state.stage = 'setup.enum.TopLeft'
            found.topLeft = parse:Call(pivotType, 'TopLeft')
            state.stage = 'setup.enum.OnUpdate'
            found.onUpdate = parse:Call(updateType, 'OnUpdate')
            r = found
        end
        local function anchor(name, field, footer, target, relative, absolute)
            state.stage = 'apply.anchor.' .. name .. '.get'
            local point = field:Get(footer)
            if point == nil then error('Agreement anchor instance missing: ' .. name) end
            state.stage = 'apply.anchor.' .. name .. '.target'
            if not alive(target) then error('Agreement anchor target missing: ' .. name) end
            r.target:Set(point, target)
            state.stage = 'apply.anchor.' .. name .. '.relative'
            r.relative:Set(point, relative)
            state.stage = 'apply.anchor.' .. name .. '.absolute'
            r.absolute:Set(point, absolute)
        end
        local function apply(login)
            state.stage = 'apply.view'
            local view = r.view:Get(login)
            if not alive(view) then return false end
            state.stage = 'apply.holder'
            local holder = view.transform:Find('Center/NoticeContainer/ContentArea/Panel/GameObject')
            if not alive(holder) then return false end
            local labels, nodes = {}, {}
            for _, name in ipairs(SEGMENTS) do
                state.stage = 'apply.label.' .. name
                local node = holder:Find(name)
                local label = alive(node) and node:GetComponent(r.labelType) or nil
                if not alive(label) then return false end
                nodes[name], labels[name] = node, label
            end
            local body, footer = labels.noticeContent0, labels.noticeContent123
            state.stage = 'apply.body.style'
            body.fontSize, body.width, body.supportEncoding = 22, 729, true
            state.stage = 'apply.body.overflow'
            r.overflow:Set(body, r.resize, nil)
            state.stage = 'apply.body.pivot'
            r.pivot:Set(body, r.topLeft, nil)
            state.stage = 'apply.body.text'
            body.text = BODY
            body.gameObject:SetActive(true)
            state.stage = 'apply.body.bind'
            r.body:Set(view, body)
            state.stage = 'apply.title'
            local title = r.title:Get(view)
            if alive(title) then title.text = '用户协议' end
            for _, name in ipairs(SEGMENTS) do
                if name ~= 'noticeContent0' and name ~= 'noticeContent123' then
                    state.stage = 'apply.hide.' .. name
                    labels[name].text = ''
                    nodes[name].gameObject:SetActive(false)
                end
            end
            state.stage = 'apply.footer.style'
            footer.fontSize, footer.width, footer.supportEncoding = 10, 729, true
            footer.spacingY = 2
            r.overflow:Set(footer, r.resize, nil)
            r.pivot:Set(footer, r.topLeft, nil)
            footer.color = UnityEngine.Color(0.74, 0.79, 0.83, 1)
            footer.text = FOOTER
            -- Both the original APK and our static override leave this anchor
            -- empty. LuaField.Set applies ChangeType to values, including nil;
            -- trying to clear an already-empty target would throw again.
            state.stage = 'apply.anchor.bottom.verify'
            local bottom = r.bottom:Get(footer)
            if bottom == nil then error('Agreement bottom anchor instance missing') end
            if alive(r.target:Get(bottom)) then error('Agreement footer has unexpected bottom anchor') end
            anchor('left', r.left, footer, body.transform, 0, 0)
            anchor('right', r.right, footer, body.transform, 1, 0)
            anchor('top', r.top, footer, body.transform, 0, -18)
            state.stage = 'apply.anchor.update'
            r.update:Set(footer, r.onUpdate)
            footer.gameObject:SetActive(true)
            state.stage = 'apply.anchor.reset'
            r.reset:Call(footer)
            state.stage = 'apply.registration.labels'
            -- LoginFormal's owner is a sibling controller in this prefab;
            -- the registration views share GameClauseView's LoginMain parent.
            local loginRoot = view.transform.parent
            if not alive(loginRoot) then return false end
            local all = loginRoot.gameObject:GetComponentsInChildren(r.labelType, true)
            state.entryLabels = {}
            local changed = 0
            for i = 0, all.Length - 1 do
                local label = all[i]
                if alive(label) and label ~= body and label ~= footer then
                    local text = label.text or ''
                    local updated = text:gsub('游戏使用条款', '用户协议')
                        :gsub('新丰洲君子约定', '用户协议'):gsub('君子约定', '用户协议')
                    if updated ~= text then label.text = updated; changed = changed + 1 end
                    if updated:find('用户协议', 1, true) ~= nil then
                        state.entryLabels[#state.entryLabels + 1] = label
                    end
                end
            end
            state.stage = 'applied'
            UnityEngine.Debug.LogWarning('WWR_USER_AGREEMENT_APPLIED labels=' .. changed ..
                ' cached=' .. #state.entryLabels .. ' footer=10')
            return true
        end
        UpdateBeat:Add(function()
            local now = UnityEngine.Time.realtimeSinceStartup
            if now < state.nextTick then return end
            state.nextTick = now + 1
            -- The original static LoginFormal getter owns the entire login
            -- prefab. Once configured, do no reflection or scene discovery until
            -- that exact prefab is destroyed and a new one is created.
            if alive(state.applied) then return end
            local ok, err = pcall(function()
                setup()
                state.stage = 'instance.GetInstance'
                local login = r.instance:Call()
                if not alive(login) or not login.gameObject.activeInHierarchy then return end
                if apply(login) then state.applied = login end
            end)
            if not ok and now - state.errorAt > 30 then
                state.errorAt = now
                UnityEngine.Debug.LogWarning('WWR_USER_AGREEMENT_ERROR stage=' ..
                    tostring(state.stage) .. ' ' .. tostring(err))
            end
        end)
        -- Registration subviews reset localized labels when opened. Keep only
        -- the few cached agreement labels consistent after that native update.
        -- No scene discovery or label enumeration occurs during normal play.
        LateUpdateBeat:Add(function()
            if not alive(state.applied) or not state.applied.gameObject.activeInHierarchy then return end
            for _, label in ipairs(state.entryLabels or {}) do
                if alive(label) and label.gameObject.activeInHierarchy then
                    local text = label.text or ''
                    local updated = text:gsub('游戏使用条款', '用户协议')
                        :gsub('新丰洲君子约定', '用户协议'):gsub('君子约定', '用户协议')
                    if updated ~= text then label.text = updated end
                end
            end
        end)
    end
end
