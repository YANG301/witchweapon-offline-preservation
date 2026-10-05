"""Run the actual furnace-only Lua using the original native Lua 5.1 DLL.

UI and network mocks follow the verified ARM64 callbacks. This does not run a
game client or contact any service, and writes no player files.
"""
from pathlib import Path
import unittest
from test_weapon_selection_cache import LuaState

SCRIPT = Path(__file__).resolve().parents[1] / "lua/init-furnace-reward-choice.lua"

MOCK = r"""
TEST = {requests={}, inventoryRequests={}, confirmations=0, errors=0, guids=0, animations=0, finalSelections=0, finalCompletions=0}
function TEST.object(value)
    function value:Equals(other) return self == other end
    return value
end
function TEST.list(values)
    local list = {Count=#values}
    for index, value in ipairs(values) do list[index-1] = value end
    return list
end
function TEST.reset()
    TEST.items, TEST.serverItems, TEST.serverRequests = {}, {}, {}
    TEST.wallet = {diamonds=100}
    function TEST.wallet:ConsumeDiamond(price) self.diamonds=self.diamonds-price end
    TEST.mode = {ChooseMateriaTime=1, result={currentRandomLootID=0}}
    TEST.button = TEST.object({gameObject={activeInHierarchy=true},onClick=function() TEST.originalClicks=(TEST.originalClicks or 0)+1 end})
    TEST.listener = TEST.object({onClick=function() TEST.originalListenerClicks=(TEST.originalListenerClicks or 0)+1 end})
    TEST.originalClick, TEST.originalListener=TEST.button.onClick, TEST.listener.onClick
    local children = {}
    for index=1,5 do
        local child = TEST.object({Data={id=40330038+index,index=index-1,isBuy=index==1}})
        child.transform = TEST.object({row=child})
        children[#children+1]=child
    end
    TEST.panel = TEST.object({gameObject={activeInHierarchy=true},chooseButton=TEST.button,
        rawList=TEST.list({40330039,40330040,40330041,40330042,40330043}),
        buyStateList=TEST.list({true,false,false,false,false}),mode=TEST.mode,
        itemContainer=TEST.object({Children=TEST.list(children)}),isSelectRunning=false})
end
TEST.reset()
function TEST.obtain(panel,wanted)
    for index=0,panel.rawList.Count-1 do
        if panel.rawList[index]==wanted then
            assert(not panel.buyStateList[index], 'Native selection has no unclaimed target')
            panel.buyStateList[index]=true
            panel.itemContainer.Children[index].Data.isBuy=true
            return
        end
    end
    error('Reward target absent from native rows')
end
function TEST.commit(request,index)
    local id=TEST.panel.rawList[index]
    if not TEST.serverRequests[request.argumentDic.idempotency] then
        TEST.serverRequests[request.argumentDic.idempotency]=true
        TEST.serverItems[id]=(TEST.serverItems[id] or 0)+1
    end
    -- Original ChooseMaterials parser increments again on a duplicate reply.
    TEST.items[id]=(TEST.items[id] or 0)+1
    TEST.mode.result.currentRandomLootID=TEST.panel.rawList[index]
    request.OnSuccessfulDelegate()
end
function TEST.sync(index)
    local request=TEST.inventoryRequests[index]
    assert(request and not request.argumentDic.idempotency and not request.argumentDic.choicePool)
    TEST.items={}
    for id,count in pairs(request.snapshot) do TEST.items[id]=count end
    request.OnSuccessfulDelegate()
end
package.preload['tolua.reflection']=function() return {} end
local knownTypes={}
for _,name in ipairs({'WaterBell.ProjX.View.Panel.SettlementBuyItemPanel',
    'WaterBell.ProjX.Playmode.WeaponDailyMode','WaterBell.ProjX.Playmode.BasicPlayMode',
    'WaterBell.ProjX.View.Panel.UIPanelBase','WaterBell.ProjX.View.Panel.UIPanelSingleContainer',
    'WaterBell.ProjX.View.Panel.SBIP_ItemData','WaterBell.ProjX.View.Panel.UIDataBase',
    'WaterBell.ProjX.Data.NetIO.ChooseMaterials','WaterBell.ProjX.Data.NetIO.BackpackGetAllItemsLogic',
    'WaterBell.ProjX.Data.NetIO.NetMsgBase','WaterBell.ProjX.Data.NetIO.ProtocolManager',
    'BattleResult','UnityEngine.Transform','System.Guid'}) do knownTypes[name]=true end
function typeof(kind)
    if TEST.missingType==kind then return nil end
    return knownTypes[kind] and kind or nil
end
tolua={loadassembly=function() end,findtype=typeof}
function tolua.getfield(kind,name)
    assert(kind and knownTypes[kind], 'Unknown field owner type')
    if kind=='WaterBell.ProjX.View.Panel.UIDataBase' then assert(name=='id') end
    if TEST.missingField==name then return nil end
    return {Get=function(_,target) return target[name] end,Set=function(_,target,value) target[name]=value end}
end
function tolua.getproperty(kind,name)
    assert(kind and knownTypes[kind], 'Unknown property owner type')
    if TEST.missingProperty==name then return nil end
    return {Get=function(_,target) return target[name] end,Set=function(_,target,value) target[name]=value end}
end
function tolua.gettypemethod(kind,name,flags,binder,types)
    assert(kind and knownTypes[kind], 'Unknown method owner type')
    if TEST.missingMethod==name then return nil end
    if name=='NewGuid' then assert(kind=='System.Guid' and types==nil) end
    if name=='<GetChooseResult>m__3' or name=='<GetChooseResult>m__4' then
        assert(types and types[1]=='UnityEngine.Transform')
    end
    if name=='SendNormalMassage' then assert(types and types[1]=='WaterBell.ProjX.Data.NetIO.NetMsgBase') end
    return {Call=function(_,target,arg)
        if name=='NewGuid' then TEST.guids=TEST.guids+1; return '00000000-0000-0000-0000-'..string.format('%012d',TEST.guids) end
        if name=='GetInstance' then return TEST end
        if name=='SendNormalMassage' then
            if arg.kind=='WaterBell.ProjX.Data.NetIO.BackpackGetAllItemsLogic' then
                arg.snapshot={}
                for id,count in pairs(TEST.serverItems) do arg.snapshot[id]=count end
                TEST.inventoryRequests[#TEST.inventoryRequests+1]=arg
            else
                TEST.requests[#TEST.requests+1]=arg
            end
            return
        end
        if name=='GetBattleResult' then return target.result end
        if name=='IsEnoughDiamondGetWeaponMaterail' then return TEST.wallet.diamonds<({5,10,10,15})[target.ChooseMateriaTime] and 1 or 0 end
        if name=='GetCurrentWeaponMaterailNeedDiamond' then return ({5,10,10,15})[target.ChooseMateriaTime] end
        if name=='<OnBuyButtonClick>m__5' then
            TEST.animations=TEST.animations+1
            target.currentRandomLootID=target.mode.result.currentRandomLootID
            TEST.obtain(target,target.currentRandomLootID)
            target.isSelectRunning=false
            return
        end
        if name=='<GetChooseResult>m__3' then
            assert(arg.row.Data.id==target.currentRandomLootID)
            TEST.finalSelections=TEST.finalSelections+1; return
        end
        if name=='<GetChooseResult>m__4' then
            TEST.finalCompletions=TEST.finalCompletions+1
            TEST.obtain(target,target.currentRandomLootID)
            target.isSelectRunning=false; return
        end
        error('Unknown native method: '..name)
    end}
end
function tolua.createinstance(kind) return {kind=kind,argumentDic={}} end
System={Type={DefaultBinder={}},Object={ReferenceEquals=function(a,b) return a==b end}}
UnityEngine={Time={realtimeSinceStartup=0},Object={FindObjectOfType=function()
    TEST.scans=(TEST.scans or 0)+1; return TEST.panel
end},Debug={LogError=function(text) TEST.errors=TEST.errors+1; TEST.lastError=text end,
    LogWarning=function(text) TEST.ready=text end}}
UIEventListener={Get=function() return TEST.listener end}
NetworkAlertUI={TryShowWarningTipBox=function(text) TEST.warning=text end}
UserInfo={GetInstance=function() return {GetPlayer=function() return TEST.wallet end} end}
WaterBell={ProjX={View={Panel={ConfirmPanel={GetInstance=function()
    return {OpenPanel=function(_,title,description,yes,no)
        TEST.confirmations=TEST.confirmations+1; TEST.yes=yes; TEST.description=description
    end}
end}}}}}
UpdateBeat={Add=function(_,callback)
    TEST.frame=callback
    TEST.tick=function()
        UnityEngine.Time.realtimeSinceStartup=UnityEngine.Time.realtimeSinceStartup+0.11
        callback()
    end
end}
function TEST.click() TEST.listener.onClick() end
"""


