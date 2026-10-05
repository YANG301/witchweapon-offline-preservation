package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.io.File;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Original CN permanent task rows and two recoverable progress chains. */
public final class ProgressionTasksSelfTest {
    private static void check(boolean condition,String label){
        if(!condition)throw new AssertionError(label);
    }
    private static Map<String,String> form(String... pairs){
        Map<String,String> out=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)out.put(pairs[i],pairs[i+1]);
        return out;
    }
    private static ProtoWire job(byte[] response,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2){
                ProtoWire candidate=ProtoWire.parse(field.data);
                if(candidate.number(1,0)==id)return candidate;
            }
        throw new AssertionError("Original task missing: "+id);
    }
    private static int countJobs(byte[] response)throws Exception{
        int count=0;for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2)count++;
        return count;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Pass responses.json");
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(
            new File(args[0]).toPath()),StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");
        byte[] seed=Base64Bytes.decode(fixtures.getJSONObject("/task/all").getString("base64"));
        ProgressionTasks tasks=ProgressionTasks.bundled();
        JSONObject state=new JSONObject().put("version",1).put("starterProfile",1)
            .put("roleCreated",true).put("legacyRoleId",7).put("exp",0).put("rmb",0)
            .put("gold",1000).put("stamina",100).put("ownedServants",new JSONObject());
        byte[] listed=tasks.taskList(state,catalog,seed);
        check(countJobs(listed)==countJobs(seed)+92,
            "All 50 original permanent achievements and 42 mainline tasks are visible");
        check(job(listed,504021001L).number(2,0)==-1&&
            job(listed,501001001L).number(2,0)==-1,
            "No unearned task appears claimable");
        JSONObject stages=new JSONObject().put("3110001001",new JSONObject().put("wins",1))
            .put("3110001004",new JSONObject().put("wins",1));
        state.put("mainlineStages",stages);
        listed=tasks.taskList(state,catalog,seed);
        check(job(listed,504021001L).number(2,-1)==0&&
            job(listed,504021002L).number(2,0)==-1,
            "First stage clear is claimable, next stage needs its predecessor");
        byte[] first=tasks.claim(state,catalog,form("jobid","504021001","roleid","7"));
        check(state.getLong("rmb")==10&&
            Arrays.equals(first,tasks.claim(state,catalog,form("jobid","504021001","roleid","7")))&&
            state.getLong("rmb")==10,
            "Original ten-diamond mainline reward is exactly once");
        check(job(tasks.taskList(state,catalog,seed),504021002L).number(2,-1)==0,
            "Pre-cleared next stage becomes claimable after predecessor claim");
        JSONObject beforeSpend=new JSONObject(state.toString()).put("stamina",200);
        state.put("stamina",100);
        ProgressionTasks.recordMainlineStaminaSpent(beforeSpend,state);
        check(state.getLong("mainlineStaminaSpent")==100&&
            job(tasks.taskList(state,catalog,seed),504043001L).number(2,-1)==0,
            "Original mainline action-point task counts real spent stamina");
        JSONObject costs=catalog.getJSONObject("roleLevels");long exp=0;
        for(int level=1;level<10;level++)exp+=costs.getLong(Integer.toString(level));
        state.put("exp",exp);
        check(job(tasks.taskList(state,catalog,seed),501001001L).number(2,-1)==0,
            "Original level-ten achievement follows the role curve");
        tasks.claim(state,catalog,form("jobid","501001001","roleid","7"));
        check(state.getLong("rmb")==60,
            "Original level-ten achievement gives 50 diamonds exactly once");
        check(job(tasks.taskList(state,catalog,seed),501001002L).number(2,0)==-1,
            "Next level milestone remains incomplete at level ten");
        byte[] achievements=tasks.achievementList(state,catalog,new byte[0]);
        check(countJobs(achievements)==50,"Separate achievement endpoint contains all fifty original CN rows");
        int achievementMetaCount=0;
        for(ProtoWire.Field field:ProtoWire.parse(achievements).fields)if(field.number==2&&field.type==2){
            ProtoWire meta=ProtoWire.parse(field.data);achievementMetaCount++;
            long id=meta.number(3,0);
            check(meta.number(1,0)==1&&id>=501000000L&&id<502000000L,
                "Achievement Result.MetaInfo has original TorD and JobID fields");
            int values=0;
            for(ProtoWire.Field value:meta.fields)if(value.number==4){
                check(value.type==0,"Original achievement Meta is int32 varint, not repeated string Args");
                values++;
            }
            check(values==1,"Every original achievement has one numeric progress value");
            check(Arrays.equals(job(achievements,id).data(4),meta.data(2))&&
                job(achievements,id).number(3,0)==1,
                "Original achievement Job and MetaInfo share TypeID and a valid row");
            if(id==501001001L)check(meta.number(4,-1)==10&&
                new String(meta.data(2),StandardCharsets.UTF_8).equals("001"),
                "Native conversion receives numeric role progress ten and string achievement type 001");
        }
        check(achievementMetaCount==50,"Every original achievement has a matching progress meta");
        check(job(achievements,501001001L).number(2,-1)==1,
            "Achievement endpoint shares the saved task claim ledger");
        byte[] stale=new ProtoWire().add(1,new ProtoWire().set(1,501001001L).set(2,-1).bytes())
            .add(2,new ProtoWire().set(3,501001001L).set(4,0).bytes()).bytes();
        check(countJobs(tasks.achievementList(state,catalog,stale))==50&&
            job(tasks.taskList(state,catalog,stale),501001001L).number(2,-1)==1,
            "Both lists refresh stale seed claims without duplicate rows");
        try{
            tasks.claimAchievement(state,catalog,form("jobid","501001001","roleid","7","type","060"));
            throw new AssertionError("Mismatched achievement type accepted");
        }catch(java.io.IOException expected){}
        try{
            tasks.claimAchievement(state,catalog,form("jobid","504021001","roleid","7"));
            throw new AssertionError("Guide job accepted by achievement route");
        }catch(java.io.IOException expected){}

        JSONObject oldCosmetic=new JSONObject(state.toString()).put("cosmeticAchievementClaims",
            new JSONObject().put("501060001",true));
        long oldGold=oldCosmetic.getLong("gold"),oldDiamonds=oldCosmetic.getLong("rmb");
        tasks.claimAchievement(oldCosmetic,catalog,form("jobid","501060001","roleid","7","type","060"));
        check(oldCosmetic.getLong("gold")==oldGold&&oldCosmetic.getLong("rmb")==oldDiamonds&&
            oldCosmetic.getJSONObject("progressionTaskClaims").getBoolean("501060001"),
            "Legacy cosmetic claim migrates without paying the original reward twice");
        JSONObject weapons=new JSONObject();
        for(int i=1;i<=12;i++)weapons.put(Integer.toString(i),LocalEconomy.encode(new ProtoWire()
            .set(1,i).set(12,60).add(13,new ProtoWire().set(1,100+i).set(4,2).bytes())));
        oldCosmetic.put("ownedServants",weapons);
        tasks.claimAchievement(oldCosmetic,catalog,form("jobid","501060002","roleid","7","type","060"));
        check(CosmeticUnlocks.ownsBoard(oldCosmetic,4),"Permanent achievement preserves original Kanban four reward");
        String paid=oldCosmetic.toString();
        CosmeticAchievements.claim(oldCosmetic,catalog,form("jobid","501060002","roleid","7"));
        check(paid.equals(oldCosmetic.toString()),"Cosmetic and achievement routes use one idempotent claim ledger");
        check(job(tasks.achievementList(oldCosmetic,catalog,new byte[0]),501062001L).number(2,-1)==0,
            "Awakening achievement counts original WeaponSpellPromoteLv field");
        JSONObject purchases=new JSONObject(state.toString()).put("staminaPurchaseDay",1)
            .put("staminaPurchaseUsed",5).put("staminaPurchasesTotal",9);
        JSONObject purchased=new JSONObject(purchases.toString()).put("staminaPurchaseUsed",6);
        ProgressionTasks.recordStaminaPurchase(purchases,purchased);
        check(purchased.getLong("staminaPurchasesTotal")==10&&
            job(tasks.achievementList(purchased,catalog,new byte[0]),501042001L).number(2,-1)==0,
            "Verified purchase increments original cumulative stamina achievement");
        ProgressionTasks.recordStaminaPurchase(new JSONObject(purchased.toString()),purchased);
        check(purchased.getLong("staminaPurchasesTotal")==10,"Purchase replay has no cumulative increment");
        ProgressionTasks.recordGuildMembership(purchased);
        check(job(tasks.achievementList(purchased,catalog,new byte[0]),501070001L).number(2,-1)==0,
            "Verified guild membership proves original join achievement");
        check(job(tasks.achievementList(purchased,catalog,new byte[0]),501100001L).number(2,0)==-1,
            "Missing authoritative kill history never fabricates progress");
        System.out.println("ProgressionTasksSelfTest PASS");
    }
    private static final class Base64Bytes {
        static byte[] decode(String value){return java.util.Base64.getDecoder().decode(value);}
    }
}
