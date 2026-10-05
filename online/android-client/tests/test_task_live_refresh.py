"""Exercise original ToLua 5.1 with asynchronous task responses and reward clicks."""
from pathlib import Path
import unittest
from test_weapon_selection_cache import LuaState

SCRIPT = Path(__file__).resolve().parents[1] / 'lua/init-task-live-refresh.lua'

MOCK = r'''
TEST = {requests=0, claims=0, popups=0, rewards=0, busy=0, logs={}, rows={}}
local serial=0
function TEST.object(value)
    serial=serial+1
    value.serial=serial
    function value:GetInstanceID() return self.serial end
    function value:Equals(other) return (self.destroyed and other==nil) or self==other end
    return value
end
function TEST.list(values)
    local out={Count=#values,Length=#values}
    for i,v in ipairs(values) do out[i-1]=v end
    function out:get_Item(index)return self[index] end
    return out
end
function TEST.button(callback)
    local button=TEST.object({gameObject=TEST.object({activeInHierarchy=true}),isEnabled=true})
    button.onClick=TEST.list({callback})
    button.gameObject.button=button
    button.listener=TEST.object({})
    return button
end
function TEST.nativeClaim()
    TEST.claims=TEST.claims+1
    TEST.busy=1
end
function TEST.respond(ids, amount)
    for _,id in ipairs(ids) do
        for i=0,TEST.quest.QuestJob.Count-1 do
            if TEST.quest.QuestJob[i].ID==id then TEST.quest.QuestJob[i].Status=1 end
        end
    end
    TEST.rewards=TEST.rewards+amount
    TEST.popups=TEST.popups+1
    TEST.busy=0
end
TEST.quest=TEST.object({QuestJob=TEST.list({
    TEST.object({ID=101,Status=-1,Valid=1}),
    TEST.object({ID=102,Status=0,Valid=1}),
    TEST.object({ID=201,Status=0,Valid=1})}),
    QuestMeta=TEST.list({TEST.object({JobID=101,Meta=0}),TEST.object({JobID=201,Meta=4})})})
TEST.daily=TEST.list({TEST.object({ID=101,Status=-1,Valid=1,Meta=0}),TEST.object({ID=102,Status=0,Valid=1,Meta=0})})
TEST.main=TEST.list({TEST.object({ID=201,Status=-1,Valid=1,Meta=0})})
TEST.model=TEST.object({DailyQuests=TEST.daily,StoryQuest=TEST.main,
    SideQuests=TEST.list({}),RandomQuests=TEST.list({}),GuideQuest=TEST.list({}),
    ActivityQuest=TEST.list({}),ActivityDailyQuest=TEST.list({}),QuestResult=0})
TEST.manager=TEST.object({QuestSystemManager=TEST.model})
TEST.panel=TEST.object({gameObject=TEST.object({activeInHierarchy=true}),currentMode=0,
    id=201,taskType=2,Current_Grid=TEST.object({}),buttonFinish=TEST.button(TEST.nativeClaim),
    getAllBtn=TEST.button(TEST.nativeClaim),paints=0,achievements=0,allButtons=0})
function TEST.panel:GetComponent(name) return TEST.manager end
function TEST.panel:GetComponentsInChildren(kind) return TEST.list(TEST.rows) end
function TEST.panel:ReFreshGrid(grid,fresh) assert(fresh==true); self.paints=self.paints+1 end
function TEST.panel:ReFreshAchieGrid() self.achievements=self.achievements+1 end
function TEST.panel:SetGetAllBtn() self.allButtons=self.allButtons+1 end
function TEST.row(index)
    local row=TEST.object({gameObject=TEST.object({activeInHierarchy=true}),
        QuestInfo=TEST.daily[index],getAwardBtn=TEST.button(TEST.nativeClaim)})
    TEST.rows[#TEST.rows+1]=row
    return row
end
TEST.row(0); TEST.row(1)
TEST.achieve={AchieveJob=TEST.list({}),metas=TEST.list({})}
function TEST.achieve:GetProgressingAchieveLength()return self.metas.Count end
function TEST.achieve:GetProgressingAchieveByIndex(index)return self.metas[index] end
TEST.user={GetQuest=function()return TEST.quest end,GetAchievement=function()return TEST.achieve end}
TEST.protocol={getNormalMsgCount=function()return TEST.busy end}
typeof=function(name)
    if name=='UIEventListener+VoidDelegate' then return nil end
    return name
end
require=function()return {} end
tolua={loadassembly=function()end}
function tolua.getproperty(kind,name)
    return {Get=function(self,target)return target[name] end,
        Set=function(self,target,value)target[name]=value end}
end
function tolua.getfield(kind,name)
    return {Get=function(self,target)return target[name] end}
end
function tolua.getmethod(kind,name,...)
    assert(kind~=nil,'Type expected, got nil')
    local arity=select('#',...)
    return {Call=function(self,target,...)
        assert(select('#',...)==arity,'wrong typed method arity: '..name)
        return target[name](target,...)
    end}
end
function tolua.gettypemethod(kind,name)
    if name=='GetInstance' then return {Call=function()return TEST.protocol end} end
    if name=='SendMsg' then return {Call=function()
        TEST.requests=TEST.requests+1
        if TEST.fetchHandler then TEST.fetchHandler() end
    end} end
    return {Call=function(self,target)return target[name](target) end}
end
tolua.createinstance=function(kind)return {} end
UIEventListener={Get=function(go)return go.button.listener end}
EventDelegate={Execute=function(list)
    for i=0,list.Count-1 do list[i]() end
end}
UnityEngine={Time={realtimeSinceStartup=0},Object={FindObjectOfType=function(kind)
    if kind=='WaterBell.ProjX.View.Panel.TaskPanelController' then return TEST.panel end
    if kind=='WaterBell.ProjX.View.Panel.GetLootsPanel' then return TEST.popup end
end},
    Debug={Log=function(value)TEST.logs[#TEST.logs+1]=value end,
        LogWarning=function(value)TEST.logs[#TEST.logs+1]=value end,
        LogError=function(value)error(value)end}}
WaterBell={ProjX={Data={Entity={UserInfo={GetInstance=function()return TEST.user end}}}}}
UpdateBeat={Add=function(self,fn)TEST.tick=fn end}
function TEST.step(count)
    for i=1,count or 1 do
        UnityEngine.Time.realtimeSinceStartup=UnityEngine.Time.realtimeSinceStartup+0.3
        TEST.tick()
    end
end
function TEST.click(button)
    if button.onClick~=nil then EventDelegate.Execute(button.onClick) end
    if button.listener.onClick~=nil then button.listener.onClick(button.gameObject) end
end
'''

class TaskLiveTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaState()
        self.lua.execute(MOCK)
        self.lua.execute(SCRIPT.read_text(encoding='utf-8'))
        self.lua.execute('TEST.step()')
    def tearDown(self):
        self.lua.__exit__()
    def test_all_entries_fetch_once_and_no_idle_network_polling(self):
        self.lua.execute('TEST.step(200); assert(TEST.requests==1); TEST.panel.currentMode=1; TEST.step(); assert(TEST.requests==2)')
    def test_server_status_and_meta_replace_stale_daily_and_main_models(self):
        self.lua.execute('''assert(TEST.main[0].Status==0 and TEST.main[0].Meta==4)
            TEST.quest.QuestJob[0].Status=0; TEST.quest.QuestMeta[0].Meta=10
            TEST.step(); assert(TEST.daily[0].Status==0 and TEST.daily[0].Meta==10)''')
    def test_duplicate_single_click_does_not_repeat_native_rewards(self):
        self.lua.execute('''local b=TEST.rows[2].getAwardBtn
            TEST.click(b); TEST.click(b); assert(TEST.claims==1)
            TEST.respond({102},50); TEST.step(3); TEST.click(b)
            assert(TEST.claims==1 and TEST.popups==1 and TEST.rewards==50)
            assert(TEST.daily[1].Status==1)''')
    def test_bulk_and_single_share_one_inflight_gate(self):
        self.lua.execute('''TEST.quest.QuestJob[0].Status=0; TEST.step()
            TEST.click(TEST.panel.getAllBtn); TEST.click(TEST.rows[1].getAwardBtn)
            TEST.click(TEST.panel.getAllBtn); assert(TEST.claims==1)
            TEST.respond({101,102},80); TEST.step()
            TEST.click(TEST.panel.getAllBtn); assert(TEST.claims==1 and TEST.rewards==80)''')
    def test_claim_waits_for_native_message_and_timeout_only_fetches(self):
        self.lua.execute('''TEST.busy=1; TEST.click(TEST.panel.buttonFinish); assert(TEST.claims==0)
            TEST.busy=0; TEST.step(); TEST.click(TEST.panel.buttonFinish); assert(TEST.claims==1)
            TEST.step(60); TEST.click(TEST.panel.buttonFinish); assert(TEST.claims==1)
            assert(TEST.popups==0 and TEST.rewards==0)
            TEST.busy=0; TEST.step(4); assert(TEST.requests>=2)''')
    def test_close_restores_native_callbacks_without_erasing_inflight_claim(self):
        self.lua.execute('''local b=TEST.rows[2].getAwardBtn; TEST.click(b)
            TEST.panel.gameObject.activeInHierarchy=false; TEST.step()
            assert(b.onClick~=nil and b.listener.onClick==nil)
            TEST.panel.gameObject.activeInHierarchy=true; TEST.step(); TEST.click(b)
            assert(TEST.claims==1); TEST.respond({102},50); TEST.step(3)
            assert(TEST.daily[1].Status==1)''')
    def test_initial_achievement_tab_preserves_native_drawing_then_updates_changes(self):
        self.lua.execute("""TEST.panel.currentMode='AchievTask'; TEST.step(); assert(TEST.panel.achievements==0)
            TEST.achieve.AchieveJob=TEST.list({{ID=1,Status=0}})
            TEST.step();assert(TEST.panel.achievements==1)""")
    def test_unchanged_mainline_responses_preserve_scroll_and_selection(self):
        self.lua.execute('''TEST.panel.currentMode='MainLine'; TEST.step(4)
            local paints=TEST.panel.paints; local requests=TEST.requests
            TEST.step(60); assert(TEST.requests>requests)
            assert(TEST.panel.paints==paints)''')
    def test_mainline_updates_while_the_same_page_stays_open(self):
        self.lua.execute('''TEST.panel.currentMode='MainLine'; TEST.step(4)
            TEST.quest.QuestJob[2].Status=-1; TEST.step()
            TEST.fetchHandler=function()
                TEST.quest.QuestJob[2].Status=0; TEST.quest.QuestMeta[1].Meta=10
            end
            TEST.step(25)
            assert(TEST.main[0].Status==0 and TEST.main[0].Meta==10)
            assert(TEST.requests>=3 and TEST.requests<=4)
            assert(TEST.claims==0 and TEST.rewards==0 and TEST.popups==0)
            local requests=TEST.requests
            TEST.panel.gameObject.activeInHierarchy=false; TEST.step(100)
            assert(TEST.requests==requests)''')
    def test_claim_refreshes_authoritative_successor_without_reopening(self):
        self.lua.execute('''TEST.panel.currentMode='MainLine'; TEST.step(4)
            TEST.main=TEST.list({TEST.main[0],TEST.object({ID=202,Status=-1,Valid=1,Meta=0})})
            TEST.model.StoryQuest=TEST.main
            TEST.quest.QuestJob=TEST.list({TEST.quest.QuestJob[0],TEST.quest.QuestJob[1],
                TEST.quest.QuestJob[2],TEST.object({ID=202,Status=-1,Valid=1})})
            TEST.fetchHandler=function()TEST.quest.QuestJob[3].Status=0 end
            local requests=TEST.requests
            TEST.click(TEST.panel.buttonFinish); TEST.respond({201},50); TEST.step(6)
            assert(TEST.requests==requests+1)
            assert(TEST.main[0].Status==1 and TEST.main[1].Status==0)
            assert(TEST.claims==1 and TEST.rewards==50 and TEST.popups==1)''')
    def test_mainline_bulk_uses_story_jobs_and_waits_for_the_native_popup(self):
        self.lua.execute('''TEST.panel.currentMode='MainLine'; TEST.panel.taskType=6; TEST.step(4)
            local before=TEST.panel.paints
            TEST.click(TEST.panel.getAllBtn); assert(TEST.claims==1)
            assert(string.find(TEST.logs[#TEST.logs],'201'))
            TEST.quest.QuestJob[2].Status=1; TEST.busy=0
            TEST.popup=TEST.object({gameObject={activeInHierarchy=true}})
            TEST.step(30); assert(TEST.panel.paints==before)
            TEST.click(TEST.panel.getAllBtn); assert(TEST.claims==1)
            TEST.popup.gameObject.activeInHierarchy=false; TEST.step(6)
            assert(TEST.main[0].Status==1 and TEST.claims==1)''')
    def test_achievement_progress_uses_typed_integer_reflection(self):
        self.lua.execute('''TEST.achieve.metas=TEST.list({{HeadID=20,Args=TEST.list({'1'})}})
            TEST.panel.currentMode='AchievTask'; TEST.step(4)
            local before=TEST.panel.achievements
            TEST.achieve.metas[0].Args[0]='2'; TEST.step()
            assert(TEST.panel.achievements==before+1)''')
    def test_mainline_queries_wait_for_gameplay_and_claim_queue(self):
        self.lua.execute('''TEST.panel.currentMode='MainLine'; TEST.step(4)
            local requests=TEST.requests; TEST.busy=1; TEST.step(50)
            assert(TEST.requests==requests)
            TEST.busy=0; TEST.step(4); assert(TEST.requests==requests+1)
            TEST.click(TEST.panel.buttonFinish); TEST.busy=0; TEST.step(20)
            assert(TEST.requests==requests+1)
            TEST.respond({201},50); TEST.step(4); assert(TEST.requests==requests+2)''')
    def test_existing_listener_is_preserved_and_missing_nested_type_is_optional(self):
        self.lua.execute('''TEST.panel.gameObject.activeInHierarchy=false; TEST.step()
            local b=TEST.rows[2].getAwardBtn; local calls=0
            b.listener.onClick=function()calls=calls+1 end
            TEST.panel.gameObject.activeInHierarchy=true; TEST.step()
            assert(b.onClick~=nil); TEST.click(b); assert(calls==1 and TEST.claims==1)''')

if __name__=='__main__': unittest.main()
