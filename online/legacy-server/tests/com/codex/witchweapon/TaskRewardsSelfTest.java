package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Real progress, native batch parameters, atomic rejection and replay checks. */
public final class TaskRewardsSelfTest {
    private static final long NOW=1789900000L;
    private static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    private static JSONObject account(long role)throws Exception{
        return new JSONObject().put("starterProfile",1).put("cosmeticProfile",1)
            .put("roleCreated",true).put("legacyRoleId",role).put("exp",0)
            .put("gold",1000).put("rmb",0).put("ownedServants",new JSONObject());
    }
    private static Map<String,String> args(long role,String ids,String types){
        Map<String,String> form=new HashMap<String,String>();
        form.put("roleid",Long.toString(role));form.put("jobid",ids);
        form.put("typeid",types);return form;
    }
    private static void reject(JSONObject state,JSONObject catalog,Map<String,String> form,
                               long now)throws Exception{
        String before=state.toString();JSONObject next=new JSONObject(before);
        long gold=next.optLong("gold",0),rmb=next.optLong("rmb",0);
        boolean rejected=false;
        try{TaskRewards.claimBatch(next,catalog,form,now,false);}
        catch(LocalDaily.InvalidRequest e){rejected=true;}
        catch(LocalDaily.Conflict e){rejected=true;}
        check(rejected,"Invalid or unready batch must be rejected");
        check(before.equals(state.toString()),"Failed clone must not commit to account");
        check(next.optLong("gold",0)==gold&&next.optLong("rmb",0)==rmb,
            "Validate every requested job before dispatching any ready job");
    }
    private static long lootSum(byte[] wire,int type,int field)throws Exception{
        long sum=0;
        for(ProtoWire.Field f:ProtoWire.parse(wire).fields)if(f.number==1&&f.type==2){
            ProtoWire loot=ProtoWire.parse(f.data);
            if(loot.number(1,0)==type)sum+=loot.number(field,0);
        }
        return sum;
    }
    private static int lootCount(byte[] wire,int type)throws Exception{
        int count=0;
        for(ProtoWire.Field f:ProtoWire.parse(wire).fields)if(f.number==1&&f.type==2&&
            ProtoWire.parse(f.data).number(1,0)==type)count++;
        return count;
    }
    private static void progress(JSONObject state,long now)throws Exception{
        LocalDaily.refresh(state,now);
        state.getJSONObject("dailyTasks").getJSONObject("progress")
            .put("502018001",1).put("502031001",1);
    }
    public static void main(String[] argv)throws Exception{
        if(argv.length!=1)throw new IllegalArgumentException("Pass offline_responses.json");
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(Paths.get(argv[0])),
            StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");

        JSONObject story=account(7).put("mainlineStages",new JSONObject()
            .put("3110002010",new JSONObject().put("wins",1))
            .put("3110003010",new JSONObject().put("wins",1)));
        reject(story,catalog,args(7,"502021004,502021005","021,021"),NOW);
        reject(story,catalog,args(7,"502021004","6"),NOW);
        reject(story,catalog,args(7,"502021004,502021004","021,021"),NOW);
        reject(story,catalog,args(7,"502021004,999999999","021,021"),NOW);
        reject(story,catalog,args(7,"502021004","021,021"),NOW);
        reject(story,catalog,args(7,"","2"),NOW);
        reject(story,catalog,args(8,"502021004","021"),NOW);
        JSONObject failed=account(7).put("mainlineStages",new JSONObject()
            .put("3110002010",new JSONObject().put("wins",0).put("attempts",3).put("stars",3)));
        reject(failed,catalog,args(7,"502021004","021"),NOW);

        Map<String,String> first=args(7,"502021004","021");
        byte[] firstLoot=TaskRewards.claimBatch(story,catalog,first,NOW,false);
        check(story.getLong("gold")==6000&&story.getLong("rmb")==10,
            "Real chapter win pays its original mainline rewards");
        check(lootSum(firstLoot,13,3)==5000&&lootSum(firstLoot,99,3)==10,
            "Mainline native LootObject Value must be preserved");
        String paid=story.toString();
        check(Arrays.equals(firstLoot,TaskRewards.claimBatch(story,catalog,first,NOW+1,false))&&
            paid.equals(story.toString()),"Exact retry replays the receipt without another grant");
        check(Arrays.equals(firstLoot,TaskRewards.claimBatch(story,catalog,first,NOW+86400,false)),
            "Permanent StoryQuest receipt survives a new daily date");
        TaskRewards.claimBatch(story,catalog,args(7,"502021005","21"),NOW+1,false);
        check(story.getJSONObject("mainStoryTaskClaims").getBoolean("502021005"),
            "A pre-cleared successor can be claimed in the next batch");

        JSONObject cosmetic=account(7).put("starterProfile",0);
        byte[] cosmeticLoot=TaskRewards.claimBatch(cosmetic,catalog,
            args(7,"502001001","001"),NOW,false);
        check(cosmetic.getJSONObject("cosmeticAchievementClaims").getBoolean("502001001")&&
            lootSum(cosmeticLoot,13,3)==10000,
            "Original type-001 mainline job dispatches its existing cosmetic handler");

        JSONObject daily=account(9);progress(daily,NOW);
        daily.put("mainlineStages",new JSONObject()
            .put("3110002010",new JSONObject().put("wins",1)));
        reject(daily,catalog,args(9,"502018001,502021004","018,021"),NOW);
        reject(daily,catalog,args(9,"502018001","2"),NOW);
        reject(daily,catalog,args(9,"502018001|502031001","18,31"),NOW);
        reject(daily,catalog,args(9,"502018001|502031001,502021004","18|31|21"),NOW);
        reject(daily,catalog,args(9,"502018001|","18|31"),NOW);
        Map<String,String> dailyForm=args(9,"502018001|502031001","18|31");
        dailyForm.put("jobids",dailyForm.remove("jobid"));
        dailyForm.put("typeids",dailyForm.remove("typeid"));
        byte[] dailyLoot=TaskRewards.claimBatch(daily,catalog,dailyForm,NOW,true);
        check(daily.getLong("activeCurrencyGreen")==7&&daily.getLong("guildCurrency")==60&&
            daily.getLong("exp")==150,"Daily and verified-guild rewards pay once per job");
        check(lootCount(dailyLoot,19)==2&&lootSum(dailyLoot,19,3)==60&&
            lootCount(dailyLoot,18)==2&&lootSum(dailyLoot,18,3)==7,
            "Return all original LootObjects without multiplying or merging native slots");
        String dailyPaid=daily.toString();
        check(Arrays.equals(dailyLoot,TaskRewards.claimBatch(daily,catalog,dailyForm,NOW+1,true))&&
            dailyPaid.equals(daily.toString()),"Daily receipt replays exactly without paying twice");
        reject(daily,catalog,dailyForm,NOW+86400);
        progress(daily,NOW+86400);
        TaskRewards.claimBatch(daily,catalog,dailyForm,NOW+86400,true);
        check(daily.getLong("guildCurrency")==120&&daily.getLong("exp")==300,
            "Same daily IDs need fresh completion on the next date");
        for(int i=0;i<daily.getJSONArray("taskBatchReceipts").length();i++)
            check(daily.getJSONArray("taskBatchReceipts").getJSONObject(i).getLong("day")==
                LocalDaily.day(NOW+86400),"Old daily receipts are discarded");

        JSONObject other=account(7);
        reject(other,catalog,first,NOW);
        check(!other.has("taskBatchReceipts")&&!other.has("mainStoryTaskClaims"),
            "Progress, grants and receipts remain isolated even for equal legacy role IDs");
        System.out.println("TASK_REWARDS_SELF_TEST_OK");
    }
}
