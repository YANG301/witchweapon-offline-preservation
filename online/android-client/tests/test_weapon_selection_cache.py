"""Execute the real WWR cache observer through the preserved ToLua runtime.

The application and DLL are read only. Every Unity/ToLua object is an in-memory
test double, and only CacheSave may write the simulated weapon cache.
"""

from __future__ import annotations

import ctypes
import json
from pathlib import Path
import unittest


PROJECT = Path(__file__).resolve().parents[2]
SCRIPT = PROJECT / "android-client/lua/init-weapon-selection-cache.lua"
BEFORE_IDENTITY = Path(__file__).parent / "fixtures/weapon_selection_cache_before_identity.lua"
CATALOG = PROJECT / "legacy-server/resources/offline_responses.json"
TO_LUA = Path(
    r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject"
    r"\Assets\Plugins\x86_64\tolua.dll"
)


class LuaState:
    """Small direct binding to the exported Lua 5.1 C API; no Lua replacement."""

    def __init__(self, dll: Path = TO_LUA) -> None:
        self.dll = ctypes.CDLL(str(dll))
        self.dll.luaL_newstate.argtypes = []
        self.dll.luaL_newstate.restype = ctypes.c_void_p
        self.dll.luaL_openlibs.argtypes = [ctypes.c_void_p]
        self.dll.luaL_openlibs.restype = None
        self.dll.luaL_loadbuffer.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p
        ]
        self.dll.luaL_loadbuffer.restype = ctypes.c_int
        self.dll.lua_pcall.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int
        ]
        self.dll.lua_pcall.restype = ctypes.c_int
        self.dll.lua_tolstring.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_size_t)
        ]
        self.dll.lua_tolstring.restype = ctypes.c_void_p
        self.dll.lua_settop.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.dll.lua_settop.restype = None
        self.dll.lua_close.argtypes = [ctypes.c_void_p]
        self.dll.lua_close.restype = None
        self.state = self.dll.luaL_newstate()
        if not self.state:
            raise MemoryError("luaL_newstate failed")
        self.dll.luaL_openlibs(self.state)

    def __enter__(self) -> "LuaState":
        return self

    def __exit__(self, *unused: object) -> None:
        self.dll.lua_close(self.state)
        self.state = None

    def _string(self, index: int = -1) -> str:
        size = ctypes.c_size_t()
        value = self.dll.lua_tolstring(self.state, index, ctypes.byref(size))
        return ctypes.string_at(value, size.value).decode("utf-8", "replace") if value else ""

    def execute(self, source: str, name: str = "test", returns: int = 0) -> str:
        data = source.encode("utf-8")
        status = self.dll.luaL_loadbuffer(self.state, data, len(data), name.encode("utf-8"))
        if not status:
            status = self.dll.lua_pcall(self.state, 0, returns, 0)
        if status:
            message = self._string()
            self.dll.lua_settop(self.state, 0)
            raise AssertionError(f"{name}: {message}")
        result = self._string() if returns else ""
        self.dll.lua_settop(self.state, 0)
        return result

    def evaluate(self, expression: str) -> str:
        return self.execute(f"return tostring({expression})", "evaluate", returns=1)


def catalog_weapon_sets() -> dict[int, list[int]]:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["_catalog"]
    result: dict[int, list[int]] = {}
    for weapon_id, weapon in catalog["weapons"].items():
        result.setdefault(int(weapon["servant"]), []).append(int(weapon_id))
    return {servant: sorted(weapons) for servant, weapons in result.items()}


