-- Original campaign UI restored; availability follows server progress.
-- Apply the expedition checkpoint once per spawned hero, and capture energy.
do
    require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
    local F=65535
    local fields={}
    local function field(t,n,o)
        local key=t..'.'..n
        local handle=fields[key]
        if handle==nil then handle=tolua.getfield(typeof(t),n,F);fields[key]=handle end
        return handle:Get(o)
    end
    local function method(t,n,types)
        return tolua.gettypemethod(typeof(t),n,F,System.Type.DefaultBinder,types,nil)
    end
    local getProperty=tolua.gettypemethod(typeof('HeroEntity'),'GetProperty',F)
    local value=method('PropertyValue','GetValue',{typeof('System.Int32')})
    local setHP=method('Entity','SetHP',{typeof('System.Int64'),typeof('System.Boolean')})
    local dir='/data/data/com.codex.witchweapon.online.originalui.test/files/'
    local nextTick=0;local hero=nil;local ready=0;local applied=false
    local function number(raw,key,default)
        return tonumber(raw:match('"'..key..'"%s*:%s*([%d%.%-]+)')) or default
    end
    local function update()
        local now=UnityEngine.Time.realtimeSinceStartup
        if now<nextTick then return end;nextTick=now+0.5
        local h=field('HeroEntity','instance',nil)
        if not h or h:Equals(nil) then hero=nil;applied=false;return end
        if h~=hero then hero=h;ready=now+1.5;applied=false end
        if now<ready then return end
        local file=io.open(dir..'offline_save_v1.json','r');if not file then return end
        local raw=file:read('*a');file:close()
        if number(raw,'activeStage',0)~=3130001026 or not raw:match('"active"%s*:%s*true') then return end
        local ps=field('HeroEntity','powerAndSharp',h);if not ps then return end
        local data=field('BuildPowerAndSharp','powerData',ps);if not data then return end
        if not applied then
            local prop=getProperty:Call(h)
            local max=value:Call(field('PropertiesVO','BHP',prop),0)
            if max<=0 then return end
            setHP:Call(h,math.max(1,math.floor(max*number(raw,'mazeHP',1)+0.5)),false)
            local e=data:GetEnumerator()
            while e:MoveNext() do
                local pd=e.Current.Value;local id=tostring(field('PowerData','servantID',pd))
                tolua.getfield(typeof('PowerData'),'currentPower',F):Set(pd,number(raw,'mazeEnergy_'..id,1000))
            end
            applied=true
            UnityEngine.Debug.Log("LOCAL_MAZE_CHECKPOINT round="..number(raw,"battleMazeRound",1).." hp="..number(raw,"mazeHP",1))
        end
        local key=raw:match('"startKey"%s*:%s*"([%d%-]+)"') or ''
        local parts={'"startKey":"'..key..'"'}
        local e=data:GetEnumerator()
        while e:MoveNext() do
            local pd=e.Current.Value;local id=tostring(field('PowerData','servantID',pd))
            parts[#parts+1]='"mazeEnergy_'..id..'":'..tostring(field('PowerData','currentPower',pd))
        end
        local f=io.open(dir..'offline_battle_energy.tmp','w')
        if f then f:write('{'..table.concat(parts,',')..'}');f:close();os.rename(dir..'offline_battle_energy.tmp',dir..'offline_battle_energy.json') end
    end
    local failed=false
    UpdateBeat:Add(function()
        if failed then return end
        local ok,err=pcall(update)
        if not ok then failed=true;UnityEngine.Debug.LogError('LOCAL_MAZE_CARRY '..tostring(err)) end
    end)
end

-- Refresh the original observable models after a committed inventory transaction.
-- Native callbacks still show their original loot and sale dialogs.
do
    local nextCheck,lastRevision,pending,lastCollection,collectionPending=0,nil,nil,nil,false
    local function supplyRefresh()
        local now=UnityEngine.Time.realtimeSinceStartup
        if now<nextCheck then return end
        nextCheck=now+1
        local f=io.open('/data/data/com.codex.witchweapon.online.originalui.test/files/offline_save_v1.json','r')
        if not f then return end
        local text=f:read('*a');f:close()
        local player=WaterBell.ProjX.Data.Entity.UserInfo.GetInstance():GetPlayer()
        if not player then return end
        -- ActivityPlay's constructor/setContent clear this balance on seasonal
        -- initialization. Offline supplies persist across those lifecycle resets.
        local activityStamina=tonumber(text:match('"activityStamina"%s*:%s*(%d+)')) or 200
        if player.ActivityStamina~=activityStamina then player.ActivityStamina=activityStamina end
        local revision=tonumber(text:match('"inventoryRevision"%s*:%s*(%d+)')) or 0
        local collection=tonumber(text:match('"collectionRevision"%s*:%s*(%d+)')) or 0
        if lastCollection==nil then lastCollection=collection end
        if collection~=lastCollection then lastCollection=collection;collectionPending=true;pending=now+1 end
        if lastRevision==nil then lastRevision=revision end
        if revision~=lastRevision then lastRevision=revision;pending=now+1 end
        if not pending or now<pending then return end
        require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
        for _,name in ipairs({'BackpackGetAllItemsLogic','BackpackGetAllEquipsLogic'}) do
            local msg=tolua.createinstance(typeof('WaterBell.ProjX.Data.NetIO.'..name))
            tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'),'SendMsg',65535):Call(msg)
        end
        if collectionPending then
            for _,name in ipairs({'GetServantListLogic','RoleGetRoleInfoLogic'}) do
                local msg=tolua.createinstance(typeof('WaterBell.ProjX.Data.NetIO.'..name))
                tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'),'SendMsg',65535):Call(msg)
            end
            collectionPending=false
        end
        player.Gold=tonumber(text:match('"gold"%s*:%s*(%d+)'))
        -- The generated Lua wrapper exposes only Diamond's getter.
        local diamonds=tonumber(text:match('"rmb"%s*:%s*(%d+)')) or 100000
        tolua.getproperty(typeof('WaterBell.ProjX.Data.Entity.ObservablePlayer'),'Diamond',65535):Set(player,int64.new(diamonds),nil)
        player.Stamina=tonumber(text:match('"stamina"%s*:%s*(%d+)')) or 200
        pending=nil
    end
    UpdateBeat:Add(function()
        local ok,err=pcall(supplyRefresh)
        if not ok then UnityEngine.Debug.LogError('OFFLINE_SUPPLY '..tostring(err));nextCheck=UnityEngine.Time.realtimeSinceStartup+10 end
    end)
end

-- UIChest.Open(14, id) in this client only logs "item". Complete its
-- fixed-gift preview with the original widgets and native claim callback.
do
    require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
    local chestType=typeof('UIChest');local detailType=typeof('ItemInfoView')
    local chestFields,detailFields,chestMethods={},{},{}
    local function detailField(name,ui)
        local handle=detailFields[name]
        if handle==nil then handle=tolua.getfield(detailType,name,65535);detailFields[name]=handle end
        return handle:Get(ui)
    end
    local resetNumber=tolua.gettypemethod(detailType,'ReSetNumber',65535)
    local function method(name,types)
        local handle=chestMethods[name]
        if handle==nil then
            handle=tolua.gettypemethod(chestType,name,65535,System.Type.DefaultBinder,types,nil)
            chestMethods[name]=handle
        end
        return handle
    end
    local nextCheck,last=0,nil
    local function field(name,ui)
        local handle=chestFields[name]
        if handle==nil then handle=tolua.getfield(chestType,name,65535);chestFields[name]=handle end
        return handle:Get(ui)
    end
    local function update()
        local now=UnityEngine.Time.realtimeSinceStartup
        if now<nextCheck then return end;nextCheck=now+0.25
        -- Native loot changes the selected label before the asynchronous full
        -- inventory refresh. Keep it bound to the refreshed original model.
        local detail=(WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(detailType)
        if detail and detailField('itemContainer',detail).gameObject.activeInHierarchy then
            resetNumber:Call(detail)
        end
        local ui=(WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(chestType)
        if not ui or ui:Equals(nil) then last=nil;return end
        if ui==last or tonumber(field('dataType',ui))~=14 then return end
        field('chooseOneWidget',ui).gameObject:SetActive(false)
        field('itemWdiget',ui).gameObject:SetActive(true)
        field('itemBg',ui).gameObject:SetActive(true)
        field('chestItemGetAwardBtn',ui).gameObject:SetActive(true)
        field('closeBtn',ui).gameObject:SetActive(true)
        field('cannelBtn',ui).gameObject:SetActive(true)
        local name,desc='物品礼包','获得物品说明中的全部奖励。'
        if detail and tostring(detailField('itemId',detail))==tostring(field('dataID',ui)) then
            name=detailField('itemName',detail).text
            desc=detailField('descItemText',detail).text
            if desc=='' then desc=detailField('item_descText',detail).text end
        end
        local rewards=method('GetChestItemDatas',{typeof('System.Int64')}):Call(ui,field('dataID',ui))
        local entries=rewards:GetEnumerator()
        if entries:MoveNext() then method('CreateItem',{typeof('LotteryLootData')}):Call(ui,entries.Current) end
        field('itemName',ui).text='奖励预览'
        local text=field('chestItemText',ui)
        text.fontSize=22
        text.text='使用1个，获得全部奖励：\n'..desc
        last=ui
    end
    UpdateBeat:Add(function()
        local ok,err=pcall(update)
        if not ok then UnityEngine.Debug.LogError('OFFLINE_INVENTORY '..tostring(err));nextCheck=UnityEngine.Time.realtimeSinceStartup+10 end
    end)
end

-- The native MobInfo loader ignores LifeTime. Use its normal death/AI cleanup
-- when an allied summon reaches its local lifetime; never touch enemy mobs.
do
    require 'tolua.reflection';tolua.loadassembly('Assembly-CSharp')
    local kind=typeof('unit.MonsterEntity');local voType=typeof('MonsterVO')
    local voField=tolua.getfield(kind,'monsterVO',65535)
    local idField=tolua.getfield(voType,'ID',65535)
    local master=tolua.getproperty(typeof('Entity'),'Master',65535)
    local die=tolua.gettypemethod(kind,'ExecDeath',65535)
    local heroField=tolua.getfield(typeof('HeroEntity'),'instance',65535)
    local ttl={['332010380501']=18,['332010381501']=20,['332010381701']=25,['332010340501']=16}
    local seen,nextCheck={},0
    local function tick()
        local now=UnityEngine.Time.time
        if now<nextCheck then return end;nextCheck=now+0.25
        -- The same native singleton gates the expedition checkpoint above.
        -- Do not scan battle actors while the player is outside a battle.
        local hero=heroField:Get(nil)
        if not hero or hero:Equals(nil) then
            for id in pairs(seen) do seen[id]=nil end
            return
        end
        local arr=UnityEngine.Object.FindObjectsOfType(kind);local live={} 
        for i=0,arr.Length-1 do
            local entity=arr[i];local vo=voField:Get(entity)
            local duration=vo and ttl[tostring(idField:Get(vo))]
            if duration and master:Get(entity,nil) then
                local id=entity:GetInstanceID();live[id]=true
                local entry=seen[id]
                if not entry then entry={born=now,expired=false};seen[id]=entry end
                if not entry.expired and now-entry.born>=duration then
                    entry.expired=true;die:Call(entity)
                end
            end
        end
        for id in pairs(seen) do if not live[id] then seen[id]=nil end end
    end
    UpdateBeat:Add(function()
        local ok,err=pcall(tick)
        if not ok then UnityEngine.Debug.LogError('OFFLINE_SUMMON '..tostring(err));nextCheck=UnityEngine.Time.time+10 end
    end)
end

UnityEngine.Debug.LogWarning('WWR_BACKGROUND_OBSERVERS_READY 151')
