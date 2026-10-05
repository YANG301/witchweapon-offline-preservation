package com.codex.witchweapon;

import java.io.IOException;
import java.util.Map;
import org.json.JSONObject;

/** Original channel-25 Activity.csv base 11, rows 11001..11009. */
final class WelfareReturn {
    private static final long[] YUAN = {214, 520, 876, 1024, 2333, 3333, 5563, 6666, 8888};
    // Each row is {type, item ID, value, count}, copied from the original
    // activity reward_type/id/value/num columns in display order.
    private static final long[][][] REWARDS = {
        {{13,0,20000,0}, {3,40240039,0,8}},
        {{3,40350003,0,3}, {99,0,20,0}},
        {{84,0,2,0}, {3,40350003,0,3}, {3,40340001,0,5}},
        {{99,0,100,0}, {3,40240039,0,10}, {3,40340001,0,10}},
        {{81,0,3,0}, {3,40350003,0,10}, {99,0,100,0}},
        {{3,40340001,0,15}, {13,0,50000,0}, {99,0,300,0}},
        {{99,0,300,0}, {3,40350003,0,20}, {3,40240039,0,30}},
        {{87,0,4,0}, {3,40350003,0,30}, {3,40340001,0,20}},
        {{80,0,6,0}, {99,0,1000,0}, {3,40340001,0,30}}
    };
    private static final String CLAIM_KEY = "welfareReturnClaimedMask";

    private WelfareReturn() { }

    static long eligibleMask(long cents) {
        long mask=0;
        for(int i=0;i<YUAN.length;i++)
            if(cents>=YUAN[i]*100L)mask|=1L<<i;
        return mask;
    }

    static long claimedMask(JSONObject state) {
        return state.optLong(CLAIM_KEY,0L)&((1L<<YUAN.length)-1L);
    }

    static byte[] claim(JSONObject state,JSONObject catalog,Map<String,String> args) throws Exception {
        LocalDaily.requireRole(state,args);
        if(!String.valueOf(ActivityBanner.WELFARE_RETURN_ID).equals(args.get("baseid")))
            throw new IOException("Wrong welfare-return activity");
        String raw=args.get("serial");
        if(raw==null||!raw.matches("[1-9]"))throw new IOException("Invalid welfare-return tier");
        int index=Integer.parseInt(raw)-1;
        if(index>=YUAN.length)throw new IOException("Invalid welfare-return tier");
        long bit=1L<<index,claimed=claimedMask(state);
        if((eligibleMask(Math.max(0L,state.optLong("virtualPurchaseCents",0L)))&bit)==0)
            throw new IOException("Welfare-return tier not reached");
        if((claimed&bit)==0){
            if(index>0&&(claimed&((1L<<index)-1L))!=((1L<<index)-1L))
                throw new IOException("Claim previous welfare-return tier first");
            LocalEconomy.init(state,catalog);
            for(long[] reward:REWARDS[index])
                LocalEconomy.grantItemReward(state,catalog,
                    new JSONObject().put("type",reward[0]).put("id",reward[1])
                        .put("value",reward[2]).put("count",reward[3]),1);
            state.put(CLAIM_KEY,claimed|bit);
            state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision"),1L));
        }
        // The preserved LuaNetProxy.Callback consumes a lootmod.LootResult.
        // A retry receives the same visual receipt without granting twice.
        ProtoWire result=new ProtoWire();
        for(long[] reward:REWARDS[index]) {
            ProtoWire object=new ProtoWire().set(1,reward[0]);
            if(reward[1]>0)object.set(2,reward[1]);
            if(reward[2]>0)object.set(3,reward[2]);
            if(reward[3]>0)object.set(4,reward[3]);
            result.add(1,object.bytes());
        }
        return result.bytes();
    }
}