NATIVE_MOCK = r"""
TEST = {cache={}, cache_calls=0, native_calls=0, trace={}, selectors={}}
local next_instance = 0
function TEST.object(value)
    next_instance = next_instance + 1
    value.instance_id = next_instance
    function value:GetInstanceID() return self.instance_id end
    function value:Equals(other) return (self.destroyed and other==nil) or self==other end
    return value
end
function TEST.array(values)
    local array = {Length=#values}
    for i,value in ipairs(values) do array[i-1]=value end
    return array
end
function TEST.delegate(value)
    local delegate=TEST.object(value)
    delegate.event_delegate=true
    function delegate:Equals(other)
        if other==nil then return false end
        if type(other)=='table' and other.event_delegate then
            -- Actual EventDelegate.Equals(EventDelegate) ignores cachedCallback.
            -- Raw Lua callbacks have the same null target and null method name.
            return self.target==other.target and self.method_name==other.method_name
        end
        return type(other)=='table' and other.converted_callback~=nil and
            self.cached_callback==other.converted_callback
    end
    return delegate
end
local function equal_item(left,right)
    return left==right or (left~=nil and left.Equals and left:Equals(right))
end
function TEST.list(entries)
    local list={entries=entries or {}}
    function list:Remove(entry)
        for i,value in ipairs(self.entries) do
            if equal_item(value,entry) then table.remove(self.entries,i); return true end
        end
        return false
    end
    function list:Insert(index,entry) table.insert(self.entries,index+1,entry) end
    function list:Add(entry) table.insert(self.entries,entry) end
    function list:RemoveAt(index) table.remove(self.entries,index+1) end
    function list:Contains(entry)
        for _,value in ipairs(self.entries) do if equal_item(value,entry) then return true end end
        return false
    end
    function list:Equals(other) return self==other end
    return setmetatable(list,{__index=function(self,key)
        if key=='Count' then return #self.entries end
        if type(key)=='number' then return self.entries[key+1] end
    end})
end
function TEST.weapon(sid,wid)
    local servant=TEST_WEAPON_CATALOG[sid]
    if not servant then return nil end
    for _,weapon in ipairs(servant) do
        if weapon==wid then
            return {WeaponCardID=wid,ServantCardID=sid,IsUnLock=not TEST.locked[wid]}
        end
    end
    return nil
end
function TEST.cache_save(mode)
    TEST.cache_calls=TEST.cache_calls+1
    table.insert(TEST.trace,'cache')
    for slot=0,mode.selectedSvCardIDArr.Length-1 do
        local sid=mode.selectedSvCardIDArr[slot]
        if sid>0 then TEST.cache[sid]=mode.selectedSvWeaponIDArr[slot] end
    end
end
function TEST.new_mode(servants,owners)
    local mode=TEST.object({selectedSvCardIDArr=TEST.array(servants),
        selectedSvBelongToRoleArr=TEST.array(owners),
        selectedSvWeaponIDArr=TEST.array({0,0})})
    function mode:CacheSave() TEST.cache_save(self) end
    function mode:SelectCards(servants,owners)
        self.selectedSvCardIDArr=TEST.array(servants)
        self.selectedSvBelongToRoleArr=TEST.array(owners)
        self.selectedSvWeaponIDArr=TEST.array({0,0})
        for slot=0,self.selectedSvCardIDArr.Length-1 do
            local sid=self.selectedSvCardIDArr[slot]
            if sid>0 then
                local cached=TEST.cache[sid]
                local weapon=TEST.weapon(sid,cached)
                if weapon and weapon.IsUnLock then self.selectedSvWeaponIDArr[slot]=cached
                else
                    for _,wid in ipairs(TEST_WEAPON_CATALOG[sid] or {}) do
                        if not TEST.locked[wid] then self.selectedSvWeaponIDArr[slot]=wid; break end
                    end
                end
            end
        end
    end
    mode:SelectCards(servants,owners)
    return mode
end
function TEST.native_switch(selector)
    TEST.native_calls=TEST.native_calls+1
    table.insert(TEST.trace,'native')
    if TEST.raise_native then error('native callback failure') end
    local mode=TEST.mode
    local slot=selector.weaponBoxIndex-TEST.controller.currentData.restrictedServants.Count
    if slot<0 or slot>=mode.selectedSvCardIDArr.Length or not selector.unlock then return end
    local weapon=TEST.weapon(mode.selectedSvCardIDArr[slot],selector.wp)
    if not weapon or not weapon.IsUnLock then return end
    mode.selectedSvWeaponIDArr[slot]=selector.wp
    selector.gameObject.activeSelf=false -- original native closes the choice UI
    if TEST.reuse_during_native then selector.wp=TEST.reuse_during_native end
end
function TEST.new_selector(wid,ui_slot)
    local selector=TEST.object({wp=wid,weaponBoxIndex=ui_slot,unlock=true,
        gameObject={activeSelf=true}})
    selector.weaponBtn=TEST.object({onClick=TEST.list()})
    local native=TEST.delegate({kind='native',target=selector,method_name='SwitchWeapon'})
    function native:Execute() TEST.native_switch(selector) end
    selector.native_delegate=native
    table.insert(selector.weaponBtn.onClick.entries,native)
    table.insert(TEST.selectors,selector)
    return selector
end
function TEST.click(selector)
    TEST.trace={}
    local list=selector.weaponBtn.onClick
    local index=0
    while index<list.Count do
        local delegate=list[index]
        if delegate then
            -- Native NGUI Execute(list) logs callback exceptions and continues.
            local ok,message=pcall(delegate.Execute,delegate)
            if not ok then table.insert(TEST.event_errors,tostring(message)) end
            if index>=list.Count then break end
            if list[index]==delegate then
                if delegate.oneShot then list:RemoveAt(index) else index=index+1 end
            end
        else index=index+1 end
    end
end
function TEST.marker(label,callback)
    local delegate=TEST.delegate({kind='original'})
    function delegate:Execute()
        table.insert(TEST.trace,label)
        if callback then callback() end
    end
    return delegate
end
function TEST.continue()
    local mode=TEST.mode
    local servants,owners={},{}
    for slot=0,mode.selectedSvCardIDArr.Length-1 do
        servants[#servants+1]=mode.selectedSvCardIDArr[slot]
        owners[#owners+1]=mode.selectedSvBelongToRoleArr[slot]
    end
    mode:SelectCards(servants,owners) -- unconditional native cache restoration
end
function TEST.reset(sid,first,other_sid,other_first)
    TEST.cache={[sid]=first,[other_sid]=other_first}
    TEST.locked={}
    TEST.cache_calls=0
    TEST.native_calls=0
    TEST.event_errors={}
    TEST.selectors={}
    TEST.trace={}
    TEST.mode=TEST.new_mode({sid,other_sid},{1,1})
    TEST.controller=TEST.object({currentData={currmode=TEST.mode,restrictedServants=TEST.list()}})
    TEST.manager=TEST.object({})
end
"""