class FurnaceChoiceTests(unittest.TestCase):
    def run_lua(self, code: str) -> None:
        with LuaState() as lua:
            lua.execute(MOCK, "furnace_native_contract")
            lua.execute(SCRIPT.read_text(encoding="utf-8"), "furnace_choice_patch")
            lua.execute("TEST.tick(); assert(TEST.errors==0 and TEST.ready=='ONLINE_FURNACE_REWARD_CHOICE_READY 155')", "setup")
            lua.execute(code, "scenario")

    def test_boot_lookup_diagnostics_and_recovery(self):
        cases = [
            ("missingType", "WaterBell.ProjX.View.Panel.UIDataBase", "dataType"),
            ("missingField", "argumentDic", "args"),
            ("missingProperty", "ChooseMateriaTime", "times"),
            ("missingMethod", "SendNormalMassage", "send"),
        ]
        for option, target, key in cases:
            with self.subTest(target=target), LuaState() as lua:
                lua.execute(MOCK, "furnace_native_contract")
                lua.execute(f"TEST.{option}='{target}'; TEST.panel=nil", "missing_target")
                lua.execute(SCRIPT.read_text(encoding="utf-8"), "furnace_choice_patch")
                lua.execute(f"""
                    TEST.tick(); assert(TEST.errors==1 and TEST.ready==nil)
                    assert(string.find(TEST.lastError,'phase=setup.{key}',1,true))
                    assert(string.find(TEST.lastError,'missing {key}',1,true))
                    assert(string.find(TEST.lastError,'{target}',1,true))
                    TEST.tick(); assert(TEST.errors==1)
                    TEST.{option}=nil
                    UnityEngine.Time.realtimeSinceStartup=UnityEngine.Time.realtimeSinceStartup+5
                    TEST.tick(); assert(TEST.ready=='ONLINE_FURNACE_REWARD_CHOICE_READY 155')
                    assert(#TEST.requests==0 and #TEST.inventoryRequests==0)
                """, "precise_boot_diagnostic")

    def test_all_four_paid_picks_finish_final_slot(self):
        self.run_lua(r"""
        local identities={}
        for index=1,4 do
            TEST.click(); assert(TEST.requests[index]==nil)
            TEST.yes(); local request=TEST.requests[index]
            assert(request and request.argumentDic.choicePool=='40330039,40330040,40330041,40330042,40330043')
            assert(not identities[request.argumentDic.idempotency]); identities[request.argumentDic.idempotency]=true
            assert(TEST.panel.isSelectRunning)
            TEST.click(); assert(#TEST.requests==index)
            TEST.commit(request,index)
            assert(not TEST.panel.isSelectRunning)
            request.OnSuccessfulDelegate(); assert(TEST.mode.ChooseMateriaTime==index+1)
        end
        assert(TEST.wallet.diamonds==60 and TEST.mode.ChooseMateriaTime==5)
        assert(TEST.animations==3 and TEST.finalSelections==1 and TEST.finalCompletions==1)
        TEST.click(); assert(#TEST.requests==4 and TEST.confirmations==4)
        assert(TEST.errors==0)
        TEST.panel.gameObject.activeInHierarchy=false; TEST.tick()
        assert(TEST.button.onClick==TEST.originalClick and TEST.listener.onClick==TEST.originalListener)
        """)

    def test_failed_request_reuses_identity_without_local_charge(self):
        self.run_lua(r"""
        TEST.click(); TEST.yes(); local first=TEST.requests[1]
        first.OnTimeOutDelegate('timeout')
        assert(not TEST.panel.isSelectRunning and TEST.wallet.diamonds==100 and TEST.mode.ChooseMateriaTime==1)
        TEST.click(); TEST.yes(); local retry=TEST.requests[2]
        assert(first.argumentDic.idempotency==retry.argumentDic.idempotency)
        TEST.commit(retry,1)
        assert(TEST.wallet.diamonds==95 and TEST.mode.ChooseMateriaTime==2)
        first.OnSuccessfulDelegate(); assert(TEST.wallet.diamonds==95)
        TEST.sync(1); TEST.tick(); TEST.sync(2)
        assert(TEST.items[TEST.panel.rawList[1]]==1)
        assert(TEST.errors==0)
        """)

    def test_cancel_stale_confirmation_and_poor_wallet(self):
        self.run_lua(r"""
        TEST.click(); assert(#TEST.requests==0 and TEST.wallet.diamonds==100)
        TEST.panel.buyStateList[1]=true; TEST.yes(); assert(#TEST.requests==0)
        TEST.panel.buyStateList[1]=false
        TEST.wallet.diamonds=4; TEST.click(); assert(TEST.warning=='钻石不足' and #TEST.requests==0)
        assert(TEST.mode.ChooseMateriaTime==1 and TEST.errors==0)
        """)

    def test_late_success_after_timeout_finishes_shared_transaction_once(self):
        self.run_lua(r"""
        TEST.click(); TEST.yes(); local first=TEST.requests[1]
        first.OnTimeOutDelegate('timeout')
        TEST.click(); TEST.yes(); local retry=TEST.requests[2]
        first.OnFailedDelegate('late failure')
        assert(TEST.panel.isSelectRunning)
        TEST.commit(first,1)
        assert(TEST.wallet.diamonds==95 and TEST.mode.ChooseMateriaTime==2 and not TEST.panel.isSelectRunning)
        TEST.commit(retry,1)
        assert(TEST.wallet.diamonds==95 and TEST.mode.ChooseMateriaTime==2 and TEST.animations==1)
        local item=TEST.panel.rawList[1]
        assert(TEST.items[item]==2 and #TEST.inventoryRequests==1)
        TEST.sync(1); TEST.tick(); assert(#TEST.inventoryRequests==2)
        TEST.sync(2); assert(TEST.items[item]==1 and TEST.serverItems[item]==1)
        -- Another replay after the first transaction is already complete still
        -- schedules a full refresh, while the wallet/UI remain unchanged.
        TEST.commit(retry,1); assert(TEST.items[item]==2)
        TEST.tick(); TEST.sync(3)
        assert(TEST.items[item]==1 and TEST.wallet.diamonds==95 and TEST.animations==1)
        TEST.commit(retry,1); TEST.tick()
        TEST.inventoryRequests[4].OnTimeOutDelegate('inventory timeout')
        TEST.tick(); assert(#TEST.inventoryRequests==4)
        UnityEngine.Time.realtimeSinceStartup=UnityEngine.Time.realtimeSinceStartup+5
        TEST.tick(); TEST.sync(5); assert(TEST.items[item]==1)
        TEST.sync(4); TEST.tick(); TEST.sync(6)
        assert(TEST.items[item]==1 and TEST.wallet.diamonds==95 and TEST.animations==1)
        assert(TEST.errors==0)
        """)

    def test_native_rebind_and_hidden_confirmation(self):
        self.run_lua(r"""
        local scans=TEST.scans; TEST.frame(); assert(TEST.scans==scans)
        local rebound=function() end
        TEST.button.onClick=rebound; TEST.tick(); assert(TEST.button.onClick==nil)
        TEST.click(); TEST.panel.gameObject.activeInHierarchy=false; TEST.yes()
        assert(#TEST.requests==0 and TEST.wallet.diamonds==100)
        TEST.tick(); assert(TEST.button.onClick==rebound)
        assert(TEST.errors==0)
        local failures=0
        UnityEngine.Object.FindObjectOfType=function() failures=failures+1; error('mock scan failure') end
        TEST.tick(); TEST.tick(); assert(failures==1 and TEST.errors==1)
        UnityEngine.Time.realtimeSinceStartup=UnityEngine.Time.realtimeSinceStartup+5
        TEST.tick(); assert(failures==2 and TEST.errors==1)
        """)


if __name__ == "__main__":
    unittest.main()
