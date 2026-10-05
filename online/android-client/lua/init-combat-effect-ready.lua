-- Observe initialization once and Sharp changes for the first ten seconds.
-- At most six Sharp records per hero. Diagnostics only.
-- No OnStart/OnInit/event replay/delegate mutation/weapon swap is performed.
do
    local key='__WWRCombatEffectReadyV1'
    if rawget(_G,key)==nil then
        local F=65535
        local owner,seenAt,firstWeapon,checked,nextCheck=nil,0,nil,false,0
        local sampleStart,sampleCount,lastSharpState=nil,0,nil
        local function log(text) UnityEngine.Debug.LogWarning('WWR_EFFECT_READY '..text) end
        local function alive(object)return object~=nil and not object:Equals(nil)end
        local function same(left,right)return System.Object.ReferenceEquals(left,right)end
        local function positive(value)return value~=nil and tonumber(tostring(value))>0 end
        local function setup()
            require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
            local heroType=typeof('HeroEntity')
            local entityType=typeof('Entity')
            local actorType=typeof('CharacterBase')
            local powerType=typeof('BuildPowerAndSharp')
            local managerType=typeof('TriggerManager')
            local triggerType=typeof('PassiveTrigger')
            local voType=typeof('TriggerVO')
            local stateType=typeof('WaterBell.ProjX.Battle.Unit.CharacterStateManager')
            local instance=tolua.getfield(heroType,'instance',F)
            local getPower=tolua.gettypemethod(heroType,'GetBuildPowerAndSharp',F)
            local getManager=tolua.gettypemethod(entityType,'GetTriggerManager',F)
            local getTriggers=tolua.gettypemethod(managerType,'GetTriggers',F)
            local powerHero=tolua.getfield(powerType,'hero',F)
            local registered=tolua.getfield(powerType,'isRegisted',F)
            local started=tolua.getfield(powerType,'isStarted',F)
            local currentWeapon=tolua.getfield(powerType,'currWeaponID',F)
            local sharpLocked=tolua.getfield(powerType,'isLockSharp',F)
            local sharp=tolua.gettypemethod(powerType,'GetCurrentWeaponSharp',F)
            local maximum=tolua.gettypemethod(powerType,'GetCurrentWeaponSharpMax',F)
            local managerUnit=tolua.getfield(managerType,'unit',F)
            local triggerEntity=tolua.getfield(triggerType,'entity',F)
            local triggerManager=tolua.getfield(triggerType,'manager',F)
            local voField=tolua.getfield(triggerType,'triggerVO',F)
            local activeField=tolua.getfield(triggerType,'isActive',F)
            local activeCondition=tolua.getfield(voType,'activeCondition',F)
            local activeArg1=tolua.getfield(voType,'activeConditionArg1',F)
            local activeArg2=tolua.getfield(voType,'activeConditionArg2',F)
            local activeCondition1=tolua.getfield(voType,'activeCondition1',F)
            local active1Arg1=tolua.getfield(voType,'activeCondition1Arg1',F)
            local active1Arg2=tolua.getfield(voType,'activeCondition1Arg2',F)
            local smField=tolua.getfield(actorType,'stateMngr',F)
            local spawned=tolua.gettypemethod(actorType,'get_isSpawnEnd',F)
            local dead=tolua.gettypemethod(actorType,'get_isDead',F)
            local paused=tolua.gettypemethod(stateType,'IsPaused',F)
            local skipped=tolua.gettypemethod(stateType,'get_isSkipped',F)
            local ooc=tolua.gettypemethod(stateType,'IsInOOC',F)
            local required={instance,getPower,getManager,getTriggers,powerHero,
                registered,started,currentWeapon,sharpLocked,sharp,maximum,managerUnit,
                triggerEntity,triggerManager,voField,activeField,smField,spawned,dead,
                paused,skipped,ooc,activeCondition,activeArg1,activeArg2,
                activeCondition1,active1Arg1,active1Arg2}
            for i=1,28 do if required[i]==nil then error('Missing ready reflection target '..i) end end
            local function tick()
                local now=UnityEngine.Time.realtimeSinceStartup
                if now<nextCheck then return end;nextCheck=now+0.1
                local hero=instance:Get(nil)
                if not alive(hero) then
                    owner=nil;checked=false;firstWeapon=nil
                    sampleStart,sampleCount,lastSharpState=nil,0,nil;return
                end
                if not same(hero,owner) then
                    owner,seenAt,firstWeapon,checked=hero,now,nil,false
                    sampleStart,sampleCount,lastSharpState=nil,0,nil
                end
                local power=getPower:Call(hero)
                if power~=nil and same(powerHero:Get(power),hero) then
                    local sampleWeapon=currentWeapon:Get(power)
                    if positive(sampleWeapon) then
                        local current,limit=tonumber(sharp:Call(power)),tonumber(maximum:Call(power))
                        if current~=nil and limit~=nil then
                            if sampleStart==nil then sampleStart=now end
                            local status='wid='..tostring(sampleWeapon)..' sharp='..current..'/'..limit..
                                ' registered='..tostring(registered:Get(power))..
                                ' started='..tostring(started:Get(power))..
                                ' sharpLocked='..tostring(sharpLocked:Get(power))
                            if now-sampleStart<=10 and sampleCount<6 and status~=lastSharpState then
                                sampleCount=sampleCount+1;lastSharpState=status
                                log('SHARP sample='..sampleCount..' t='..
                                    string.format('%.1f',now-sampleStart)..' '..status)
                            end
                        end
                    end
                end
                if checked or now-seenAt<2 then return end
                local sm=smField:Get(hero)
                if sm==nil or paused:Call(sm) or skipped:Call(sm) or ooc:Call(sm) or
                    dead:Call(hero) or not spawned:Call(hero) then return end
                local manager=getManager:Call(hero)
                if power==nil or manager==nil or not registered:Get(power) or
                    not same(powerHero:Get(power),hero) or not same(managerUnit:Get(manager),hero) then return end
                local wid=currentWeapon:Get(power)
                if not positive(wid) then return end
                if firstWeapon==nil then firstWeapon=wid;seenAt=now;return end
                if tostring(firstWeapon)~=tostring(wid) then
                    checked=true;log('SKIP_NATIVE_SWAP');return
                end
                local current,limit=tonumber(sharp:Call(power)),tonumber(maximum:Call(power))
                if limit==nil or current==nil then return end
                local list=getTriggers:Call(manager)
                if list==nil or list.Count==0 then
                    checked=true;log('CHECK wid='..tostring(wid)..' sharp='..current..'/'..limit..
                        ' registered='..tostring(registered:Get(power))..' started='..tostring(started:Get(power))..
                        ' sharpLocked='..tostring(sharpLocked:Get(power))..' triggers=0 initGates=0 active=0');return
                end
                local gates,active=0,0
                for i=0,list.Count-1 do
                    local trigger=list[i]
                    if trigger==nil or not same(triggerEntity:Get(trigger),hero) or
                        not same(triggerManager:Get(trigger),manager) then return end
                    local vo=voField:Get(trigger)
                    if vo==nil then return end
                    local gate=(activeCondition:Get(vo)==3 and tostring(activeArg1:Get(vo))==tostring(wid) and
                                activeArg2:Get(vo)==3) or
                               (activeCondition1:Get(vo)==3 and tostring(active1Arg1:Get(vo))==tostring(wid) and
                                active1Arg2:Get(vo)==3)
                    if gate then
                        gates=gates+1
                        if activeField:Get(trigger) then active=active+1 end
                    end
                end
                if now-seenAt<0.5 then return end
                checked=true
                log('CHECK wid='..tostring(wid)..' sharp='..current..'/'..limit..
                    ' registered='..tostring(registered:Get(power))..' started='..tostring(started:Get(power))..
                    ' sharpLocked='..tostring(sharpLocked:Get(power))..
                    ' triggers='..list.Count..' initGates='..gates..' active='..active)
            end
            LateUpdateBeat:Add(function()
                local ok,err=pcall(tick)
                if not ok then
                    nextCheck=UnityEngine.Time.realtimeSinceStartup+10
                    log('ERROR '..tostring(err))
                end
            end)
        end
        local ok,err=pcall(setup)
        if ok then rawset(_G,key,true);log('INSTALLED')
        else log('SETUP_FAILED '..tostring(err)) end
    end
end