REFLECTION_MOCK = r"""
TEST.logs={}
TEST.callback_conversions=0
System={Object={ReferenceEquals=function(left,right) return rawequal(left,right) end}}
local types={
    ['SelectWeaponSingle']='selector',
    ['WaterBell.ProjX.Playmode.PlayModeMngr']='manager',
    ['WaterBell.ProjX.Playmode.BasicPlayMode']='mode',
    ['WaterBell.ProjX.View.Panel.SelectCardsController']='panel',
    ['SelectCardsData']='data',
    ['WaterBell.ProjX.Data.Entity.ObservableServantWeapon']='owned'
}
function typeof(name)
    assert(types[name], 'unknown reflected type '..tostring(name))
    return types[name]
end
tolua={}
package.preload['tolua.reflection']=function() return tolua end
function tolua.loadassembly(name) assert(name=='Assembly-CSharp') end
local fields={
    selector={weaponBtn=true,wp=true,weaponBoxIndex=true,unlock=true},
    panel={current=true,currentData=true},
    data={currmode=true,restrictedServants=true},
    mode={selectedSvCardIDArr=true,selectedSvBelongToRoleArr=true,selectedSvWeaponIDArr=true}
}
function tolua.getfield(kind,name,flags)
    assert(flags==65535 and fields[kind] and fields[kind][name],
        'unknown reflected field '..tostring(kind)..'.'..tostring(name))
    return {Get=function(self,target)
        if kind=='panel' and name=='current' then assert(target==nil); return TEST.controller end
        assert(target~=nil,'instance field received nil target')
        return target[name]
    end}
end
function tolua.gettypemethod(kind,name,flags)
    assert(flags==65535)
    if kind=='manager' and name=='GetExistedInstance' then
        return {Call=function(self,...) assert(select('#',...)==0); return TEST.manager end}
    elseif kind=='manager' and name=='GetCurrPlayMode' then
        return {Call=function(self,target) assert(target==TEST.manager); return TEST.mode end}
    elseif kind=='mode' and name=='CacheSave' then
        return {Call=function(self,target) target:CacheSave() end}
    elseif kind=='data' and name=='GetWeaponData' then
        return {Call=function(self,sid,wid) return TEST.weapon(sid,wid) end}
    end
    error('unknown reflected method '..tostring(kind)..'.'..tostring(name))
end
function tolua.getproperty(kind,name,flags)
    assert(flags==65535 and kind=='owned' and
        (name=='WeaponCardID' or name=='ServantCardID' or name=='IsUnLock'))
    return {Get=function(self,target,indices) assert(indices==nil); return target[name] end}
end
EventDelegate={}
function EventDelegate.Callback(callback)
    assert(type(callback)=='function')
    TEST.callback_conversions=TEST.callback_conversions+1
    return {converted_callback=callback}
end
function EventDelegate.Add(list,callback)
    assert(type(callback)=='table' and type(callback.converted_callback)=='function',
        'native EventDelegate.Add requires an explicitly converted Callback')
    for index=0,list.Count-1 do
        if list[index]:Equals(callback) then return list[index] end
    end
    local delegate=TEST.delegate({kind='observer',cached_callback=callback.converted_callback})
    function delegate:Execute() callback.converted_callback() end
    list:Add(delegate)
    return delegate
end
UnityEngine={Debug={Log=function(value) table.insert(TEST.logs,value) end},Object={}}
function UnityEngine.Object.FindObjectsOfType(kind)
    assert(kind=='selector')
    return TEST.array(TEST.selectors)
end
UpdateBeat={callbacks={}}
function UpdateBeat:Add(callback) table.insert(self.callbacks,callback) end
function TEST.tick()
    for _,callback in ipairs(UpdateBeat.callbacks) do callback() end
end
function TEST.no_errors()
    for _,message in ipairs(TEST.logs) do
        assert(not string.find(message,'FAILED',1,true),message)
    end
end
"""


class WeaponSelectionCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.weapon_sets = catalog_weapon_sets()
        cls.servant = 10010101
        cls.weapons = cls.weapon_sets[cls.servant]
        if len(cls.weapons) != 3:
            raise AssertionError("The preserved servant 10010101 must have three weapons")
        cls.other_servant = 10010001
        cls.other_weapon = cls.weapon_sets[cls.other_servant][0]

    def setUp(self) -> None:
        self.lua = LuaState()
        catalog = ",".join(
            f"[{servant}]={{{','.join(map(str, weapons))}}}"
            for servant, weapons in self.weapon_sets.items()
        )
        self.lua.execute(f"TEST_WEAPON_CATALOG={{{catalog}}}", "real catalog")
        self.lua.execute(NATIVE_MOCK, "native behavioral mock")
        self.lua.execute(
            f"TEST.reset({self.servant},{self.weapons[0]},"
            f"{self.other_servant},{self.other_weapon})",
            "fresh world",
        )
        self.lua.execute(REFLECTION_MOCK, "strict reflection and delegate mock")

    def tearDown(self) -> None:
        self.lua.__exit__()

    def test_native_cache_timing_control(self) -> None:
        """Without observers, native selection is overwritten by old cache."""
        self.lua.execute(f"button=TEST.new_selector({self.weapons[1]},0); TEST.click(button)")
        self.assertEqual(self.lua.evaluate("TEST.mode.selectedSvWeaponIDArr[0]"), str(self.weapons[1]))
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.lua.execute("TEST.continue()")
        self.assertEqual(self.lua.evaluate("TEST.mode.selectedSvWeaponIDArr[0]"), str(self.weapons[0]))

    def load_patch(self, *, remove_extra_bindings: bool = False, script: Path = SCRIPT) -> None:
        source = script.read_text(encoding="utf-8")
        if remove_extra_bindings:
            statement = "if alive(selector) then bind(selector) end"
            self.assertEqual(source.count(statement), 1)
            source = source.replace(statement, "if alive(selector) then end")
        self.lua.execute(source, "real init-weapon-selection-cache.lua")
        self.assertEqual(self.lua.evaluate("__WWRWeaponSelectionCachePersistenceV1"), "true")
        self.lua.execute("TEST.tick(); TEST.no_errors()", "discover real observer")

    def make_button(self, weapon: int, slot: int = 0) -> None:
        self.lua.execute(f"button=TEST.new_selector({weapon},{slot})")

    def check_selected(self, weapon: int) -> None:
        self.assertEqual(self.lua.evaluate("TEST.mode.selectedSvWeaponIDArr[0]"), str(weapon))

    def test_real_script_without_extra_binding_reproduces_overwrite(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch(remove_extra_bindings=True)
        self.lua.execute("TEST.click(button)")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.lua.execute("TEST.continue()")
        self.check_selected(self.weapons[0])

    def test_same_frame_continue_keeps_second_weapon(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("TEST.click(button)")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.assertEqual(self.lua.evaluate("table.concat(TEST.trace,',')"), "native,cache")
        # No UpdateBeat tick is permitted between the native click and Continue.
        self.lua.execute("TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])

    def test_switch_second_first_third_and_back(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        for weapon in (self.weapons[1], self.weapons[0], self.weapons[2], self.weapons[0]):
            self.lua.execute(f"button.wp={weapon}; button.gameObject.activeSelf=true; TEST.click(button)")
            self.check_selected(weapon)
            self.lua.execute("TEST.continue(); TEST.no_errors()")
            self.check_selected(weapon)
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "4")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "4")

    def test_illegal_locked_and_ui_locked_do_not_save(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        invalid = self.weapon_sets[self.other_servant][0]
        self.lua.execute(f"button.wp={invalid}; TEST.click(button); TEST.continue()")
        self.check_selected(self.weapons[0])
        self.lua.execute(f"button.wp={self.weapons[1]}; TEST.locked[button.wp]=true; TEST.click(button)")
        self.check_selected(self.weapons[0])
        self.lua.execute("TEST.locked={}; button.unlock=false; TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[0])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "3")

    def test_native_hides_and_reuses_control_before_post_callback(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute(f"TEST.reuse_during_native={self.weapons[2]}; TEST.click(button)")
        self.assertEqual(self.lua.evaluate("button.wp"), str(self.weapons[2]))
        self.assertEqual(self.lua.evaluate("button.gameObject.activeSelf"), "false")
        self.lua.execute("TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_mode_rebuild_uses_saved_selection_and_can_switch_again(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("TEST.click(button)")
        self.lua.execute(f"TEST.mode=TEST.new_mode({{{self.servant},{self.other_servant}}},{{1,1}}); "
                         "TEST.controller.currentData.currmode=TEST.mode")
        self.check_selected(self.weapons[1])
        self.lua.execute(f"button.wp={self.weapons[2]}; TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[2])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "2")

    def test_duplicate_loading_and_discovery_preserve_native_callback(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.load_patch()
        self.lua.execute("TEST.tick(); TEST.tick(); TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("#UpdateBeat.callbacks"), "1")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick[1]==button.native_delegate"), "true")
        self.assertEqual(self.lua.evaluate("TEST.callback_conversions"), "2")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_original_callback_order_survives_later_insertions(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute("before=TEST.marker('before'); after=TEST.marker('after'); "
                         "button.weaponBtn.onClick:Insert(0,before); button.weaponBtn.onClick:Add(after)")
        self.load_patch()
        self.lua.execute("head=TEST.marker('head'); tail=TEST.marker('tail'); "
                         "button.weaponBtn.onClick:Insert(0,head); button.weaponBtn.onClick:Add(tail); "
                         "TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "7")
        self.lua.execute("local list=button.weaponBtn.onClick; "
                         "assert(list[1]==head and list[2]==before and list[3]==button.native_delegate "
                         "and list[4]==after and list[5]==tail)")
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("table.concat(TEST.trace,',')"), "head,before,native,after,tail,cache")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")

    def test_rebound_list_and_button_detach_old_observers(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("oldList=button.weaponBtn.onClick; "
                         "button.weaponBtn.onClick=TEST.list({button.native_delegate}); TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("oldList.Count"), "1")
        self.assertEqual(self.lua.evaluate("oldList[0]==button.native_delegate"), "true")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.lua.execute("secondList=button.weaponBtn.onClick; "
                         "button.weaponBtn=TEST.object({onClick=TEST.list({button.native_delegate})}); "
                         "TEST.tick(); TEST.no_errors(); TEST.click(button); TEST.continue()")
        self.assertEqual(self.lua.evaluate("secondList.Count"), "1")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_destroyed_selector_detaches_and_new_control_works(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("oldButton=button; button.destroyed=true; TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("oldButton.weaponBtn.onClick.Count"), "1")
        self.make_button(self.weapons[2])
        self.lua.execute("TEST.tick(); TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[2])

    def test_restricted_party_slot_offset_matches_native(self) -> None:
        self.lua.execute("TEST.controller.currentData.restrictedServants=TEST.list({{}})")
        self.make_button(self.weapons[1], slot=1)
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.lua.execute(f"button.weaponBoxIndex=0; button.wp={self.weapons[2]}; "
                         "TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_native_later_callback_rejects_transition_without_overwriting_it(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute(f"button.weaponBtn.onClick:Add(TEST.marker('reject',function() "
                         f"TEST.mode.selectedSvWeaponIDArr[0]={self.weapons[0]} end))")
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.no_errors()")
        self.check_selected(self.weapons[0])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")

    def test_mode_changed_inside_native_callback_is_not_saved(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute("oldMode=TEST.mode; button.weaponBtn.onClick:Add(TEST.marker('rebuild',function() "
                         f"TEST.mode=TEST.new_mode({{{self.servant},{self.other_servant}}},{{1,1}}); "
                         "TEST.controller.currentData.currmode=TEST.mode end))")
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.no_errors()")
        self.check_selected(self.weapons[0])
        self.assertEqual(self.lua.evaluate("oldMode.selectedSvWeaponIDArr[0]"), str(self.weapons[1]))
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")

    def test_owner_changed_inside_native_callback_is_not_saved(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute("button.weaponBtn.onClick:Add(TEST.marker('owner',function() "
                         "TEST.mode.selectedSvBelongToRoleArr[0]=2 end))")
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.assertEqual(self.lua.evaluate(f"TEST.cache[{self.servant}]"), str(self.weapons[0]))

    def test_unchanged_selection_does_not_save(self) -> None:
        self.make_button(self.weapons[0])
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.tick(); TEST.no_errors()")
        self.check_selected(self.weapons[0])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")

    def test_original_callback_failure_is_logged_and_does_not_save(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("TEST.raise_native=true; TEST.click(button)")
        self.assertEqual(self.lua.evaluate("#TEST.event_errors"), "1")
        self.assertIn("native callback failure", self.lua.evaluate("TEST.event_errors[1]"))
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.lua.execute("TEST.raise_native=false; TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_live_list_one_shot_removal_does_not_skip_post_observer(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute("before=TEST.marker('one-before'); before.oneShot=true; "
                         "after=TEST.marker('one-after'); after.oneShot=true; "
                         "button.weaponBtn.onClick:Insert(0,before); button.weaponBtn.onClick:Add(after)")
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.assertEqual(self.lua.evaluate("table.concat(TEST.trace,',')"), "one-before,native,one-after,cache")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_live_list_executes_callback_added_during_dispatch(self) -> None:
        self.make_button(self.weapons[1])
        self.lua.execute("late=TEST.marker('late'); "
                         "appender=TEST.marker('appender',function() "
                         "if not TEST.appended_once then "
                         "button.weaponBtn.onClick:Add(late); TEST.appended_once=true end end); "
                         "button.weaponBtn.onClick:Add(appender)")
        self.load_patch()
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("table.concat(TEST.trace,',')"), "native,appender,cache,late")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.lua.execute("TEST.tick(); TEST.click(button); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("table.concat(TEST.trace,',')"), "native,appender,late")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "2")
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")

    def test_old_script_value_equality_reproduces_missing_observer_failure(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch(script=BEFORE_IDENTITY)
        self.lua.execute("local list=button.weaponBtn.onClick; "
                         "assert(list[0]~=list[2] and list[0]:Equals(list[2])); "
                         "list:RemoveAt(0); TEST.tick(); TEST.click(button)")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.lua.execute("TEST.continue()")
        self.check_selected(self.weapons[0])

    def test_independently_removed_pre_observer_is_rebound_by_identity(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("local list=button.weaponBtn.onClick; "
                         "assert(list[0]~=list[2] and list[0]:Equals(list[2])); "
                         "list:RemoveAt(0); TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")

    def test_independently_removed_post_observer_is_rebound_by_identity(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.lua.execute("button.weaponBtn.onClick:RemoveAt(2); TEST.tick(); TEST.no_errors()")
        self.assertEqual(self.lua.evaluate("button.weaponBtn.onClick.Count"), "3")
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[1])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")

    def add_late_rejection(self) -> None:
        self.lua.execute(f"tail=TEST.marker('late-reject',function() "
                         f"TEST.mode.selectedSvWeaponIDArr[0]={self.weapons[0]} end); "
                         "button.weaponBtn.onClick:Add(tail); TEST.tick(); TEST.no_errors()")

    def test_old_value_equality_caches_before_dynamically_appended_native_callback(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch(script=BEFORE_IDENTITY)
        self.add_late_rejection()
        self.lua.execute("TEST.click(button)")
        self.check_selected(self.weapons[0])
        # Equals mistakes the added raw callback for the post observer, leaving
        # the old observer before it and incorrectly persisting the rejected ID.
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "1")
        self.assertEqual(self.lua.evaluate(f"TEST.cache[{self.servant}]"), str(self.weapons[1]))
        self.lua.execute("TEST.continue()")
        self.check_selected(self.weapons[1])

    def test_identity_reorders_post_after_dynamically_appended_native_callback(self) -> None:
        self.make_button(self.weapons[1])
        self.load_patch()
        self.add_late_rejection()
        self.lua.execute("TEST.click(button); TEST.continue(); TEST.no_errors()")
        self.check_selected(self.weapons[0])
        self.assertEqual(self.lua.evaluate("TEST.cache_calls"), "0")
        self.assertEqual(self.lua.evaluate(f"TEST.cache[{self.servant}]"), str(self.weapons[0]))
        self.assertEqual(self.lua.evaluate("TEST.native_calls"), "1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
