package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;

/** The preserved C.A.P.H level curve and the original Vipmod wire protocol. */
final class VipSystem {
    // Original config/clientexel/vip.txt: XP needed from levels 0..4.
    private static final long[] NEXT_LEVEL_EXP={1000,2000,4000,6000,10000};
    static final class Invalid extends IOException { Invalid(String message){super(message);} }
    static final class Conflict extends IOException { Conflict(String message){super(message);} }
    static final class Action {
        final byte[] response;
        final boolean changed;
        Action(byte[] response,boolean changed){this.response=response;this.changed=changed;}
    }

    private VipSystem() {}

    /** Original dictionary 11007: free CAPH score expires after fifteen days. */
    static boolean refresh(JSONObject state,long now)throws Exception {
        JSONObject days=state.optJSONObject("vipFreeExpDays");
        if(days==null)return false; // Older saves have no reliable earning dates.
        long today=LocalDaily.day(now), expired=0;
        List<String> remove=new ArrayList<String>();
        for(Iterator<String> it=days.keys();it.hasNext();) {
            String key=it.next();
            long earned;
            try{earned=Long.parseLong(key);}
            catch(NumberFormatException ex){throw new Invalid("Invalid CAPH free score day");}
            long amount=days.optLong(key,-1);
            if(amount<0)throw new Invalid("Invalid CAPH free score amount");
            if(earned<=today-15) {
                expired=Math.addExact(expired,amount);
                remove.add(key);
            }
        }
        if(remove.isEmpty())return false;
        long balance=state.optLong("vipExp",0);
        // An administrator may have lowered a legacy account's balance after
        // earning free score. Expiry must never make it negative.
        state.put("vipExp",Math.max(0,balance-expired));
        for(String key:remove)days.remove(key);
        return true;
    }

    /** Only proven free sources (daily tasks/sign-in) use the dated ledger. */
    static void grantFreeExp(JSONObject state,long amount,long now)throws Exception {
        if(amount<=0)throw new Invalid("Invalid free CAPH score grant");
        refresh(state,now);
        long today=LocalDaily.day(now);
        JSONObject days=state.optJSONObject("vipFreeExpDays");
        if(days==null){days=new JSONObject();state.put("vipFreeExpDays",days);}
        String key=Long.toString(today);
        days.put(key,Math.addExact(days.optLong(key,0),amount));
        LocalEconomy.addResource(state,"vipExp",0,amount);
    }

    static boolean handles(String path) {
        return path.equals("/vip/info") || path.equals("/vip/gift2") || path.equals("/vip/gift5");
    }

    static int level(long totalExp) {
        if(totalExp<0)totalExp=0;
        int level=0;
        for(long cost:NEXT_LEVEL_EXP) {
            if(totalExp<cost)break;
            totalExp-=cost;
            level++;
        }
        return level;
    }

    /** Dictionary 11000: level one adds one daily free gold prayer. */
    static int freeGoldLimit(JSONObject state) {
        return level(state.optLong("vipExp",0))>=1?6:5;
    }

    /** Dictionary 11002: level three adds a Tarot prayer on weekends. */
    static int freeTarotLimit(JSONObject state,long now) {
        long day=LocalDaily.day(now);
        boolean weekend=Math.floorMod(day+3,7)>=5;
        return weekend && level(state.optLong("vipExp",0))>=3?2:1;
    }

    /** Dictionary 11003: level four doubles maze supply crate rewards. */
    static int mazeSupplyMultiplier(JSONObject state) {
        return level(state.optLong("vipExp",0))>=4?2:1;
    }

    static long progress(long totalExp) {
        if(totalExp<0)return 0;
        for(long cost:NEXT_LEVEL_EXP) {
            if(totalExp<cost)return totalExp;
            totalExp-=cost;
        }
        return 0;
    }

    /** Native ShopBuy applies Loots, then overwrites C.A.P.H from ExtraInfo. */
    static byte[] withBuyResultExtra(byte[] buyResult,JSONObject state)throws IOException {
        long total=state.optLong("vipExp",0),points=state.optLong("vipPoint",0);
        // Actionmod.ExtraInfo.VipExtra=100; Vipmod.VipExtra fields 1..5.
        // The account stores cumulative score; the wire stores level progress.
        ProtoWire vip=new ProtoWire().set(1,0).set(2,0)
            .set(3,level(total)).set(4,Math.toIntExact(progress(total)))
            .set(5,Math.toIntExact(points));
        return ProtoWire.parse(buyResult)
            .set(4,new ProtoWire().set(100,vip.bytes()).bytes()).bytes();
    }

    private static void requireRole(JSONObject state,Map<String,String> args)throws Invalid {
        if(!state.optBoolean("roleCreated",false) || state.optLong("legacyRoleId",0)<1)
            throw new Invalid("Role required for CAPH");
        String role=args.get("roleid");
        if(role!=null && !role.equals(Long.toString(state.optLong("legacyRoleId",0))))
            throw new Invalid("CAPH role does not belong to account");
    }

    private static String claimDay(int level) {
        return level==2?"vipGift2ClaimDay":"vipGift5ClaimDay";
    }

    private static boolean claimedToday(JSONObject state,int level,long today) {
        return state.optLong(claimDay(level),Long.MIN_VALUE)==today;
    }

    /** Vipmod.VipInstance; histories remain empty until exact daily sources exist. */
    static byte[] info(JSONObject state,Map<String,String> args,long now)throws Exception {
        requireRole(state,args);
        long today=LocalDaily.day(now);
        return new ProtoWire().set(2,claimedToday(state,2,today)?1:0)
            .set(3,claimedToday(state,5,today)?1:0).bytes();
    }

    private static ProtoWire reward(int level) {
        ProtoWire result=new ProtoWire();
        // Original dictionary.tsv 11001/11004 gives these guaranteed rewards.
        // The optional coin/gem/tarot chance and amounts are server-side data
        // missing from the preserved APK and must not be guessed.
        long item=level==2?40330099L:40340009L;
        result.add(1,new ProtoWire().set(1,3).set(2,item).set(4,1).bytes());
        if(level==5)
            result.add(1,new ProtoWire().set(1,13).set(3,10000).set(4,10000).bytes());
        return result;
    }

    static Action respond(JSONObject next,JSONObject catalog,String path,
                          Map<String,String> args,long now)throws Exception {
        boolean expired=refresh(next,now);
        requireRole(next,args);
        if(path.equals("/vip/info"))return new Action(info(next,args,now),expired);
        int required=path.equals("/vip/gift2")?2:path.equals("/vip/gift5")?5:-1;
        if(required<0)throw new Invalid("Unknown CAPH route");
        if(level(next.optLong("vipExp",0))<required)
            throw new Conflict("CAPH level too low");
        long today=LocalDaily.day(now);
        ProtoWire loot=reward(required);
        // A retried tap gets the same receipt without receiving a second copy.
        if(claimedToday(next,required,today))return new Action(loot.bytes(),expired);
        if(catalog==null)throw new Invalid("CAPH reward catalog unavailable");
        LocalEconomy.init(next,catalog);
        long item=required==2?40330099L:40340009L;
        LocalEconomy.grantItemReward(next,catalog,new JSONObject()
            .put("type",3).put("id",item).put("value",0).put("count",1),1);
        if(required==5)
            LocalEconomy.grantItemReward(next,catalog,new JSONObject()
                .put("type",13).put("id",0).put("value",10000).put("count",0),1);
        next.put(claimDay(required),today);
        return new Action(loot.bytes(),true);
    }
}
