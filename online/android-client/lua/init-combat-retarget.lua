-- Finish a released manual move before its queued enemy selection is lost.
-- The native AdvExecFinishMove clears nextTarget in RunToDir_Hero (3103).
-- Use the native cached-command executor first; it owns targeting and attacks.
-- Run2Target also needs recovery when a death/selection leaves its lock behind.
do
    require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
    local F=65535
    local heroType=typeof('HeroEntity')
    local actorType=typeof('CharacterBase')
    local inputType=typeof('InputReciverMkII')
    local stateType=typeof('WaterBell.ProjX.Battle.Unit.CharacterStateManager')
    local heroInstance=tolua.getfield(heroType,'instance',F)
    local inputInstance=tolua.getfield(inputType,'instance',F)
    local stateField=tolua.getfield(actorType,'stateMngr',F)
    local nextTarget=tolua.getfield(heroType,'nextTarget',F)
    local currentTarget=tolua.getfield(actorType,'currentTarget',F)
    local slidingField=tolua.getfield(inputType,'isSliding',F)
    local state=tolua.gettypemethod(stateType,'GetCurrLogicState',F)
    local paused=tolua.gettypemethod(stateType,'IsPaused',F)
    local skipped=tolua.gettypemethod(stateType,'get_isSkipped',F)
    local ooc=tolua.gettypemethod(stateType,'IsInOOC',F)
    local dead=tolua.gettypemethod(actorType,'get_isDead',F)
    local unselectable=tolua.gettypemethod(actorType,'get_cannotChoose',F)
    local finish=tolua.gettypemethod(heroType,'AdvExecFinishMove',F)
    local cached=tolua.gettypemethod(heroType,'AdvExecTryCachedPreCMD',F)
    local release=tolua.gettypemethod(inputType,'ReleaseMouse',F)
    local locked=tolua.gettypemethod(heroType,'get_isTargetLocked',F)
    local clear=tolua.gettypemethod(heroType,'ClearTarget',F)
    local search=tolua.gettypemethod(heroType,'SearchAndStartAttack',F)
    local start=tolua.gettypemethod(heroType,'AdvExecStartMoveAndAtkUnit',F)
    local allow=tolua.gettypemethod(stateType,'IsAllow2TakeAnyActionNow',F)
    local componentType=typeof('UnityEngine.Component')
    local transformType=typeof('UnityEngine.Transform')
    local getTransform=tolua.gettypemethod(componentType,'get_transform',F)
    local getPosition=tolua.gettypemethod(transformType,'get_position',F)
    local owner,nextCheck,notBefore=nil,0,0
    local chased,chaseSince,sampleAt,lastDistance,lastProgress=nil,0,0,nil,0
    local function alive(object)return object~=nil and not object:Equals(nil)end
    local function selectable(object)
        return alive(object) and not dead:Call(object) and not unselectable:Call(object)
    end
    local function resetChase()
        chased,chaseSince,sampleAt,lastDistance,lastProgress=nil,0,0,nil,0
    end
    local function tick()
        local now=UnityEngine.Time.realtimeSinceStartup
        if now<nextCheck then return end;nextCheck=now+0.05
        local hero=heroInstance:Get(nil)
        if not alive(hero) then owner=nil;resetChase();return end
        if hero~=owner then owner=hero;notBefore=now+0.15;resetChase() end
        -- Touchscreen and mouse emulation both count. Never interrupt a held
        -- movement input, another finger's skill press, or a skill animation.
        if UnityEngine.Input.touchCount>0 or UnityEngine.Input.GetMouseButton(0) then
            notBefore=now+0.15;resetChase();return
        end
        if now<notBefore then return end
        local sm=stateField:Get(hero)
        if not sm then resetChase();return end
        if paused:Call(sm) or skipped:Call(sm) or ooc:Call(sm) or dead:Call(hero) then return end
        local logic=tonumber(state:Call(sm))
        if logic~=3103 and logic~=4000 then resetChase();return end
        if logic==4000 then
            local target=currentTarget:Get(hero)
            if target~=chased or chaseSince==0 then
                chased,chaseSince,sampleAt,lastDistance,lastProgress=target,now,now,nil,now
                return
            end
            if now-chaseSince<0.25 or not allow:Call(sm) then return end
            local queued=nextTarget:Get(hero)
            if selectable(queued) then
                cached:Call(hero);resetChase();notBefore=now+0.25
                UnityEngine.Debug.Log('WWR_COMBAT_CHASE_RECOVER queued')
                return
            end
            if not selectable(target) then
                -- Same original path used by Hero.OnPersished, never substitute
                -- a corpse or overwrite the player's held movement command.
                clear:Call(hero);search:Call(hero);resetChase();notBefore=now+0.5
                UnityEngine.Debug.Log('WWR_COMBAT_CHASE_RECOVER invalid-target')
                return
            end
            if not locked:Call(hero) then
                start:Call(hero,target);resetChase();notBefore=now+0.5
                UnityEngine.Debug.Log('WWR_COMBAT_CHASE_RECOVER unlocked')
                return
            end
            if now-sampleAt>=0.3 then
                local hp=getPosition:Call(getTransform:Call(hero))
                local tp=getPosition:Call(getTransform:Call(target))
                local dx,dz=hp.x-tp.x,hp.z-tp.z
                local distance=dx*dx+dz*dz
                if lastDistance==nil or math.abs(distance-lastDistance)>0.04 then lastProgress=now end
                sampleAt,lastDistance=now,distance
                if now-lastProgress>=1.5 then
                    -- Rebind the original target transform and attack decision;
                    -- it still checks weapon reach, energy and skill cooldown.
                    start:Call(hero,target);resetChase();notBefore=now+0.5
                    UnityEngine.Debug.Log('WWR_COMBAT_CHASE_RECOVER stalled')
                end
            end
            return
        end
        resetChase()
        local target=nextTarget:Get(hero)
        local selected=selectable(target)
        if selected then cached:Call(hero) end
        local receiver=inputInstance:Get(nil)
        if alive(receiver) and slidingField:Get(receiver) then
            release:Call(receiver)
        elseif tonumber(state:Call(sm))==3103 then
            finish:Call(hero)
        end
        notBefore=now+0.15
        UnityEngine.Debug.Log('WWR_COMBAT_MOVE_RELEASE queued='..tostring(selected))
    end
    LateUpdateBeat:Add(function()
        local ok,err=pcall(tick)
        if not ok then
            nextCheck=UnityEngine.Time.realtimeSinceStartup+10
            UnityEngine.Debug.LogError('WWR_COMBAT_RETARGET '..tostring(err))
        end
    end)
end
UnityEngine.Debug.LogWarning('WWR_COMBAT_RETARGET_READY 159')
