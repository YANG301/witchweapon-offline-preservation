-- Preserve the installed LoginMain and its local/online server selection.
do
    local KEY = '__WWRLoginEmailRecoveryV1'
    if rawget(_G, KEY) == nil then
        local state = {nextTick=0, errorAt=-100, clicks=0, buttons={}, cooldown=0}
        rawset(_G, KEY, state)
        local decode = @@EMAIL_JSON_DECODER@@
        local ORIGIN = 'https://212.192.15.11:18443/api/v1/auth/password/'
        local MESSAGES = {
            '你知道不勾选就没法注册吧︿(￣︶￣)︿',
            '喂，不许再点了，口牙！！！o(≧口≦)o',
            '......=￣ω￣=',
            '............(。_。)',
            '..................~~( ﹁ ﹁ ) ~~~',
            '你是不是有点太闲了？(ー`´ー)',
            '快点！香农！咬它！凸(艹皿艹 )',
            '汪汪汪！！！U•ェ•*U',
            '汪汪汪汪汪！！！U•ェ•*U',
            '香农！香农？你要跑那里去？Σ(っ °Д °;)っ',
            '都怪你，不理你了(╬◣д◢)',
            '还点！我咬死你w(ﾟДﾟ)w',
            '不理你了，点一百次也不理你，哼！（｀へ´）',
        }
        local FINAL = '啊啊啊啊！！！受不了你了，我要用jvav把你踢出去(///￣皿￣)○～'
        local r
        local function alive(v) return v ~= nil and not v:Equals(nil) end
        local function visible(v) return alive(v) and v.gameObject.activeInHierarchy end
        local function field(t, n)
            local f = tolua.getfield(t, n, 65535)
            if f == nil then error('Login field unavailable: '..n) end
            return f
        end
        local function setup()
            if r ~= nil then return end
            require 'tolua.reflection'
            tolua.loadassembly('Assembly-CSharp')
            pcall(function() tolua.loadassembly('UnityEngine') end)
            local login, pw, reg, reset = typeof('WaterBell.ProjX.View.Panel.LoginFormal'),
                typeof('AccLoginByPWView'), typeof('AccRegisterByEmailView'), typeof('ForgetCodeView')
            local custom = typeof('WaterBell.ProjX.View.Common.CustomInput')
            local found = {instance=tolua.gettypemethod(login,'GetInstance',65535),
                pw=field(login,'accLoginByPWView'), reg=field(login,'accRegisterByEmailView'),
                reset=field(login,'forgetCodeView'), clause=field(login,'gameClauseView'),
                input=field(custom,'Input'),
                label=field(custom,'Label'), placeholder=field(custom,'DefaultText'),
                pwPhone=field(pw,'switchSMSLoginBtn'), regPhone=field(reg,'switchPhoneRegBtn'),
                loginEmail=field(pw,'accNameInput'), loginPassword=field(pw,'accPWInput'),
                loginButton=field(pw,'loginBtn'), agree=field(reg,'agreeContractBtn'),
                agreed=field(reg,'IsAgreeContract'), regPassword=field(reg,'accPWInput'),
                regButton=field(reg,'regAndLoginBtn'), mailStep=field(reset,'secondeMailStep'),
                phoneStep=field(reset,'secondePhoneStep'), firstStep=field(reset,'firstStep'),
                toMail=tolua.gettypemethod(reset,'ToMailNextStep',65535)}
            for _, n in ipairs({'phoneAsAccNameInput','nextBtn','MailCodeInput','MailPWInput',
                'MailResetBtn','MailCodeRegainBtn','MailCodeRegainLabel','MailSMSLostBtn'}) do
                found[n]=field(reset,n)
            end
            if found.instance == nil or found.toMail == nil then error('Login method unavailable') end
            r=found
        end
        local function tip(text)
            -- The network warning toast belongs to the in-game UI and can be
            -- invisible on LoginMain. Reuse its working native alert instead.
            local alert=GUtilUISuper.show(typeof(UIAlert),'UIAlert',nil,true)
            alert:setButton(true,'确定',nil)
            alert:setData('提示',text)
            alert:setListener(function() end,nil)
        end
        local function bind(button, callback)
            if not alive(button) then return end
            local id=button:GetInstanceID()
            local entry=state.buttons[id]
            if entry == nil then
                entry={button=button,listener=UIEventListener.Get(button.gameObject),callback=callback}
                state.buttons[id]=entry
            end
            button.onClick=nil
            entry.listener.onClick=entry.callback
        end
        local function value(custom)
            return alive(custom) and r.input:Get(custom) or nil
        end
        local function contents(custom)
            local input=value(custom)
            return alive(input) and input.value or ''
        end
        local function style(custom, placeholder, limit)
            if not alive(custom) then return end
            local input=value(custom)
            if alive(input) then input.characterLimit=limit end
            r.placeholder:Set(custom,placeholder)
            local label=r.label:Get(custom)
            if alive(label) and (not alive(input) or input.value == '') then label.text=placeholder end
        end
        local function count(text)
            local _, n=text:gsub('[\128-\191]','')
            return #text-n
        end
        local function validPassword(text)
            local n=count(text)
            return n>=12 and n<=128 and not text:find('[%z\1-\31\127]')
                and text==text:gsub('^%s+',''):gsub('%s+$','')
        end
        local function validRegistrationPassword(text)
            return #text>=12 and #text<=20 and text:match('^[a-zA-Z0-9]+$')~=nil
                and text:match('[a-zA-Z]')~=nil and text:match('%d')~=nil
        end
        local function email(text)
            local trimmed=text:gsub('^%s+',''):gsub('%s+$',''):lower()
            if #trimmed>254 or not trimmed:match('^[^%s@]+@[^%s@]+%.[^%s@]+$') then return nil end
            return trimmed
        end
        local function quote(text)
            return '"'..text:gsub('[%z\1-\31\\"]',function(c)
                if c=='"' then return '\\"' end
                if c=='\\' then return '\\\\' end
                return string.format('\\u%04x',c:byte())
            end)..'"'
        end
        local function headers()
            if state.headers ~= nil then return state.headers end
            local ft=typeof('UnityEngine.WWWForm')
            local getter=tolua.gettypemethod(ft,'get_headers',65535)
            local h=getter:Call(tolua.createinstance(ft))
            local set=tolua.gettypemethod(h:GetType(),'set_Item',{typeof('System.String'),typeof('System.String')})
            set:Call(h,'Content-Type','application/json; charset=utf-8')
            state.headers=h
            return h
        end
        local function dispose()
            if state.request ~= nil then state.request:Dispose() end
            state.request,state.requestKind,state.requestView=nil,nil,nil
        end
        local function send(kind, view)
            if state.request ~= nil or not visible(view) then return end
            local address=email(contents(r.phoneAsAccNameInput:Get(view)))
            if address == nil then tip('请输入有效的注册邮箱'); return end
            if kind=='send' and UnityEngine.Time.realtimeSinceStartup<state.cooldown then
                r.toMail:Call(view)
                tip('今日已申请找回验证码，请检查邮箱；30分钟内有效，明天可再次发送')
                return
            end
            local body='{"email":'..quote(address)
            if kind=='reset' then
                local code=contents(r.MailCodeInput:Get(view))
                local password=contents(r.MailPWInput:Get(view))
                if not code:match('^%d%d%d%d%d%d$') then tip('请输入邮件中的6位验证码'); return end
                if not validPassword(password) then tip('新密码须为12–128个字符，首尾不能有空格，不能包含控制字符'); return end
                body=body..',"code":'..quote(code)..',"password":'..quote(password)
            end
            state.request=UnityEngine.WWW(ORIGIN..kind,body..'}',headers())
            state.requestKind,state.requestView,state.requestAt=kind,view,UnityEngine.Time.realtimeSinceStartup
        end
        local function checked(reg)
            r.agreed:Set(reg,true)
            local button=r.agree:Get(reg)
            if alive(button) then
                local active=button.transform:Find('active')
                local inactive=button.transform:Find('Disactive')
                if alive(active) then active.gameObject:SetActive(true) end
                if alive(inactive) then inactive.gameObject:SetActive(false) end
            end
        end
        local function agreementClick(reg)
            checked(reg)
            if state.alertOpen then return end
            state.clicks=state.clicks+1
            local message=MESSAGES[state.clicks]
            if state.clicks==114 then message=FINAL end
            if message == nil then return end
            local alert=GUtilUISuper.show(typeof(UIAlert),'UIAlert',nil,true)
            alert:setButton(true,state.clicks==114 and '退出游戏' or '确定',nil)
            alert:setData('不，你会同意的',message)
            state.alertOpen=true
            local quit=state.clicks==114
            alert:setListener(function()
                state.alertOpen=false
                if quit then UnityEngine.Application.Quit() end
            end,nil)
        end
        local function receive(now)
            if state.request == nil then return end
            if not visible(state.requestView) then dispose(); return end
            if not state.request.isDone then
                if now-state.requestAt>35 then dispose(); tip('请求超时，请稍后重试；请勿重复发送邮件') end
                return
            end
            local view,kind=state.requestView,state.requestKind
            local ok,response=pcall(function() return decode(state.request.text) end)
            local transport=state.request.error
            dispose()
            if not ok or type(response)~='table' then
                tip('邮箱找回服务暂不可用，请稍后重试')
                UnityEngine.Debug.LogWarning('WWR_PASSWORD_RECOVERY_TRANSPORT_FAILED')
                return
            end
            local fail=response.error
            if fail ~= nil or (transport ~= nil and transport ~= '') then
                tip(type(fail)=='table' and fail.message or response.message or '邮箱找回请求未完成，请稍后重试')
                UnityEngine.Debug.LogWarning('WWR_PASSWORD_RECOVERY_REJECTED')
                return
            end
            if kind=='send' then
                state.cooldown=now+math.max(1,math.min(86400,tonumber(response.cooldownSeconds) or 86400))
                r.toMail:Call(view)
                tip(response.message or '请检查注册邮箱，验证码30分钟内有效')
                UnityEngine.Debug.LogWarning('WWR_PASSWORD_RECOVERY_SEND_ACCEPTED')
            else
                local password=value(r.MailPWInput:Get(view))
                local code=value(r.MailCodeInput:Get(view))
                if alive(password) then password.value='' end
                if alive(code) then code.value='' end
                r.mailStep:Get(view):SetActive(false)
                r.phoneStep:Get(view):SetActive(false)
                r.firstStep:Get(view):SetActive(true)
                tip(response.message or '密码已重置，请返回登录并使用新密码')
                UnityEngine.Debug.LogWarning('WWR_PASSWORD_RECOVERY_RESET_SUCCEEDED')
            end
        end
        local function tick(now)
            setup()
            local login=r.instance:Call()
            if not visible(login) then dispose(); return end
            if not alive(state.login) or not state.login:Equals(login) then
                state.login=login
                state.buttons={}
                local clause=r.clause:Get(login)
                local root=alive(clause) and clause.transform.parent or nil
                state.wechat=alive(root) and root:Find('EntryOptionView/Center/Main/WechatContainner') or nil
                UnityEngine.Debug.LogWarning('WWR_LOGIN_EMAIL_RECOVERY_READY 189')
            end
            if alive(state.wechat) and state.wechat.gameObject.activeSelf then
                state.wechat.gameObject:SetActive(false)
            end
            local pw,reg,reset=r.pw:Get(login),r.reg:Get(login),r.reset:Get(login)
            if visible(pw) then
                r.pwPhone:Get(pw).gameObject:SetActive(false)
                style(r.loginEmail:Get(pw),'请输入注册邮箱',254)
                style(r.loginPassword:Get(pw),'密码（12–128位）',128)
                r.loginButton:Get(pw).isEnabled=email(contents(r.loginEmail:Get(pw)))~=nil
                    and validPassword(contents(r.loginPassword:Get(pw)))
            end
            if visible(reg) then
                r.regPhone:Get(reg).gameObject:SetActive(false)
                checked(reg)
                bind(r.agree:Get(reg),function() agreementClick(reg) end)
                style(r.regPassword:Get(reg),'12–20位字母+数字',20)
                r.regButton:Get(reg).isEnabled=validRegistrationPassword(contents(r.regPassword:Get(reg)))
            end
            if visible(reset) then
                style(r.phoneAsAccNameInput:Get(reset),'请输入注册邮箱',254)
                style(r.MailPWInput:Get(reset),'新密码（12–128位）',128)
                r.phoneStep:Get(reset):SetActive(false)
                bind(r.nextBtn:Get(reset),function() send('send',reset) end)
                bind(r.MailResetBtn:Get(reset),function() send('reset',reset) end)
                bind(r.MailCodeRegainBtn:Get(reset),function() send('send',reset) end)
                bind(r.MailSMSLostBtn:Get(reset),function()
                    tip('请检查垃圾邮件。每个账号和IP每天只能发送一次，验证码30分钟内有效。账号问题请到玩家QQ群1078249413反馈。')
                end)
                local sending=state.request~=nil
                r.nextBtn:Get(reset).isEnabled=not sending and email(contents(r.phoneAsAccNameInput:Get(reset)))~=nil
                r.MailResetBtn:Get(reset).isEnabled=not sending
                    and contents(r.MailCodeInput:Get(reset)):match('^%d%d%d%d%d%d$')~=nil
                    and validPassword(contents(r.MailPWInput:Get(reset)))
                r.MailCodeRegainBtn:Get(reset).isEnabled=not sending and now>=state.cooldown
                r.MailCodeRegainLabel:Get(reset).text=now<state.cooldown and '明天可再发送' or '重新发送'
            end
            receive(now)
        end
        LateUpdateBeat:Add(function()
            local now=UnityEngine.Time.realtimeSinceStartup
            if not visible(state.login) and now<state.nextTick then return end
            if not visible(state.login) then state.nextTick=now+0.5 end
            local ok,err=pcall(function() tick(now) end)
            if not ok and now-state.errorAt>30 then
                state.errorAt=now
                -- No email, password, verification code or response is logged.
                UnityEngine.Debug.LogWarning('WWR_LOGIN_EMAIL_RECOVERY_ERROR '..tostring(err))
            end
        end)
    end
end
