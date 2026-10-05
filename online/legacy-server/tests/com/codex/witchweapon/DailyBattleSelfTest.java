package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Isolated original-protocol checks; never reads or writes a player save. */
public final class DailyBattleSelfTest {
    private static void check(boolean good,String message){if(!good)throw new AssertionError(message);}
    private static JSONObject account()throws Exception{
        return new JSONObject().put("roleCreated",true).put("legacyRoleId",101)
            .put("starterProfile",1).put("stamina",200).put("gold",1000).put("exp",0);
    }
    private static Map<String,String> form(String identity){
        Map<String,String> args=new HashMap<String,String>();args.put("idempotency",identity);return args;
    }
    private static long noon(int year,int month,int day){
        return LocalDate.of(year,month,day).atTime(12,0).toEpochSecond(ZoneOffset.ofHours(8));
    }
    private static ProtoWire level(byte[] bytes,long id)throws Exception{
        for(ProtoWire.Field chapter:ProtoWire.parse(bytes).fields)if(chapter.number==1&&chapter.type==2)
            for(ProtoWire.Field item:ProtoWire.parse(chapter.data).fields)if(item.number==2&&item.type==2){
                ProtoWire level=ProtoWire.parse(item.data);
                if(level.number(1,0)==id)return level;
            }
        throw new AssertionError("Missing level "+id);
    }
    private static int dailyChapters(byte[] bytes)throws Exception{
        int count=0;
        for(ProtoWire.Field f:ProtoWire.parse(bytes).fields)if(f.number==1&&f.type==2){
            long id=ProtoWire.parse(f.data).number(1,0);
            if(id>=3020001&&id<=3020006)count++;
        }
        return count;
    }
    private static int groupBattleCount(byte[] bytes,long first,int levels)throws Exception{
        int count=0;
        for(int i=0;i<levels;i++)count+=level(bytes,first+i).number(6,0);
        return count;
    }
    private static void rejects(RunnableWithException action)throws Exception{
        try{action.run();throw new AssertionError("Expected rejection");}
        catch(java.io.IOException expected){}
    }
    private interface RunnableWithException{void run()throws Exception;}
    public static void main(String[] argv)throws Exception{
        DailyBattle daily=DailyBattle.bundled();
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(
            Paths.get("resources/offline_responses.json")),StandardCharsets.UTF_8));
        byte[] seed=Base64.decode(fixtures.getJSONObject("/level/getAllProgress")
            .getString("base64"),Base64.DEFAULT);
        JSONObject extra=new JSONObject();daily.install(extra);
        check(extra.length()==80,"Forty daily combat JSON and monster fixtures");
        check(daily.supports(3120001001L)&&daily.supports(3120006006L),"Daily stages recognized");
        check(!daily.supports(3120007001L),"The separate furnace is excluded");
        long friday=noon(2026,9,25),sunday=noon(2026,9,27);
        JSONObject a=account(),b=account();
        byte[] current=daily.progress(seed,a,friday);
        check(dailyChapters(current)==6,"Six daily chapters appended to original progress");
        check(level(current,3120001001L).number(4,1)==0,"Thursday/Sunday trial closed Friday");
        check(level(current,3120002001L).number(4,0)==1,"Friday trial open");
        check(level(current,3120002002L).number(4,1)==0,"Second difficulty needs first clear");
        check(level(current,3120005001L).number(4,0)==1,"Friday bounty open");
        check(level(current,3120006001L).number(4,1)==0,"Friday practice closed");
        rejects(()->daily.begin(a,3120001001L,form("closed"),friday));
        byte[] openAccess=daily.progress(seed,a,friday,true);
        check(level(openAccess,3120001001L).number(4,0)==1 &&
              level(openAccess,3120002007L).number(4,0)==1 &&
              level(openAccess,3120006006L).number(4,0)==1,
              "Open-access client may choose any daily challenge without a weekday or prior clear");
        JSONObject late=daily.begin(account(),3120002007L,form("open-late"),friday,true);
        check(late.optLong("activeStage")==3120002007L,
              "Server permits the unopened final difficulty in open-access mode");
        long stage=3120002001L;
        JSONObject started=daily.begin(a,stage,form("first"),friday);
        check(started.getJSONObject("dailyBattleAttempts").getInt("3020002")==1,
            "One shared daily attempt recorded");
        check(daily.begin(started,stage,form("first"),friday)==started,
            "Start retry does not spend another attempt");
        Map<String,String> won=form("first");won.put("instanceid",String.valueOf(stage));
        won.put("pass","1");won.put("stars","2");
        DailyBattle.Settlement result=daily.settle(started,fixtures.getJSONObject("_catalog"),won,friday+60);
        JSONObject settled=result.state;
        check(settled.getLong("stamina")==190 && settled.getLong("exp")==5,
            "Daily success charges stamina and awards role experience once");
        check(settled.getJSONObject("items").getLong("40220003")==1,
            "Original Magic Overflow reward enters this account's inventory");
        check(settled.getJSONObject("dailyBattleStages").getJSONObject(String.valueOf(stage))
            .getInt("wins")==1,"Difficulty clear is durable");
        check(ProtoWire.parse(result.response).number(1,0)==190,
            "Original BattleResult carries remaining stamina");
        JSONObject partial=account().put("stamina",50).put("staminaRegenCap",60)
            .put("staminaRegenAt",friday-150);
        JSONObject partialStarted=daily.begin(partial,stage,form("partial-clock"),friday);
        Map<String,String> partialWin=form("partial-clock");
        partialWin.put("instanceid",String.valueOf(stage));partialWin.put("pass","1");
        ProtoWire partialResult=ProtoWire.parse(daily.settle(partialStarted,
            fixtures.getJSONObject("_catalog"),partialWin,friday+60).response);
        check(partialResult.number(1,0)==40 && partialResult.number(2,0)==friday-150,
            "Daily BattleResult reset the original AP countdown");
        DailyBattle.Settlement replay=daily.settle(settled,fixtures.getJSONObject("_catalog"),won,friday+90);
        check(replay.state==settled && Arrays.equals(result.response,replay.response),
            "Settlement retry returns the exact stored response without reward");
        check(daily.begin(settled,stage,form("first"),friday+90)==settled,
            "Settled start retry does not charge an attempt");
        current=daily.progress(seed,settled,friday+100);
        check(level(current,stage).number(2,0)==1 && level(current,3120002002L).number(4,0)==1,
            "First clear unlocks second difficulty in the original progress protocol");
        JSONObject again=daily.begin(settled,3120002002L,form("second"),friday+120);
        Map<String,String> lost=new HashMap<String,String>();lost.put("pass","0");lost.put("stars","0");
        JSONObject afterLoss=daily.settle(again,fixtures.getJSONObject("_catalog"),lost,friday+150).state;
        check(afterLoss.getLong("stamina")==190 && afterLoss.getLong("exp")==5,
            "Failed battle consumes an attempt but grants no reward");
        rejects(()->daily.begin(afterLoss,stage,form("third"),friday+180));
        check(level(daily.progress(seed,afterLoss,friday+180),stage).number(4,1)==0,
            "Shared two-attempt limit closes the set");
        check(level(daily.progress(seed,afterLoss,sunday),stage).number(4,0)==1,
            "Beijing next open day resets shared attempts");
        check(level(daily.progress(seed,b,friday),stage).number(2,1)==0 &&
            b.optJSONObject("dailyBattleStages")==null,"Other account stays untouched");
        // The client sums Level.BattleCount across all six difficulties of
        // the soda set. Publishing the shared total on each level made two
        // plays look like twelve, so its displayed balance became 3-12=-9.
        long soda=3120006001L;
        JSONObject sodaState=account();
        for(int run=0;run<2;run++){
            long id=soda+run;
            String key="soda-"+run;
            sodaState=daily.begin(sodaState,id,form(key),friday+200+run*120,true);
            Map<String,String> victory=form(key);
            victory.put("instanceid",String.valueOf(id));victory.put("pass","1");
            sodaState=daily.settle(sodaState,fixtures.getJSONObject("_catalog"),
                victory,friday+260+run*120).state;
        }
        byte[] sodaProgress=daily.progress(seed,sodaState,friday+500,true);
        check(groupBattleCount(sodaProgress,soda,6)==2 &&
            level(sodaProgress,soda).number(6,0)==1 &&
            level(sodaProgress,soda+1).number(6,0)==1,
            "Soda group must report two per-level plays, leaving one of three");
        JSONObject oldSoda=account().put("dailyBattleDay",DailyBattle.chinaDay(friday))
            .put("dailyBattleStage",soda+1)
            .put("dailyBattleAttempts",new JSONObject()
                .put("day",DailyBattle.chinaDay(friday)).put("3020006",2));
        check(groupBattleCount(daily.progress(seed,oldSoda,friday,true),soda,6)==2,
            "Old group-only save must not repeat its two plays on all six levels");
        JSONObject overLimit=new JSONObject(oldSoda.toString());
        overLimit.getJSONObject("dailyBattleAttempts").put("3020006",12);
        byte[] capped=daily.progress(seed,overLimit,friday,true);
        check(groupBattleCount(capped,soda,6)==3 &&
            level(capped,soda+1).number(6,0)==3 &&
            overLimit.getJSONObject("dailyBattleAttempts").getInt("3020006")==12,
            "Old over-limit save must display zero remaining without rewriting its ledger");
        rejects(()->daily.begin(overLimit,soda+2,form("over-limit"),friday+600,true));
        JSONObject overLimitPerStage=new JSONObject(overLimit.toString());
        overLimitPerStage.put("dailyBattleStageAttempts",new JSONObject()
            .put("day",DailyBattle.chinaDay(friday))
            .put(String.valueOf(soda),2).put(String.valueOf(soda+1),10));
        byte[] perStageCapped=daily.progress(seed,overLimitPerStage,friday,true);
        check(groupBattleCount(perStageCapped,soda,6)==3 &&
            level(perStageCapped,soda).number(6,0)==2 &&
            level(perStageCapped,soda+1).number(6,0)==1,
            "Over-limit per-stage history must stay within the shared daily limit");
        JSONObject migrated=daily.begin(oldSoda,soda+2,form("soda-third"),friday+600,true);
        check(groupBattleCount(daily.progress(seed,migrated,friday+600,true),soda,6)==3 &&
            level(daily.progress(seed,migrated,friday+600,true),soda+2).number(6,0)==1,
            "Old soda save was not migrated to per-level attempts on its next play");
        check(DailyBattle.chinaDay(57599)==0 && DailyBattle.chinaDay(57600)==1,
            "UTC+8 midnight is the reset boundary");
        System.out.println("DAILY_BATTLE_SELF_TEST_OK");
    }
}
