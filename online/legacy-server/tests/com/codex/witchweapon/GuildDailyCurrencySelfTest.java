package com.codex.witchweapon;

import org.json.JSONObject;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** The original daily UI promises 30 guild reputation per completed daily quest. */
public final class GuildDailyCurrencySelfTest {
    private static void check(boolean okay,String detail){if(!okay)throw new AssertionError(detail);}
    private static JSONObject account(long role)throws Exception {
        return new JSONObject().put("roleCreated",true).put("legacyRoleId",role)
            .put("starterProfile",1).put("gold",1000).put("rmb",0)
            .put("items",new JSONObject()).put("equips",new JSONObject())
            .put("ownedServants",new JSONObject());
    }
    private static Map<String,String> form(long role,String ids){
        Map<String,String> result=new HashMap<String,String>();
        result.put("roleid",String.valueOf(role));result.put("jobid",ids);
        return result;
    }
    private static void ready(JSONObject state,long now,String... ids)throws Exception {
        LocalDaily.refresh(state,now);
        JSONObject progress=state.getJSONObject("dailyTasks").getJSONObject("progress");
        for(String id:ids)progress.put(id,1);
    }
    private static int guildLoot(byte[] payload)throws Exception {
        int count=0;
        for(ProtoWire.Field field:ProtoWire.parse(payload).fields)if(field.number==1){
            ProtoWire reward=ProtoWire.parse(field.data);
            if(reward.number(1,0)==19){
                check(reward.number(3,0)==30&&reward.number(4,0)==30,
                    "Guild reputation LootObject amount differs from original UI");
                count++;
            }
        }
        return count;
    }
    public static void main(String[] args)throws Exception {
        JSONObject catalog=new JSONObject().put("items",new JSONObject());
        long now=2000000000L;
        JSONObject member=account(101),outsider=account(202);
        ready(member,now,"502031001");ready(outsider,now,"502031001");
        byte[] first=LocalDaily.claimTask(member,catalog,form(101,"502031001"),now,true);
        check(member.getLong("guildCurrency")==30&&guildLoot(first)==1,
            "Verified guild member did not receive daily reputation");
        byte[] replay=LocalDaily.claimTask(member,catalog,form(101,"502031001"),now,false);
        check(Arrays.equals(first,replay)&&member.getLong("guildCurrency")==30,
            "Daily retry changed previously granted reputation");
        byte[] noGuild=LocalDaily.claimTask(outsider,catalog,form(202,"502031001"),now,false);
        check(outsider.optLong("guildCurrency",0)==0&&guildLoot(noGuild)==0,
            "Nonmember received guild shop currency");
        check(guildLoot(LocalDaily.claimTask(outsider,catalog,form(202,"502031001"),now,true))==0&&
            outsider.optLong("guildCurrency",0)==0,
            "Joining after claim retroactively credited an already paid task");
        JSONObject batch=account(303);
        ready(batch,now,"502031001","502034001");
        byte[] together=LocalDaily.claimTaskBatch(batch,catalog,
            form(303,"502031001,502034001"),now,true);
        check(batch.getLong("guildCurrency")==60&&guildLoot(together)==2,
            "One-key claim did not pay 30 reputation for each ready task");
        byte[] togetherReplay=LocalDaily.claimTaskBatch(batch,catalog,
            form(303,"502031001,502034001"),now,true);
        check(Arrays.equals(together,togetherReplay)&&batch.getLong("guildCurrency")==60,
            "One-key retry doubled guild reputation");
        ready(member,now+86400L,"502031001");
        LocalDaily.claimTask(member,catalog,form(101,"502031001"),now+86400L,true);
        check(member.getLong("guildCurrency")==60,
            "Next-day task did not earn a new 30 guild reputation");
        System.out.println("GUILD_DAILY_CURRENCY_OK");
    }
}
