package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

/** Original VIP curve and account-bound C.A.P.H route regression. */
public final class VipSelfTest {
    private static void check(boolean ok,String label){if(!ok)throw new AssertionError(label);}

    private static LocalSave save(File dir,String account,long role,long xp,long points)throws Exception {
        File accountDir=new File(dir,account);
        Files.createDirectories(accountDir.toPath());
        JSONObject value=new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",role).put("name",account).put("gold",1000).put("rmb",0)
            .put("exp",0).put("vipExp",xp).put("vipPoint",points)
            .put("stamina",60).put("activityStamina",0)
            .put("ownedServants",new JSONObject()).put("items",new JSONObject())
            .put("equips",new JSONObject());
        Files.write(new File(accountDir,"offline_save_v1.json").toPath(),
            (value.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        return new LocalSave(accountDir);
    }

    private static JSONObject catalog() throws Exception {
        return new JSONObject().put("roleLevels",new JSONObject())
            .put("items",new JSONObject().put("40330099",new JSONObject())
                .put("40340009",new JSONObject()));
    }

    private static JSONObject saved(File root,String account)throws Exception {
        return new JSONObject(new String(Files.readAllBytes(new File(
            new File(root,account),"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8));
    }

    private static boolean hasLoot(byte[] bytes,int type,long id,long amount)throws Exception {
        for(ProtoWire.Field field:ProtoWire.parse(bytes).fields)
            if(field.number==1 && field.type==2) {
                ProtoWire loot=ProtoWire.parse(field.data);
                if(loot.number(1,0)==type && loot.number(2,0)==id &&
                   loot.number(4,0)==amount)return true;
            }
        return false;
    }

    public static void main(String[] args)throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("Pass isolated directory");
        File root=new File(args[0]);
        Files.createDirectories(root.toPath());
        check(VipSystem.level(0)==0 && VipSystem.level(999)==0 && VipSystem.level(1000)==1,
            "Original CAPH first level boundary");
        check(VipSystem.level(2999)==1 && VipSystem.level(3000)==2 &&
            VipSystem.level(22999)==4 && VipSystem.level(23000)==5 &&
            VipSystem.level(Long.MAX_VALUE)==5,"Original cumulative 0..5 curve");
        check(VipSystem.progress(999)==999 && VipSystem.progress(3000)==0 &&
            VipSystem.progress(23000)==0,"Per-level progress never exceeds next tier");
        JSONObject tier0=new JSONObject().put("vipExp",0),
            tier1=new JSONObject().put("vipExp",1000),
            tier3=new JSONObject().put("vipExp",7000),
            tier4=new JSONObject().put("vipExp",13000);
        long weekday=1700000000L,weekend=weekday+3*86400L;
        check(VipSystem.freeGoldLimit(tier0)==5&&VipSystem.freeGoldLimit(tier1)==6,
            "Level one grants exactly one extra daily gold prayer");
        check(VipSystem.freeTarotLimit(tier3,weekday)==1&&
            VipSystem.freeTarotLimit(tier3,weekend)==2&&
            VipSystem.freeTarotLimit(tier0,weekend)==1,
            "Level three adds one weekend-only Tarot prayer in China time");
        check(VipSystem.mazeSupplyMultiplier(tier3)==1&&
            VipSystem.mazeSupplyMultiplier(tier4)==2,
            "Level four doubles maze supply crate rewards");
        long earnedAt=1700000000L;
        long earnedDay=LocalDaily.day(earnedAt);
        JSONObject free=new JSONObject().put("vipExp",3000);
        VipSystem.grantFreeExp(free,50,earnedAt);
        VipSystem.grantFreeExp(free,30,earnedAt+86400);
        check(free.getLong("vipExp")==3080 &&
            free.getJSONObject("vipFreeExpDays").getLong(Long.toString(earnedDay))==50,
            "Free score grants retain their original earning day");
        check(!VipSystem.refresh(free,earnedAt+14*86400L) && free.getLong("vipExp")==3080,
            "Free score remains available through day fourteen");
        check(VipSystem.refresh(free,earnedAt+15*86400L) && free.getLong("vipExp")==3030,
            "Only the first daily score bucket expires on day fifteen");
        check(!VipSystem.refresh(free,earnedAt+15*86400L) && free.getLong("vipExp")==3030,
            "Repeated requests cannot subtract expired score twice");
        check(VipSystem.refresh(free,earnedAt+16*86400L) && free.getLong("vipExp")==3000,
            "Second daily bucket expires independently; legacy score stays intact");
        JSONObject oldScore=new JSONObject().put("vipExp",3000);
        check(!VipSystem.refresh(oldScore,earnedAt+1000*86400L) &&
            oldScore.getLong("vipExp")==3000,
            "Older saves without earning dates must not lose CAPH score");
        LocalSave a=save(root,"first",101,3000,450),b=save(root,"second",202,999,25),
            c=save(root,"fifth",303,23000,900);
        JSONObject catalog=catalog();
        Map<String,String> first=new HashMap<String,String>();first.put("roleid","101");
        Map<String,String> second=new HashMap<String,String>();second.put("roleid","202");
        ProtoWire seed=new ProtoWire().add(1,new ProtoWire().bytes());
        ProtoWire roleA=ProtoWire.parse(ProtoWire.parse(a.respond("/role/role",first,
            seed.bytes(),null)).data(1));
        ProtoWire roleB=ProtoWire.parse(ProtoWire.parse(b.respond("/role/role",second,
            seed.bytes(),null)).data(1));
        check(roleA.number(102,-1)==2 && roleA.number(124,-1)==0 &&
            roleA.number(125,-1)==450,"First role CAPH level, EXP and points");
        check(roleB.number(102,-1)==0 && roleB.number(124,-1)==999 &&
            roleB.number(125,-1)==25,"Second account remains isolated");
        LocalSave stale=save(root,"expired",404,3050,0);
        JSONObject staleFile=saved(root,"expired");
        staleFile.put("vipFreeExpDays",new JSONObject().put(Long.toString(
            LocalDaily.day(System.currentTimeMillis()/1000)-15),50));
        Files.write(new File(new File(root,"expired"),"offline_save_v1.json").toPath(),
            (staleFile.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        Map<String,String> staleRole=new HashMap<String,String>();staleRole.put("roleid","404");
        ProtoWire refreshedRole=ProtoWire.parse(ProtoWire.parse(stale.respond("/role/role",
            staleRole,seed.bytes(),null)).data(1));
        check(refreshedRole.number(102,-1)==2 && refreshedRole.number(124,-1)==0 &&
            saved(root,"expired").getLong("vipExp")==3000 &&
            saved(root,"expired").getJSONObject("vipFreeExpDays").length()==0,
            "Account request lazily expires and persists free score before role response");
        save(root,"maze",505,13000,0);
        JSONObject mazeState=saved(root,"maze").put("mazeRound",4)
            .put("mazePendingBonus",3);
        Files.write(new File(new File(root,"maze"),"offline_save_v1.json").toPath(),
            (mazeState.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave maze=new LocalSave(new File(root,"maze"));
        byte[] chest=maze.respond("/csc/bonus/commit",new HashMap<String,String>(),
            new byte[0],null);
        ProtoWire chestLoot=ProtoWire.parse(ProtoWire.parse(chest).data(2));
        ProtoWire chestGold=ProtoWire.parse(chestLoot.data(1));
        check(chestGold.number(3,0)==20000&&
            saved(root,"maze").getLong("gold")==21000&&
            saved(root,"maze").getInt("mazeSupplyBoxes")==1,
            "CAPH Lv4 doubles actual maze chest payout, not the opened-box count");
        byte[] chestRetry=maze.respond("/csc/bonus/commit",new HashMap<String,String>(),
            new byte[0],null);
        check(java.util.Arrays.equals(chest,chestRetry)&&
            saved(root,"maze").getLong("gold")==21000,
            "Maze checkpoint retry cannot double pay the CAPH reward");
        ProtoWire info=ProtoWire.parse(a.respond("/vip/info",first,new byte[0],null));
        check(info.number(2,0)==0 && info.number(3,0)==0,
            "Unclaimed level-two and level-five flags use original VipInstance fields");
        boolean wrongRole=false;
        try{a.respond("/vip/info",second,new byte[0],null);}
        catch(VipSystem.Invalid expected){wrongRole=true;}
        check(wrongRole,"CAPH role parameter cannot cross accounts");
        boolean lowLevel=false;
        try{b.respond("/vip/gift2",second,new byte[0],catalog);}
        catch(VipSystem.Conflict expected){lowLevel=true;}
        check(lowLevel && !saved(root,"second").getJSONObject("items").has("40330099"),
            "Below level two cannot receive a daily gift");
        byte[] firstGift=a.respond("/vip/gift2",first,new byte[0],catalog);
        check(hasLoot(firstGift,3,40330099L,1),"Level-two daily gift contains the guaranteed brownie");
        JSONObject persisted=saved(root,"first");
        check(persisted.getJSONObject("items").getLong("40330099")==1 &&
            persisted.getLong("vipPoint")==450,"Level-two gift reaches the inventory once");
        byte[] repeated=a.respond("/vip/gift2",first,new byte[0],catalog);
        check(java.util.Arrays.equals(firstGift,repeated) &&
            saved(root,"first").getJSONObject("items").getLong("40330099")==1,
            "Repeated tap replays the receipt without granting a second item");
        check(ProtoWire.parse(a.respond("/vip/info",first,new byte[0],null)).number(2,0)==1,
            "Level-two daily claim flag is visible in VipInstance");
        check(ProtoWire.parse(b.respond("/vip/info",second,new byte[0],null)).number(2,0)==0,
            "Another account has an independent daily claim flag");
        Map<String,String> fifth=new HashMap<String,String>();fifth.put("roleid","303");
        byte[] advanced=c.respond("/vip/gift5",fifth,new byte[0],catalog);
        check(hasLoot(advanced,3,40340009L,1) && hasLoot(advanced,13,0,10000),
            "Level-five daily gift contains the guaranteed macaron and 10000 gold");
        JSONObject advancedSave=saved(root,"fifth");
        check(advancedSave.getJSONObject("items").getLong("40340009")==1 &&
            advancedSave.getLong("gold")==11000,"Advanced daily gift reaches inventory and wallet");
        JSONObject simulated=new JSONObject(advancedSave.toString());
        long today=LocalDaily.day(1700000000L);
        simulated.put("vipGift5ClaimDay",today);
        check(ProtoWire.parse(VipSystem.info(simulated,fifth,1700000000L)).number(3,0)==1 &&
            ProtoWire.parse(VipSystem.info(simulated,fifth,1700000000L+86400)).number(3,1)==0,
            "Daily C.A.P.H claim clears at the next local game day");
        VipSystem.Action nextDay=VipSystem.respond(simulated,catalog,"/vip/gift5",
            fifth,1700000000L+86400);
        check(nextDay.changed && hasLoot(nextDay.response,3,40340009L,1) &&
            simulated.getJSONObject("items").getLong("40340009")==2 &&
            simulated.getLong("gold")==21000 &&
            ProtoWire.parse(VipSystem.info(simulated,fifth,1700000000L+86400)).number(3,0)==1,
            "Next local game day can grant one more advanced gift");
        System.out.println("VipSelfTest PASS: level curve, account isolation, free score expiry, daily rewards and replay");
    }
}
