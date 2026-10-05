"""Exercise scene replacement and pooled-row lifetimes in the real Lua runtime."""
from pathlib import Path
import unittest
from test_weapon_selection_cache import LuaState

LUA = Path(__file__).resolve().parents[1] / 'lua'
MOCK = r'''
TEST={searches=0, reads=0, handles=0, paints=0, callbacks={}, scene={}}
UnityEngine={Time={realtimeSinceStartup=0},Object={},Debug={LogWarning=function()end,LogError=error}}
function TEST.object(t)
    function t:Equals(other)return self.dead==true or self==other end
    return t
end
function UnityEngine.Object.FindObjectOfType(kind)
    TEST.searches=TEST.searches+1
    return TEST.scene[kind]
end
UpdateBeat={Add=function(self,fn)TEST.callbacks[fn]=true end,
    Remove=function(self,fn)TEST.callbacks[fn]=nil end,
    Count=function(self)local n=0;for _ in pairs(TEST.callbacks)do n=n+1 end;return n end}
LateUpdateBeat={Count=function()return 0 end}
function TEST.step(now)
    UnityEngine.Time.realtimeSinceStartup=now
    for fn in pairs(TEST.callbacks)do fn() end
end
package.preload['tolua.reflection']=function()end
tolua={loadassembly=function()end}
typeof=function(t)return t end
function tolua.getproperty(kind,name)
    TEST.handles=TEST.handles+1
    return {Get=function(self,obj)TEST.reads=TEST.reads+1; return obj[name] end,
        Destroy=function()error('Cached handles must not be destroyed')end}
end
function tolua.getmethod(kind,name)
    return {Call=function(self,view,value)TEST.paints=TEST.paints+1;view[name]=value end}
end
CSVPool={AchievementConfig=function()return {{ID=1,arg1='count'}}end}
function TEST.row()
    local view=TEST.object({QuestInfo={Info={Type=1,Argu1=10},Status=-1,Meta=0}})
    local label=TEST.object({gameObject={activeSelf=true},text=''})
    local owner=TEST.object({activeInHierarchy=true})
    owner.transform={GetComponent=function()return view end,
        Find=function()return {GetComponent=function()return label end}end}
    return owner,view,label
end
'''

class RuntimePerformanceTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaState(); self.lua.execute(MOCK)
    def tearDown(self):
        self.lua.__exit__()
    def probes(self):
        self.lua.execute((LUA/'init-runtime-ui-probes.lua').read_text(encoding='utf-8'))
    def rows(self):
        self.lua.execute('PATCH=(function()\n'+(LUA/'TaskItemPatch-online-v6.lua').read_text(encoding='utf-8')+'\nend)()')
    def test_missing_queries_are_bounded_and_new_panel_is_found_within_native_open_window(self):
        self.probes()
        self.lua.execute('''for i=1,100 do WWRRuntimeUI.Find('Task')end;assert(TEST.searches==1)
            TEST.scene.Task=TEST.object({gameObject={activeInHierarchy=true}})
            UnityEngine.Time.realtimeSinceStartup=.101
            assert(WWRRuntimeUI.Find('Task')==TEST.scene.Task and TEST.searches==2)
            for i=1,1000 do assert(WWRRuntimeUI.Find('Task')==TEST.scene.Task)end
            assert(TEST.searches==2)''')
    def test_destroyed_object_is_replaced_immediately_without_waiting_for_ttl(self):
        self.probes()
        self.lua.execute('''local first=TEST.object({gameObject={activeInHierarchy=true}})
            TEST.scene.Task=first;assert(WWRRuntimeUI.Find('Task')==first)
            first.dead=true
            local second=TEST.object({gameObject={activeInHierarchy=true}});TEST.scene.Task=second
            assert(WWRRuntimeUI.Find('Task')==second and TEST.searches==2)''')
    def test_reused_panel_reopens_immediately_and_inactive_instance_can_be_replaced(self):
        self.probes()
        self.lua.execute('''local first=TEST.object({gameObject={activeInHierarchy=true}})
            TEST.scene.Task=first;WWRRuntimeUI.Find('Task')
            first.gameObject.activeInHierarchy=false;TEST.scene.Task=nil
            assert(WWRRuntimeUI.Find('Task')==nil)
            first.gameObject.activeInHierarchy=true
            assert(WWRRuntimeUI.Find('Task')==first and TEST.searches==1)
            first.gameObject.activeInHierarchy=false
            local second=TEST.object({gameObject={activeInHierarchy=true}});TEST.scene.Task=second
            UnityEngine.Time.realtimeSinceStartup=.101
            assert(WWRRuntimeUI.Find('Task')==second and TEST.searches==2)''')
    def test_many_rows_register_one_observer_and_hidden_rows_do_no_model_work(self):
        self.rows()
        self.lua.execute('''TEST.owners={}
            for i=1,170 do local o=TEST.row();o.activeInHierarchy=false
                PATCH:Start(o);TEST.owners[i]=o end
            assert(UpdateBeat:Count()==1)
            for i=1,100 do TEST.step(i*.5)end
            assert(TEST.reads==0 and TEST.handles==0 and TEST.paints==0)''')
    def test_visible_row_repaints_and_reuses_handles_after_page_reopens(self):
        self.rows()
        self.lua.execute('''local o,v,label=TEST.row();PATCH:Start(o);TEST.step(0)
            assert(TEST.paints==0 and TEST.handles==6)
            o.activeInHierarchy=false;v.QuestInfo.Meta=10;v.QuestInfo.Status=0
            TEST.step(.5);assert(TEST.paints==0)
            o.activeInHierarchy=true;TEST.step(1)
            assert(TEST.paints==2 and TEST.handles==6 and label.text:find('10',1,true))''')
    def test_hidden_native_scene_blocks_active_pooled_panels_and_row_models(self):
        self.probes();self.rows()
        self.lua.execute('''local manager={CheckSceneIsShow=function()return TEST.shown end}
            WaterBell={ProjX={View={UIFrame={UISceneManager={getInstance=function()return manager end}}}}}
            TEST.shown=false
            local o=TEST.row();PATCH:Start(o)
            TEST.scene['WaterBell.ProjX.View.Panel.TaskPanelController']=TEST.object({gameObject={activeInHierarchy=true}})
            TEST.step(.5)
            assert(WWRRuntimeUI.Find('WaterBell.ProjX.View.Panel.TaskPanelController')==nil)
            assert(TEST.searches==0 and TEST.reads==0)
            TEST.shown=true;TEST.step(1)
            assert(WWRRuntimeUI.Find('WaterBell.ProjX.View.Panel.TaskPanelController')~=nil)
            assert(TEST.searches==1 and TEST.reads==6)''')
    def test_map_daily_and_furnace_cache_follow_original_scenes_without_gating_battle_rewards(self):
        self.probes()
        self.lua.execute('''local manager={CheckSceneIsShow=function(self,id)return id==TEST.shown end}
            WaterBell={ProjX={View={UIFrame={UISceneManager={getInstance=function()return manager end}}}}}
            local pages={['WaterBell.ProjX.View.Panel.MapPanelControl']=2,
                ['WaterBell.ProjX.View.Panel.SelectLevelDetail']=3,
                ['WaterBell.ProjX.View.Panel.ClimbTowerLevelDetail']=30,['DailyPanelControl']=15,['TrialSelectLevel']=15}
            for name in pairs(pages)do TEST.scene[name]=TEST.object({gameObject={activeInHierarchy=true}})end
            TEST.shown=11
            for name in pairs(pages)do assert(WWRRuntimeUI.Find(name)==nil)end
            assert(TEST.searches==0)
            local time=0
            for name,id in pairs(pages)do
                time=time+.1;UnityEngine.Time.realtimeSinceStartup=time;TEST.shown=id
                assert(WWRRuntimeUI.Find(name)==TEST.scene[name])
            end
            assert(TEST.searches==5)
            local reward='WaterBell.ProjX.View.Panel.SettlementUI'
            TEST.scene[reward]=TEST.object({gameObject={activeInHierarchy=true}})
            assert(WWRRuntimeUI.Find(reward)==TEST.scene[reward])''')
    def test_summon_cleanup_skips_hall_keeps_allied_lifetime_and_resets_between_battles(self):
        self.lua.execute(r'''
            TEST.hero=nil;TEST.monsters={Length=0};TEST.scans=0;TEST.deaths=0
            UnityEngine.Time.time=0
            tolua.getfield=function(kind,name)
                TEST.handles=TEST.handles+1
                return {Get=function(self,obj)
                    if name=='instance' then return TEST.hero end
                    return obj[name]
                end}
            end
            tolua.getproperty=function(kind,name)
                TEST.handles=TEST.handles+1
                return {Get=function(self,obj)return obj[name]end}
            end
            tolua.gettypemethod=function()
                TEST.handles=TEST.handles+1
                return {Call=function(self,obj)TEST.deaths=TEST.deaths+1 end}
            end
            UnityEngine.Object.FindObjectsOfType=function()
                TEST.scans=TEST.scans+1;return TEST.monsters
            end
        ''')
        source=(LUA/'init-campaign-background.lua').read_text(encoding='utf-8')
        self.lua.execute(source[source.index('-- The native MobInfo loader'):])
        self.lua.execute(r'''
            for i=0,100 do UnityEngine.Time.time=i*.25;TEST.step(i*.25)end
            assert(TEST.scans==0 and TEST.deaths==0 and TEST.handles==5)
            TEST.hero=TEST.object({})
            local ally={monsterVO={ID='332010380501'},Master={}}
            function ally:GetInstanceID()return 1 end
            local enemy={monsterVO={ID='332010380501'}}
            function enemy:GetInstanceID()return 2 end
            TEST.monsters={Length=2,[0]=ally,[1]=enemy}
            UnityEngine.Time.time=30;TEST.step(30)
            UnityEngine.Time.time=47.75;TEST.step(47.75);assert(TEST.deaths==0)
            UnityEngine.Time.time=48;TEST.step(48);assert(TEST.deaths==1)
            UnityEngine.Time.time=49;TEST.step(49);assert(TEST.deaths==1)
            TEST.hero.dead=true;UnityEngine.Time.time=50;TEST.step(50)
            local scans=TEST.scans
            UnityEngine.Time.time=51;TEST.step(51);assert(TEST.scans==scans)
            TEST.hero=TEST.object({});UnityEngine.Time.time=52;TEST.step(52)
            assert(TEST.deaths==1)
            UnityEngine.Time.time=70;TEST.step(70);assert(TEST.deaths==2)
            assert(TEST.handles==5)
        ''')
    def test_inventory_count_refresh_reuses_reflection_handles(self):
        self.lua.execute(r'''
            System={Type={DefaultBinder={}}};TEST.reset=0
            TEST.detail={itemContainer={gameObject={activeInHierarchy=true}}}
            TEST.scene.ItemInfoView=TEST.detail
            tolua.getfield=function(kind,name)
                TEST.handles=TEST.handles+1
                return {Get=function(self,obj)return obj[name]end}
            end
            tolua.gettypemethod=function(kind,name)
                TEST.handles=TEST.handles+1
                return {Call=function(self,obj)TEST.reset=TEST.reset+1 end}
            end
        ''')
        source=(LUA/'init-campaign-background.lua').read_text(encoding='utf-8')
        self.lua.execute(source[source.index('-- UIChest.Open'):source.index('-- The native MobInfo loader')])
        self.lua.execute(r'''
            for i=0,1000 do TEST.step(i*.25)end
            assert(TEST.handles==2 and TEST.reset==1001)
            TEST.detail.itemContainer.gameObject.activeInHierarchy=false
            TEST.step(251);assert(TEST.reset==1001 and TEST.handles==2)
        ''')
    def test_uninitialized_native_scene_dictionary_falls_back_to_normal_lookup(self):
        self.probes()
        self.lua.execute('''local manager={CheckSceneIsShow=function()error('not initialized')end}
            WaterBell={ProjX={View={UIFrame={UISceneManager={getInstance=function()return manager end}}}}}
            local name='WaterBell.ProjX.View.Panel.TaskPanelController'
            TEST.scene[name]=TEST.object({gameObject={activeInHierarchy=true}})
            assert(WWRRuntimeUI.Find(name)==TEST.scene[name] and TEST.searches==1)''')
    def test_destroyed_rows_are_released_without_a_destroy_event(self):
        self.rows()
        self.lua.execute('''local o,v=TEST.row();PATCH:Start(o);TEST.step(0)
            o.dead=true;TEST.step(.5)
            local reads=TEST.reads;o.dead=false;TEST.step(1)
            assert(TEST.reads==reads)
            PATCH:Start(o);PATCH:Start(o);assert(UpdateBeat:Count()==1)
            PATCH:OnDestroy(o);TEST.step(2);assert(TEST.reads==reads)''')
    def test_guide_cache_suppresses_reparents_and_new_managed_buttons_without_scene_scans(self):
        self.lua.execute(r'''
            TEST.scans,TEST.trees,TEST.hash=0,0,{}
            function TEST.hash:GetType()return 'Dictionary<string,Transform>' end
            TEST.sceneID=11
            function TEST.button()
                local button=TEST.object({isEnabled=true})
                button.sprite,button.collider=TEST.object({enabled=true}),TEST.object({enabled=true})
                local go=TEST.object({activeSelf=true})
                function button:GetInstanceID()return self end
                function go:SetActive(value)self.activeSelf=value end
                function go:GetComponentsInChildren(kind)
                    TEST.trees=TEST.trees+1
                    return {Length=1,[0]=kind=='UISprite' and button.sprite or button.collider}
                end
                button.gameObject=go
                local control=TEST.object({button=button})
                local target=TEST.object({GetComponent=function()return control end})
                return button,control,target
            end
            TEST.button1,TEST.guide,TEST.target=TEST.button()
            TEST.hash.ButtonTaskGuide=TEST.target
            UnityEngine.Resources={FindObjectsOfTypeAll=function()return {Length=1,[0]=TEST.guide}end}
            UnityEngine.Object.FindObjectsOfType=function()
                TEST.scans=TEST.scans+1;return {Length=1,[0]=TEST.guide}
            end
            tolua.findtype=typeof
            tolua.getfield=function(kind,name)
                return {Get=function(self,target)
                    if name=='_hash' then return TEST.hash end
                    return target[name]
                end}
            end
            tolua.getmethod=function(kind,name)
                return {Call=function(self,target,key)
                    if name=='ContainsKey' then return target[key]~=nil end
                    return target[key]
                end}
            end
            local manager={GetCurrentUISceneState=function()return {SceneID=TEST.sceneID}end}
            WaterBell={ProjX={View={UIFrame={UISceneManager={getInstance=function()return manager end}}}}}
            LateUpdateBeat={Add=function(self,fn)TEST.late=fn end}
        ''')
        self.lua.execute((LUA/'init-optional-entry-visibility.lua').read_text(encoding='utf-8'))
        self.lua.execute('''for i=1,10 do UnityEngine.Time.realtimeSinceStartup=i*.1;TEST.late()end
            local scans,trees=TEST.scans,TEST.trees
            for i=1,60 do
                TEST.button1.gameObject.activeSelf=true;TEST.button1.sprite.enabled=true
                UnityEngine.Time.realtimeSinceStartup=1+i/30;TEST.late()
                assert(not TEST.button1.gameObject.activeSelf and not TEST.button1.sprite.enabled)
            end
            assert(TEST.scans-scans<=4 and TEST.trees==trees)
            local button,control,target=TEST.button();TEST.hash.ButtonTaskGuide=target
            UnityEngine.Time.realtimeSinceStartup=3.01;TEST.late()
            assert(not button.gameObject.activeSelf and not button.sprite.enabled and not button.collider.enabled)
        ''')

if __name__=='__main__': unittest.main()
