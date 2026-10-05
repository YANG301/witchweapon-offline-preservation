package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Tests the preserved twelve-wave fixtures and account-local CSC reset rules. */
public final class BarrierLabyrinthSelfTest {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static JSONObject read(String path)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(Paths.get(path)),StandardCharsets.UTF_8));
    }
    private static void rejected(RunnableWithError action,String message)throws Exception{
        try{action.run();throw new AssertionError(message);}catch(IOException expected){}
    }
    private interface RunnableWithError {void run()throws Exception;}
    private static void sameField(ProtoWire.Field before,ProtoWire.Field after,String where){
        check(before.number==after.number && before.type==after.type,where+" changed wire structure");
        if(before.type==0)check(before.value==after.value,where+" changed value");
        else check(Arrays.equals(before.data,after.data),where+" changed data");
    }
    private static void checkMobBalance(String original,String revised,int round)throws Exception{
        ProtoWire source=ProtoWire.parse(Base64.decode(original,Base64.DEFAULT));
        ProtoWire result=ProtoWire.parse(Base64.decode(revised,Base64.DEFAULT));
        check(source.fields.size()==result.fields.size(),"Maze basket field count changed at "+round);
        int mobs=0;
        for(int index=0;index<source.fields.size();index++){
            ProtoWire.Field before=source.fields.get(index),after=result.fields.get(index);
            check(before.number==after.number && before.type==after.type,
                "Maze basket field structure changed at "+round);
            if(before.number!=5){sameField(before,after,"Non-mob basket field at "+round);continue;}
            ProtoWire oldMob=ProtoWire.parse(before.data),newMob=ProtoWire.parse(after.data);
            long id=oldMob.number(6,0);
            long localBuff=id==331080240701L?90300071L:0;
            List<ProtoWire.Field> kept=new ArrayList<ProtoWire.Field>();
            for(ProtoWire.Field old:oldMob.fields)if(old.number!=1 || localBuff==0)kept.add(old);
            if(localBuff!=0)
                check(oldMob.integers(1).size()==1 && oldMob.integers(1).get(0)==localBuff &&
                    newMob.integers(1).isEmpty(),"Synthetic maze non-critical damage gate remained");
            check(kept.size()==newMob.fields.size(),"Maze MobInfo field count changed at "+round);
            int[] stats=new int[3];
            for(int fieldIndex=0;fieldIndex<kept.size();fieldIndex++){
                ProtoWire.Field old=kept.get(fieldIndex),now=newMob.fields.get(fieldIndex);
                check(old.number==now.number && old.type==now.type,
                    "Maze MobInfo wire structure changed at "+round);
                int divisor=old.number==30?4:(old.number==31 || old.number==32)?5:0;
                if(divisor==0){sameField(old,now,"Maze MobInfo non-combat field at "+round);continue;}
                stats[old.number-30]++;
                check(old.type==0 && old.value>1 &&
                    now.value==(old.value+divisor-1)/divisor && now.value<old.value,
                    "Maze HP/attack reduction missing at "+round);
            }
            check(oldMob.number(6,0)>0 && Arrays.equals(stats,new int[]{1,1,1}),
                "Maze MobInfo lacks a complete stat triple at "+round);
            if(round==1 && oldMob.number(6,0)==331080240701L)
                check(newMob.number(30,0)==4000 && newMob.number(31,0)==13 &&
                    newMob.number(32,0)==13,"First maze boss stayed too strong");
            mobs++;
        }
        check(mobs>=5,"Maze round has too few preserved enemy definitions: "+round);
    }

    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: responses.json stage_catalog.json");
        JSONObject responses=read(args[0]);
        new StageCatalog(read(args[1])).install(responses);
        String mainline=responses.getJSONObject("/combat/mob/json#3110001003").getString("body");
        String mainlineMob=responses.getJSONObject("/combat/mob/info#3110001003").getString("base64");
        List<String> sourceMobs=new ArrayList<String>();
        for(int round=1;round<=12;round++)sourceMobs.add(responses.getJSONObject(
            "/combat/mob/info#3130001026@"+round).getString("base64"));
        BarrierLabyrinth.install(responses);
        check(mainline.equals(responses.getJSONObject("/combat/mob/json#3110001003").getString("body")),
            "True mainline 1-3 was overwritten");
        check(mainlineMob.equals(responses.getJSONObject("/combat/mob/info#3110001003")
            .getString("base64")),"True mainline 1-3 enemy stats were overwritten");

        JSONObject state=new JSONObject();
        byte[] role=Base64.decode(responses.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        long now=1_780_000_000L;
        ProtoWire info=ProtoWire.parse(BarrierLabyrinth.info(state,role,now));
        List<Long> ids=info.integers(3),levels=info.integers(4);
        check(ids.size()==16 && new HashSet<Long>(ids).size()==13 && levels.size()==16 &&
              info.number(17,0)>0 && info.number(24,0)==1 && info.number(25,-1)==1 &&
              info.number(22,0)==5 && info.number(27,0)==1,
              "Level-one maze entrance, enemy level, or sixteen-node map is wrong");
        for(int reward=1;reward<=4;reward++)
            check(ids.get(reward*4-1)==0 && levels.get(reward*4-1)==0,
                "Missing zero-ID reward node after maze fight "+reward*3);
        check(state.length()==0,"Read-only maze info changed the account save");
        JSONObject unclaimed=new JSONObject().put("mazeRound",4).put("mazePendingBonus",3);
        check(ProtoWire.parse(BarrierLabyrinth.info(unclaimed,role,now)).number(24,0)==4 &&
            BarrierLabyrinth.pendingBonus(unclaimed)==3,
            "Third-floor win skipped the original reward node");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.requireRoleStage(unclaimed,new LinkedHashMap<String,String>());
        }},"The next maze battle started before the reward node was claimed");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.reset(unclaimed,now);
        }},"Maze reset discarded an unclaimed checkpoint");
        JSONObject oldClaimed=new JSONObject().put("mazeRound",4).put("mazeSupplyBoxes",1);
        check(BarrierLabyrinth.pendingBonus(oldClaimed)==0 &&
            ProtoWire.parse(BarrierLabyrinth.info(oldClaimed,role,now)).number(24,0)==5,
            "An old save with an automatically awarded box was rolled back");
        JSONObject groupState=new JSONObject().put("ownedServants",new JSONObject()
            .put("10010001","owned").put("10010101","owned"));
        Map<String,String> groupForm=new LinkedHashMap<String,String>();
        groupForm.put("svcardids","10010001|10010101");
        groupForm.put("mercenaryownerids","");
        BarrierLabyrinth.Group group=BarrierLabyrinth.group(groupState,groupForm,role,now);
        ProtoWire selected=ProtoWire.parse(group.response);
        check(selected.integers(1).size()==2 && selected.integers(2).size()==2 &&
              selected.integers(2).get(0)==1000 && selected.integers(7).size()==2 &&
              selected.number(22,0)==5 &&
              group.state.getJSONArray("mazeParty").getLong(0)==10010001L &&
              !groupState.has("mazeParty"),"CSC group response did not persist the selected party");
        groupForm.put("svcardids","10010001|10010001");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.group(groupState,groupForm,role,now);
        }},"Duplicate party member was accepted");
        groupForm.put("svcardids","10010001|10010201");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.group(groupState,groupForm,role,now);
        }},"Unowned party member was accepted");
        Set<String> bodies=new HashSet<String>();
        for(int round=1;round<=12;round++){
            final int serial=round;
            long stage=BarrierLabyrinth.stageForRound(round);
            int slot=round-1+(round-1)/3;
            check(ids.get(slot)==stage && levels.get(slot)==5 && BarrierLabyrinth.supports(stage),
                "Stage list and combat round differ at "+round);
            JSONObject battle=new JSONObject(responses.getJSONObject(
                BarrierLabyrinth.fixtureKey("/combat/mob/json",round)).getString("body"));
            check(Long.toString(stage).equals(battle.getJSONObject("EnemyLayer").getString("levelID")) &&
                  battle.getJSONObject("EnemyLayer").getJSONArray("areas").length()>0,
                "Combat JSON uses an incorrect stage ID");
            bodies.add(battle.toString());
            JSONObject mob=responses.getJSONObject(BarrierLabyrinth.fixtureKey("/combat/mob/info",round));
            check(sourceMobs.get(round-1).equals(responses.getJSONObject(
                "/combat/mob/info#3130001026@"+round).getString("base64")),
                "The preserved source enemy roster changed");
            checkMobBalance(sourceMobs.get(round-1),mob.getString("base64"),round);
            JSONObject cursor=new JSONObject().put("mazeRound",round);
            BarrierLabyrinth.requireCurrentStage(cursor,Long.toString(stage));
            Map<String,String> roleForm=new LinkedHashMap<String,String>();
            roleForm.put("instid",Long.toString(stage));
            BarrierLabyrinth.requireRoleStage(cursor,roleForm);
            roleForm.put("instid","3130001999");
            rejected(new RunnableWithError(){public void run()throws Exception{
                BarrierLabyrinth.requireRoleStage(new JSONObject().put("mazeRound",serial),roleForm);
            }},"Wrong CSC combat role stage was accepted");
            rejected(new RunnableWithError(){public void run()throws Exception{
                BarrierLabyrinth.requireCurrentStage(new JSONObject().put("mazeRound",serial),"3130001999");
            }},"An unrelated maze settlement ID was accepted");
        }
        check(bodies.size()==12,"The twelve maze rounds collapsed to one fixture");
        check(!BarrierLabyrinth.supports(3110001003L),"Mainline 1-3 was mistaken for the maze");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.fixtureKey("/combat/mob/json",13);
        }},"Completed run still has a battle fixture");

        JSONObject midRun=new JSONObject().put("mazeRound",7).put("mazeRuns",2)
            .put("mazeWins",17).put("mazeAttempts",21).put("mazeHP",0.4)
            .put("mazeEnergy_101",44).put("mazeSupplyBoxes",5);
        JSONObject reset=BarrierLabyrinth.reset(midRun,now);
        check(reset.getInt("mazeRound")==1 && reset.getInt("mazeRuns")==3 &&
              reset.getInt("mazeWins")==17 && reset.getInt("mazeAttempts")==21 &&
              reset.getInt("mazeSupplyBoxes")==5 && reset.getInt("mazeBestCleared")==6 &&
              !reset.has("mazeEnergy_101") && reset.getDouble("mazeHP")==1 &&
              BarrierLabyrinth.resetsRemaining(reset,now)==0 && midRun.getInt("mazeRound")==7,
              "Reset lost historical records, retained battle energy, or changed the input");
        check(ProtoWire.parse(BarrierLabyrinth.info(reset,role,now)).number(25,-1)==0,
            "Spent daily reset remained visible");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.reset(reset,now);
        }},"Second reset in one day succeeded");
        check(BarrierLabyrinth.resetsRemaining(reset,now+86400)==1,
            "The next local day did not restore one reset");
        JSONObject tomorrow=BarrierLabyrinth.reset(reset,now+86400);
        check(tomorrow.getInt("mazeRuns")==4 && BarrierLabyrinth.resetsRemaining(tomorrow,now)==0,
            "Clock rollback refilled a spent daily reset");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.reset(new JSONObject().put("active",true),now);
        }},"A live battle was discarded by reset");

        JSONObject victorious=new JSONObject().put("mazeRound",13).put("mazeWins",12);
        BarrierLabyrinth.recordVictory(victorious,12);
        check(victorious.getInt("mazeBestCleared")==12 && victorious.getInt("mazeCompletedRuns")==1 &&
              ProtoWire.parse(BarrierLabyrinth.info(victorious,role,now)).number(24,0)==17,
              "Completed twelve-floor run was not retained");
        rejected(new RunnableWithError(){public void run()throws Exception{
            BarrierLabyrinth.requireCurrentStage(victorious,"3130001025");
        }},"Finished maze accepted another settlement");
        System.out.println("BARRIER_LABYRINTH_SELF_TEST_OK");
    }
}
