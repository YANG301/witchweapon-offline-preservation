"""Check the native duplicate Guild display repair without any wallet mutation."""
from pathlib import Path
import unittest
from test_weapon_selection_cache import LuaState
from test_task_live_refresh import MOCK

SCRIPT = Path(__file__).resolve().parents[1] / 'lua/init-task-loot-display.lua'
REWARD_MOCK = r'''
function tolua.getfield(kind,name)
    return {Get=function(self,target)return target[name] end,
        Set=function(self,target,value)target[name]=value end}
end
TEST.awards=TEST.object({gameObject={activeInHierarchy=true},itemCount=5,waiting=true})
function TEST.awards:IsInvoking(name)return self.waiting end
TEST.container=TEST.object({gameObject={activeInHierarchy=true},Children=TEST.list({}),
    poolList=TEST.list({}),poolContainer=TEST.object({}),
    grid=TEST.object({Reposition=function(self)self.painted=true end})})
function TEST.listRemove(self,index)
    for i=index,self.Count-2 do self[i]=self[i+1] end
    self[self.Count-1]=nil; self.Count=self.Count-1; self.Length=self.Count
end
function TEST.container.poolList:Add(child)error('Device reflection cannot convert LotteryLoot to Object')end
TEST.destroyed=0
UnityEngine.Object.Destroy=function(go)go.destroyed=true; TEST.destroyed=TEST.destroyed+1 end
function TEST.reward(kind,value)
    return {OriginType=kind,OriginID=0,OriginValue=value,OriginNum=0,count=value}
end
function TEST.fill(values)
    TEST.awards.dataList=TEST.list(values)
    TEST.awards.dataList.RemoveAt=TEST.listRemove
    local children={}
    for i=1,#values do
        local go=TEST.object({activeInHierarchy=true})
        function go:SetActive(value)self.activeInHierarchy=value end
        children[i]=TEST.object({gameObject=go,transform={SetParent=function(self,parent)self.parent=parent end}})
    end
    TEST.container.Children=TEST.list(children)
    TEST.container.Children.RemoveAt=TEST.listRemove
    TEST.awards.lootContainer=TEST.container
end
UnityEngine.Object.FindObjectOfType=function(kind)
    if kind=='WaterBell.ProjX.View.Panel.TaskPanelController' then return TEST.panel end
    if kind=='WaterBell.ProjX.View.Panel.GetAwardsPanel' then return TEST.awards end
end
'''

class TaskLootTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaState()
        self.lua.execute(MOCK)
        self.lua.execute(REWARD_MOCK)
        self.lua.execute(SCRIPT.read_text(encoding='utf-8'))
    def tearDown(self):
        self.lua.__exit__()
    def test_duplicate_guild_is_removed_without_summing_or_changing_other_rewards(self):
        self.lua.execute('''TEST.fill({TEST.reward('Guild',30),TEST.reward('VC_Green',3),
            TEST.reward('Guild',30),TEST.reward('RoleExp',100)})
            TEST.step(); assert(TEST.awards.dataList.Count==3)
            assert(TEST.awards.dataList[0].count==30 and TEST.awards.dataList[1].count==3)
            assert(TEST.container.Children.Count==3 and TEST.container.grid.painted)
            assert(TEST.awards.itemCount==3 and TEST.rewards==0 and TEST.claims==0)
            assert(TEST.destroyed==1 and TEST.container.poolList.Count==0)
            TEST.step(20); assert(TEST.awards.dataList.Count==3 and TEST.destroyed==1)''')
    def test_single_background_restarts_original_opening_without_old_close_time(self):
        self.lua.execute('''TEST.awards.bgAnim=TEST.object({})
            function TEST.awards.bgAnim:GetCurrentAnimatorStateInfo(layer)
                error('Previous closing state has negative time; do not sample it')
            end
            function TEST.awards.bgAnim:Play(name,layer,time)
                assert(name=='box_4' and layer==0 and time==0); self.opened=true
            end
            TEST.fill({TEST.reward('Guild',30),TEST.reward('VC_Green',3),
                TEST.reward('Guild',30),TEST.reward('Mat',20),TEST.reward('RoleExp',100)})
            TEST.step(); assert(TEST.awards.bgAnim.opened)
            assert(TEST.awards.dataList.Count==4 and TEST.container.Children.Count==4)
            assert(TEST.claims==0 and TEST.rewards==0)''')

    def test_bulk_total_is_preserved_and_non_guild_duplicates_are_not_removed(self):
        self.lua.execute('''TEST.fill({TEST.reward('19',180),TEST.reward('RoleExp',100),
            TEST.reward('19',180),TEST.reward('RoleExp',100)})
            TEST.step(); assert(TEST.awards.dataList.Count==3)
            assert(TEST.awards.dataList[0].count==180)''')
    def test_other_pages_and_different_guild_values_are_untouched(self):
        self.lua.execute('''TEST.fill({TEST.reward('Guild',30),TEST.reward('Guild',30)})
            TEST.panel.gameObject.activeInHierarchy=false; TEST.step()
            assert(TEST.awards.dataList.Count==2)
            TEST.panel.gameObject.activeInHierarchy=true
            TEST.fill({TEST.reward('Guild',30),TEST.reward('Guild',60)}); TEST.step()
            assert(TEST.awards.dataList.Count==2)''')
    def test_incomplete_native_children_are_not_edited(self):
        self.lua.execute('''TEST.fill({TEST.reward('Guild',30),TEST.reward('Guild',30)})
            TEST.container.Children:RemoveAt(1); TEST.step()
            assert(TEST.awards.dataList.Count==2)''')
    def test_created_animation_targets_are_never_removed(self):
        self.lua.execute('''TEST.fill({TEST.reward('Guild',30),TEST.reward('Guild',30)})
            TEST.awards.waiting=false; TEST.step()
            assert(TEST.awards.dataList.Count==2 and TEST.destroyed==0)''')
    def test_bulk_removes_only_input_rows_before_children_and_tweens_exist(self):
        self.lua.execute('''TEST.fill({TEST.reward('Guild',60),TEST.reward('Guild',60),TEST.reward('RoleExp',200)})
            TEST.bulk=TEST.awards; TEST.container.Children=TEST.list({})
            UnityEngine.Object.FindObjectOfType=function(kind)
                if kind=='WaterBell.ProjX.View.Panel.TaskPanelController' then return TEST.panel end
                if kind=='WaterBell.ProjX.View.Panel.GetLootsPanel' then return TEST.bulk end
            end
            TEST.step(); assert(TEST.bulk.dataList.Count==2)
            assert(TEST.container.Children.Count==0 and TEST.destroyed==0)
            assert(TEST.bulk.dataList[0].count==60)''')

    def test_bulk_reopen_recomputes_stale_visibility_without_changing_alpha_or_animation(self):
        self.lua.execute('''TEST.fill({TEST.reward('Mat',20)})
            TEST.bulk=TEST.awards; TEST.container.Children=TEST.list({})
            TEST.bulk.box=TEST.object({alpha=1,finalAlpha=0,invalidated=0})
            function TEST.bulk.box:Invalidate(children)
                assert(children==false); self.invalidated=self.invalidated+1; self.finalAlpha=1
            end
            UnityEngine.Object.FindObjectOfType=function(kind)
                if kind=='WaterBell.ProjX.View.Panel.TaskPanelController' then return TEST.panel end
                if kind=='WaterBell.ProjX.View.Panel.GetLootsPanel' then return TEST.bulk end
            end
            TEST.step(); assert(TEST.bulk.box.invalidated==0)
            TEST.step(2); assert(TEST.bulk.box.invalidated==1 and TEST.bulk.box.alpha==1)
            TEST.step(2); assert(TEST.bulk.box.invalidated==1)
            assert(TEST.awards.dataList.Count==1 and TEST.claims==0 and TEST.rewards==0)''')

    def test_unchanged_single_background_count_keeps_native_animation(self):
        self.lua.execute('''TEST.awards.bgAnim=TEST.object({})
            function TEST.awards.bgAnim:Play() error('Native animation must remain untouched') end
            TEST.fill({TEST.reward('Guild',30),TEST.reward('Mat',20),TEST.reward('RoleExp',100),
                TEST.reward('Coin',3000),TEST.reward('Caph',50),TEST.reward('Guild',30)})
            TEST.step(); assert(TEST.awards.itemCount==5 and TEST.awards.dataList.Count==5)''')

if __name__ == '__main__':
    unittest.main()
