"""Execute released-move repair in Lua 5.1 against the audited native contract."""
import unittest
from pathlib import Path
from test_weapon_selection_cache import LuaState

SCRIPT=Path(__file__).resolve().parents[1]/'lua/init-combat-retarget.lua'
MOCK=r'''
T={now=0,held=false,touch=0,finish=0,release=0,cached=0,logs=0,fields=0,methods=0,start=0,search=0,clear=0}
typeof=function(t)return t end
package.preload['tolua.reflection']=function()end
tolua={loadassembly=function()end}
function T.actor(t)
 function t:Equals(v)return self.destroyed==true or self==v end
 t.transform=t.transform or {position={x=0,z=0}};return t
end
T.sm={logic=3103};T.hero=T.actor({stateMngr=T.sm});T.receiver=T.actor({isSliding=false})
function tolua.getfield(kind,name)
 T.fields=T.fields+1
 return {Get=function(self,obj)
  if name=='instance' then if kind=='HeroEntity' then return T.hero else return T.receiver end end
  return obj[name]
 end}
end
function tolua.gettypemethod(kind,name)
 T.methods=T.methods+1
 return {Call=function(self,obj,arg)
  if name=='GetCurrLogicState' then return obj.logic end
  if name=='IsPaused' then return obj.paused end
  if name=='get_isSkipped' then return obj.skipped end
  if name=='IsInOOC' then return obj.ooc end
  if name=='get_isDead' then return obj.dead end
  if name=='get_cannotChoose' then return obj.cannotChoose end
  if name=='get_isTargetLocked' then return obj.locked end
  if name=='IsAllow2TakeAnyActionNow' then return obj.allow~=false end
  if name=='get_transform' then return obj.transform end
  if name=='get_position' then return obj.position end
  if name=='ClearTarget' then T.clear=T.clear+1;obj.currentTarget=nil;obj.locked=false end
  if name=='SearchAndStartAttack' then
   T.search=T.search+1;obj.currentTarget=T.enemy;obj.locked=true;return T.enemy~=nil
  end
  if name=='AdvExecStartMoveAndAtkUnit' then
   T.start=T.start+1;obj.currentTarget=arg;obj.locked=true
   if T.inRange then obj.stateMngr.logic=3002 end
  end
  if name=='AdvExecTryCachedPreCMD' then
   T.cached=T.cached+1;obj.currentTarget=obj.nextTarget;obj.nextTarget=nil;obj.stateMngr.logic=3002;return true
  end
  if name=='AdvExecFinishMove' then
   T.finish=T.finish+1;obj.nextTarget=nil;obj.stateMngr.logic=5002
  end
  if name=='ReleaseMouse' then
   T.release=T.release+1;obj.isSliding=false
   if T.hero.stateMngr.logic==3103 then T.finish=T.finish+1;T.hero.nextTarget=nil;T.hero.stateMngr.logic=5002 end
  end
 end}
end
UnityEngine={Time={realtimeSinceStartup=0},Input={touchCount=0,GetMouseButton=function()return T.held end},
Debug={Log=function()T.logs=T.logs+1 end,LogWarning=function()end,LogError=error}}
LateUpdateBeat={Add=function(self,fn)T.tick=fn end}
function T.step(now)
 UnityEngine.Time.realtimeSinceStartup=now;UnityEngine.Input.touchCount=T.touch;T.tick()
end
'''

class CombatRetargetTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaState();self.lua.execute(MOCK);self.lua.execute(SCRIPT.read_text(encoding='utf-8'))
    def tearDown(self):self.lua.__exit__()
    def test_queued_target_executes_before_native_finish_would_clear_it(self):
        self.lua.execute('''local target=T.actor({});T.hero.nextTarget=target;T.receiver.isSliding=true
          T.step(0);T.step(.2)
          assert(T.cached==1 and T.hero.currentTarget==target and T.finish==0)
          assert(T.release==1 and T.receiver.isSliding==false and T.sm.logic==3002)''')
    def test_released_manual_move_uses_original_finish_once(self):
        self.lua.execute('''T.step(0);T.step(.2);for i=1,1000 do T.step(.2+i*.05)end
          assert(T.finish==1 and T.cached==0 and T.logs==1)''')
    def test_mouse_and_any_finger_held_prevent_recovery(self):
        self.lua.execute('''T.held=true;T.step(0);T.step(1);assert(T.finish==0)
          T.held=false;T.touch=2;T.step(2);assert(T.finish==0)
          T.touch=0;T.step(2.1);assert(T.finish==0);T.step(2.2);assert(T.finish==1)''')
    def test_cast_stand_and_quest_states_untouched(self):
        self.lua.execute('''T.step(0);for _,s in ipairs({3000,3002,3004,5002,1007,1004,2100})do
          T.sm.logic=s;T.step(s);end;assert(T.finish==0 and T.cached==0)''')
    def test_pause_skip_control_and_dead_untouched(self):
        self.lua.execute('''T.step(0);T.sm.paused=true;T.step(1);T.sm.paused=false
          T.sm.skipped=true;T.step(2);T.sm.skipped=false;T.sm.ooc=true;T.step(3)
          T.sm.ooc=false;T.hero.dead=true;T.step(4);assert(T.finish==0)''')
    def test_dead_destroyed_and_unselectable_targets_not_replayed(self):
        self.lua.execute('''T.step(0);for i,key in ipairs({'dead','destroyed','cannotChoose'})do
          T.hero.nextTarget=T.actor({[key]=true});T.sm.logic=3103;T.step(i)
          end;assert(T.cached==0 and T.finish==3)''')
    def test_scene_exit_discards_owner_and_reflection_handles_are_reused(self):
        self.lua.execute('''T.step(0);local fields,methods=T.fields,T.methods
          T.hero=nil;T.step(1);T.hero=T.actor({stateMngr={logic=3103}});T.step(2)
          assert(T.finish==0);T.step(2.2);assert(T.finish==1)
          assert(T.fields==fields and T.methods==methods)''')
    def test_chase_replaces_dead_target_using_original_death_path(self):
        self.lua.execute('''T.sm.logic=4000;T.hero.currentTarget=T.actor({dead=true});T.enemy=T.actor({})
          T.step(0);T.step(.2);T.step(.5)
          assert(T.clear==1 and T.search==1 and T.hero.currentTarget==T.enemy)''')
    def test_chase_restores_lost_lock_and_reaches_native_attack(self):
        self.lua.execute('''T.sm.logic=4000;local e=T.actor({});T.hero.currentTarget=e;T.inRange=true
          T.step(0);T.step(.2);T.step(.5)
          assert(T.start==1 and T.hero.locked and T.sm.logic==3002 and T.hero.currentTarget==e)''')
    def test_live_chase_moving_toward_target_is_not_restarted(self):
        self.lua.execute('''T.sm.logic=4000;T.hero.currentTarget=T.actor({transform={position={x=10,z=0}}})
          T.hero.locked=true;T.step(0)
          for i=1,20 do T.hero.transform.position.x=i*.2;T.step(i*.3)end
          assert(T.start==0 and T.clear==0 and T.search==0)''')
    def test_stalled_chase_rebinds_once_then_original_attack_runs(self):
        self.lua.execute('''T.sm.logic=4000;T.hero.currentTarget=T.actor({});T.hero.locked=true;T.inRange=true
          T.step(0);for i=1,20 do T.step(i*.3)end
          assert(T.start==1 and T.sm.logic==3002)''')
    def test_held_input_and_native_control_gate_prevent_chase_recovery(self):
        self.lua.execute('''T.sm.logic=4000;T.hero.currentTarget=T.actor({dead=true});T.held=true
          T.step(0);T.step(2);T.held=false;T.sm.allow=false;T.step(3);T.step(5)
          assert(T.clear==0 and T.search==0 and T.start==0)''')
    def test_chase_pending_manual_target_takes_priority_over_search(self):
        self.lua.execute('''T.sm.logic=4000;T.hero.currentTarget=T.actor({dead=true});local e=T.actor({})
          T.hero.nextTarget=e;T.step(0);T.step(.2);T.step(.5)
          assert(T.cached==1 and T.hero.currentTarget==e and T.search==0)''')

if __name__=='__main__':unittest.main()
