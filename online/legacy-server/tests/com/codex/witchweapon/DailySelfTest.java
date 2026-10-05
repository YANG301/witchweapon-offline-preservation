package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;

public final class DailySelfTest {
    private static final long D = 86400;
    private static void check(boolean okay,String message) {
        if(!okay)throw new AssertionError(message);
    }
    private static JSONObject account(long role) throws Exception {
        return new JSONObject().put("roleCreated",true).put("legacyRoleId",role)
            .put("gold",1000).put("rmb",0).put("items",new JSONObject())
            .put("equips",new JSONObject()).put("ownedServants",new JSONObject());
    }
    private static JSONObject catalog() throws Exception {
        return new JSONObject().put("items",new JSONObject()
            .put("40220020",new JSONObject()).put("40320001",new JSONObject())
            .put("40350003",new JSONObject()).put("40330099",new JSONObject()));
    }
    private static Map<String,String> form(long role,long base) {
        Map<String,String> result=new HashMap<String,String>();
        result.put("roleid",String.valueOf(role));result.put("baseid",String.valueOf(base));
        return result;
    }
    private static ProtoWire activity(JSONObject state,long now)throws Exception {
        ProtoWire result=new ProtoWire();LocalDaily.appendTo(result,state,now);return result;
    }
    private static ProtoWire entry(ProtoWire list,long base)throws Exception {
        for(ProtoWire.Field f:list.fields)if(f.number==1 && f.type==2){
            ProtoWire e=ProtoWire.parse(f.data);
            if(e.number(2,0)==base)return e;
        }
        throw new AssertionError("Missing activity " + base);
    }
    private static ProtoWire job(ProtoWire list,long id)throws Exception {
        for(ProtoWire.Field f:list.fields)if(f.number==1 && f.type==2){
            ProtoWire e=ProtoWire.parse(f.data);
            if(e.number(1,0)==id)return e;
        }
        throw new AssertionError("Missing job " + id);
    }
    private static long firstTaskMeta(ProtoWire list,long id)throws Exception {
        for(ProtoWire.Field f:list.fields)if(f.number==2 && f.type==2){
            ProtoWire e=ProtoWire.parse(f.data);
            if(e.number(3,0)==id)return e.number(4,0);
        }
        throw new AssertionError("Missing task meta " + id);
    }
    private static void taskProgress(JSONObject state,long now,long id,long amount)throws Exception {
        LocalDaily.refresh(state,now);
        state.getJSONObject("dailyTasks").getJSONObject("progress")
            .put(String.valueOf(id),amount);
    }
    private static void checkRoleFields(JSONObject state)throws Exception {
        state.put("name","Test role");
        LocalSave save=new LocalSave(new File("."));
        Field value=LocalSave.class.getDeclaredField("state");
        value.setAccessible(true);value.set(save,state);
        byte[] seed=new ProtoWire().set(1,new ProtoWire().bytes()).bytes();
        JSONObject catalog=new JSONObject().put("roleLevels",new JSONObject());
        ProtoWire role=ProtoWire.parse(ProtoWire.parse(save.respond("/role/role",
            Collections.<String,String>emptyMap(),seed,catalog)).data(1));
        check(role.number(106,-1)==state.optLong("exp"),"Role EXP field 106");
        check(role.number(124,-1)==VipSystem.progress(state.optLong("vipExp")),
            "VIP level progress field 124");
        check(role.number(125,-1)==state.optLong("vipPoint"),"VIP point field 125");
    }
    private static void invalid(RunnableWithException action)throws Exception {
        try { action.run();throw new AssertionError("Expected rejection"); }
        catch(LocalDaily.InvalidRequest expected) {}
    }
    private interface RunnableWithException { void run()throws Exception; }
    public static void main(String[] argv)throws Exception {
        check(LocalDaily.day(57599)==0 && LocalDaily.day(57600)==1,
            "Attendance boundary is midnight UTC+8");
        JSONObject a=account(101),b=account(202),defs=catalog();
        long start=2_000_000_000L;
        long today=LocalDaily.day(start);
        ProtoWire list=activity(a,start);
        check(list.fields.size()==3,"Three original activity entries");
        check(entry(list,25).number(1,0)==14,"Accumulated login activity");
        check(entry(list,26).number(1,0)==15,"Seven-day login activity");
        check(entry(list,999).number(1,0)==7,"Stamina placeholder activity");
        ProtoWire streak=ProtoWire.parse(entry(list,26).data(108));
        check(streak.number(1,0)==1 && streak.number(3,0)==1,"First day claimable");
        activity(a,start+60);
        check(a.getJSONObject("dailyLogin").getInt("totalDays")==1,"Same day no duplicate login");
        invalid(()->LocalDaily.claim(a,defs,"/activity/sign/continuitygain",form(202,26),start));
        byte[] first=LocalDaily.claim(a,defs,"/activity/sign/continuitygain",form(101,26),start);
        check(a.getLong("gold")==1500,"Day one original 500 gold granted");
        check(Arrays.equals(first,LocalDaily.claim(a,defs,"/activity/sign/continuitygain",form(101,26),start+10)),"Retry reply stable");
        check(a.getLong("gold")==1500,"Retry cannot duplicate reward");
        check(ProtoWire.parse(entry(activity(a,start+20),26).data(108)).number(3,1)==0,"Claim flag cleared");
        activity(b,start);
        check(b.getJSONObject("dailyLogin").getInt("totalDays")==1 && b.getLong("gold")==1000,"Other account isolated");
        long second=start+D;
        if(LocalDaily.day(second)==today)throw new AssertionError("Test day arithmetic");
        check(ProtoWire.parse(entry(activity(a,second),26).data(108)).number(1,0)==2,"Second consecutive day");
        LocalDaily.claim(a,defs,"/activity/sign/continuitygain",form(101,26),second);
        check(a.getJSONObject("items").getLong("40220020")==5,"Day two original item granted");
        activity(a,second+2*D);
        check(a.getJSONObject("dailyLogin").getInt("streakDays")==1,"Missing day resets streak");
        check(a.getJSONObject("dailyLogin").getInt("totalDays")==3,"Accumulated days retained");
        long cursor=second+2*D;
        while(a.getJSONObject("dailyLogin").getInt("totalDays")<15) {
            cursor+=D;activity(a,cursor);
        }
        check(ProtoWire.parse(entry(activity(a,cursor),25).data(107)).number(3,0)==1,"15th day cumulative reward available");
        long count=a.getJSONObject("items").optLong("40350003");
        LocalDaily.claim(a,defs,"/activity/sign/autogain",form(101,25),cursor);
        LocalDaily.claim(a,defs,"/activity/sign/autogain",form(101,25),cursor);
        check(a.getJSONObject("items").getLong("40350003")==count+3,"Cumulative grant exactly once");
        JSONObject before=new JSONObject(a.toString());
        a.put("drawCount",1);
        LocalDaily.observe(a,before,"/draw/gold/single",cursor);
        ProtoWire tasks=ProtoWire.parse(LocalDaily.taskList(a,new byte[0],cursor));
        int dailyCount=0;
        for(ProtoWire.Field f:tasks.fields)if(f.number==1 && f.type==2 &&
                LocalDaily.dailyTask(String.valueOf(ProtoWire.parse(f.data).number(1,0))))dailyCount++;
        check(dailyCount==15,"All fifteen original CN daily jobs are shown");
        check(job(tasks,502031001L).number(2,-1)==0,"Gold draw task ready");
        check(firstTaskMeta(tasks,502031001L)==1,"Gold draw progress shown");
        Map<String,String> request=form(101,0);request.put("jobid","502031001");
        final long taskDay=cursor;
        invalid(()->LocalDaily.claimTask(a,defs,form(202,0),taskDay));
        Map<String,String> huge=form(101,0);huge.put("jobid","9999999999999999999");
        invalid(()->LocalDaily.claimTask(a,defs,huge,taskDay));
        byte[] taskAward=LocalDaily.claimTask(a,defs,request,cursor);
        check(ProtoWire.parse(taskAward).fields.size()==4,"All four gold-draw rewards returned");
        check(Arrays.equals(taskAward,LocalDaily.claimTask(a,defs,request,cursor)),
            "Daily reward retry reply stable");
        check(a.getLong("activeCurrencyGreen")==3,"Daily task reward exactly once");
        check(a.getLong("exp")==50 && a.getLong("vipExp")==30 &&
            a.getLong("vipPoint")==30,"Gold-draw XP and VIP rewards exactly once");
        check(a.getJSONObject("vipFreeExpDays").getLong(Long.toString(
            LocalDaily.day(cursor)))==30,
            "Daily quest CAPH score is recorded in its fifteen-day expiry bucket");
        checkRoleFields(a);
        check(job(ProtoWire.parse(LocalDaily.taskList(a,new byte[0],cursor)),502031001L).number(2,0)==1,"Claimed task status");
        JSONObject old=account(404);
        taskProgress(old,cursor,502031001L,1);
        old.put("activeCurrencyGreen",3).put("exp",17).put("vipExp",2).put("vipPoint",9);
        old.getJSONObject("dailyTasks").getJSONObject("claimed").put("502031001",true);
        LocalDaily.taskList(old,new byte[0],cursor);
        check(old.getLong("activeCurrencyGreen")==3 && old.getLong("exp")==67 &&
            old.getLong("vipExp")==32 && old.getLong("vipPoint")==39,
            "Old claim backfill excludes previously paid green");
        check(old.getJSONObject("vipFreeExpDays").getLong(Long.toString(
            LocalDaily.day(cursor)))==30,
            "Legacy task reward backfill dates only its newly paid free score");
        LocalDaily.taskList(old,new byte[0],cursor);
        check(old.getLong("activeCurrencyGreen")==3 && old.getLong("exp")==67 &&
            old.getLong("vipExp")==32 && old.getLong("vipPoint")==39,
            "Old claim backfill repeats exactly zero times");
        JSONObject oldDirect=account(405);
        taskProgress(oldDirect,cursor,502031001L,1);
        oldDirect.put("activeCurrencyGreen",3);
        oldDirect.getJSONObject("dailyTasks").getJSONObject("claimed").put("502031001",true);
        Map<String,String> oldForm=form(405,0);oldForm.put("jobid","502031001");
        LocalDaily.claimTask(oldDirect,defs,oldForm,cursor);
        LocalDaily.claimTask(oldDirect,defs,oldForm,cursor);
        check(oldDirect.getLong("activeCurrencyGreen")==3 && oldDirect.getLong("exp")==50 &&
            oldDirect.getLong("vipExp")==30 && oldDirect.getLong("vipPoint")==30,
            "Direct old-claim retry backfills missing rewards only once");
        long[] activeIDs={502018001L,502022001L,502022005L,502031001L,
            502034001L,502083001L};
        long[][] rewardAmounts={{4,100,0,40},{6,100,50,50},{6,200,80,75},
            {3,50,30,30},{3,100,50,50},{3,100,0,20}};
        for(int i=0;i<activeIDs.length;i++) {
            JSONObject player=account(500+i);
            taskProgress(player,cursor,activeIDs[i],i==1?10:1);
            Map<String,String> form=form(500+i,0);
            form.put("jobid",String.valueOf(activeIDs[i]));
            LocalDaily.claimTask(player,defs,form,cursor);
            check(player.getLong("activeCurrencyGreen")==rewardAmounts[i][0] &&
                player.getLong("exp")==rewardAmounts[i][1] &&
                player.optLong("vipExp")==rewardAmounts[i][2] &&
                player.getLong("vipPoint")==rewardAmounts[i][3],
                "All original rewards for daily task "+activeIDs[i]);
        }
        tasks=ProtoWire.parse(LocalDaily.taskList(a,new byte[0],cursor+D));
        check(firstTaskMeta(tasks,502031001L)==0 && job(tasks,502031001L).number(2,0)==-1,"Task progress resets next day");
        JSONObject c=account(303);
        activity(c,start);
        c.getJSONObject("ownedServants").put("1",LocalEconomy.encode(new ProtoWire()
            .set(2,1).set(3,0).set(12,1).set(16,0)));
        JSONObject preWeapon=new JSONObject(c.toString());
        c.getJSONObject("ownedServants").put("1",LocalEconomy.encode(new ProtoWire()
            .set(2,1).set(3,0).set(12,1).set(16,5)));
        LocalDaily.observe(c,preWeapon,"/servant/weapon",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(c,new byte[0],start));
        check(job(tasks,502018001L).number(2,-1)==0,"Weapon training task ready");
        check(job(tasks,502083001L).number(2,0)==-1,"Drink task not credited by weapon training");
        JSONObject preDrink=new JSONObject(c.toString());
        c.getJSONObject("ownedServants").put("1",LocalEconomy.encode(new ProtoWire()
            .set(2,1).set(3,5).set(12,1).set(16,5)));
        LocalDaily.observe(c,preDrink,"/servant/exp",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(c,new byte[0],start));
        check(job(tasks,502083001L).number(2,-1)==0,"Drink task ready");
        JSONObject preMaze=new JSONObject(c.toString());
        c.put("mazeWins",1);
        LocalDaily.observe(c,preMaze,"/level/pushMainLineProgress",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(c,new byte[0],start));
        check(job(tasks,502022005L).number(2,-1)==0,"Maze clear task ready");
        Map<String,String> mazeClaim=form(303,0);mazeClaim.put("jobid","502022005");
        LocalDaily.claimTask(c,defs,mazeClaim,start);
        check(c.getLong("activeCurrencyGreen")==6,"Maze task original reward granted");

        JSONObject expanded=account(606);
        LocalDaily.refresh(expanded,start);
        JSONObject preHard=new JSONObject(expanded.toString());
        expanded.put("mainlineStages",new JSONObject().put("3110002011",
            new JSONObject().put("wins",1).put("sweeps",0)));
        LocalDaily.observe(expanded,preHard,"/level/pushMainLineProgress",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(expanded,new byte[0],start));
        check(job(tasks,502022002L).number(2,-1)==0 &&
            firstTaskMeta(tasks,502022001L)==0,"Hard clears do not count as normal clears");
        JSONObject preSweep=new JSONObject(expanded.toString());
        expanded.getJSONObject("mainlineStages").put("3110002001",
            new JSONObject().put("wins",0).put("sweeps",10));
        LocalDaily.observe(expanded,preSweep,"/level/sweep",start);
        LocalDaily.observe(expanded,new JSONObject(expanded.toString()),"/level/sweep",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(expanded,new byte[0],start));
        check(firstTaskMeta(tasks,502022001L)==10 && job(tasks,502022001L).number(2,-1)==0,
            "Normal sweeps count once and unchanged replay counts zero");
        JSONObject preDaily=new JSONObject(expanded.toString());
        expanded.put("dailyBattleStages",new JSONObject().put("3120001001",
            new JSONObject().put("wins",1)).put("3120005001",new JSONObject().put("sweeps",1)));
        expanded.put("furnaceStages",new JSONObject().put("3120007001",new JSONObject().put("wins",1)));
        LocalDaily.observe(expanded,preDaily,"/level/pushDailyProgress",start);
        tasks=ProtoWire.parse(LocalDaily.taskList(expanded,new byte[0],start));
        for(long id:new long[]{502022003L,502022004L,502022007L})
            check(job(tasks,id).number(2,-1)==0,"Original battle type daily is ready: "+id);
        JSONObject preActivity=new JSONObject(expanded.toString()).put("activityStamina",500).put("stamina",500);
        expanded.put("activityStamina",100).put("stamina",100);
        LocalDaily.observe(expanded,preActivity,"/level/startBattle",start);
        Map<String,String> activityClaim=form(606,0);activityClaim.put("jobid","502043004");
        byte[] activityLoot=LocalDaily.claimTask(expanded,defs,activityClaim,start);
        check(expanded.getJSONObject("items").getLong("40330099")==1 &&
            expanded.getLong("activeCurrencyGreen")==5 && expanded.getLong("vipExp")==70 &&
            expanded.getLong("vipPoint")==50 && ProtoWire.parse(activityLoot).fields.size()==4,
            "Activity stamina daily gives its original supply and resource rewards");
        String activityPaid=expanded.toString();
        LocalDaily.claimTask(expanded,defs,activityClaim,start);
        check(activityPaid.equals(expanded.toString()),"Activity daily replay grants no second item");
        JSONObject ordinary=account(607),preOrdinary=new JSONObject(ordinary.toString()).put("stamina",500);
        ordinary.put("stamina",100);
        LocalDaily.observe(ordinary,preOrdinary,"/level/startBattle",start);
        check(firstTaskMeta(ProtoWire.parse(LocalDaily.taskList(ordinary,new byte[0],start)),
            502043004L)==0,"Normal stamina is not event stamina");
        Map<String,String> powder=new HashMap<String,String>();powder.put("setid","44000188");
        LocalDaily.recordShopPurchase(expanded,powder,start);
        LocalDaily.recordGuildSupport(expanded,start);
        LocalDaily.recordGuildDonation(expanded,start);
        tasks=ProtoWire.parse(LocalDaily.taskList(expanded,new byte[0],start));
        for(long id:new long[]{502040001L,502071002L,502074001L})
            check(job(tasks,id).number(2,-1)==0,"Successful authoritative callback completes daily: "+id);
        JSONObject summary=account(608);
        long[] twelve={502018001L,502022001L,502022002L,502022003L,502022004L,
            502022005L,502022007L,502031001L,502034001L,502040001L,502071002L,502074001L};
        for(long id:twelve)taskProgress(summary,start,id,id==502022001L?10:1);
        tasks=ProtoWire.parse(LocalDaily.taskList(summary,new byte[0],start));
        check(job(tasks,502006001L).number(2,-1)==0 && firstTaskMeta(tasks,502006001L)==12,
            "Summary daily counts twelve completed jobs without requiring claims");
        Map<String,String> summaryClaim=form(608,0);summaryClaim.put("jobid","502006001");
        LocalDaily.claimTask(summary,defs,summaryClaim,start);
        LocalDaily.claimTask(summary,defs,summaryClaim,start);
        check(summary.getLong("rmb")==10,"Original summary diamond reward is paid once");
        byte[] refreshed=LocalDaily.taskList(summary,tasks.bytes(),start);
        check(job(ProtoWire.parse(refreshed),502006001L).number(2,-1)==1,
            "Stale seed rows are refreshed to the saved claim status");

        JSONObject batch=account(707);
        taskProgress(batch,start,502031001L,1);
        Map<String,String> batchForm=form(707,0);
        batchForm.put("jobid","502031001,502034001");
        String beforeBadBatch=batch.toString();
        Map<String,String> badBatch=form(707,0);badBatch.put("jobid","502031001,509005003");
        invalid(()->LocalDaily.claimTaskBatch(batch,defs,badBatch,start));
        check(beforeBadBatch.equals(batch.toString()),"Invalid batch must not change save");
        byte[] firstBatch=LocalDaily.claimTaskBatch(batch,defs,batchForm,start);
        check(ProtoWire.parse(firstBatch).fields.size()==4,
            "Batch response must contain the first task's visible loot");
        check(batch.getLong("activeCurrencyGreen")==3&&batch.getLong("exp")==50,
            "Batch did not grant the completed task");
        check(Arrays.equals(firstBatch,LocalDaily.claimTaskBatch(batch,defs,batchForm,start))&&
            batch.getLong("activeCurrencyGreen")==3,
            "Batch retry must show the same loot without paying twice");
        taskProgress(batch,start,502034001L,1);
        byte[] secondBatch=LocalDaily.claimTaskBatch(batch,defs,batchForm,start);
        check(ProtoWire.parse(secondBatch).fields.size()==4&&
            batch.getLong("activeCurrencyGreen")==6&&batch.getLong("exp")==150,
            "A newly completed task must be claimable with the same batch request");
        taskProgress(batch,start,502018001L,1);
        Map<String,String> categoryBatch=form(707,0);categoryBatch.put("typeid","2");
        byte[] thirdBatch=LocalDaily.claimTaskBatch(batch,defs,categoryBatch,start);
        check(ProtoWire.parse(thirdBatch).fields.size()==3&&
            batch.getLong("activeCurrencyGreen")==10&&batch.getLong("exp")==250,
            "Daily category batch did not claim its ready task");
        Map<String,String> wrongCategory=form(707,0);wrongCategory.put("typeid","3");
        invalid(()->LocalDaily.claimTaskBatch(batch,defs,wrongCategory,start));

        // The live one-key route must not fall through to the author's empty
        // response fixture, which caused the original blank reward panel.
        Path isolated=Files.createTempDirectory("ww-daily-batch-");
        try {
            JSONObject routed=account(808).put("version",1);
            taskProgress(routed,System.currentTimeMillis()/1000,502031001L,1);
            LocalSave routedSave=new LocalSave(isolated.toFile());
            Field stateField=LocalSave.class.getDeclaredField("state");
            stateField.setAccessible(true);stateField.set(routedSave,routed);
            Map<String,String> routedForm=form(808,0);routedForm.put("jobid","502031001");
            routedForm.put("typeid","031");
            JSONObject routedCatalog=new JSONObject(defs.toString())
                .put("roleLevels",new JSONObject());
            byte[] routedLoot=routedSave.respond("/task/updatemore",routedForm,
                new byte[0],routedCatalog);
            check(ProtoWire.parse(routedLoot).fields.size()==4,
                "One-key route returned the empty offline fixture");
            check(((JSONObject)stateField.get(routedSave)).getLong("activeCurrencyGreen")==3,
                "One-key route did not commit rewards");
        } finally {
            try(java.util.stream.Stream<Path> files=Files.walk(isolated)){
                files.sorted(Comparator.reverseOrder()).forEach(path->{
                    try{Files.deleteIfExists(path);}catch(Exception ignored){}
                });
            }
        }
        System.out.println("DAILY_SELF_TEST_OK");
    }
}
