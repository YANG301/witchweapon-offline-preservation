package com.codex.witchweapon;

import java.util.Collections;
import org.json.JSONObject;

public final class StaminaPurchaseSelfTest {
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static JSONObject role(long stamina,long diamonds)throws Exception{
        return new JSONObject().put("roleCreated",true).put("legacyRoleId",17)
            .put("stamina",stamina).put("rmb",diamonds);
    }
    public static void main(String[] args)throws Exception{
        long day=LocalDaily.day(0);
        long now=10000;
        JSONObject state=role(50,1000);
        check(StaminaPurchase.apply(state,Collections.<String,String>emptyMap(),now),"First purchase rejected");
        check(state.getLong("stamina")==170&&state.getLong("rmb")==985&&
            state.getInt("staminaPurchaseUsed")==1,"First original price or grant changed");
        check(!StaminaPurchase.apply(state,Collections.<String,String>emptyMap(),now+1),
            "Rapid repeated request charged twice");
        check(state.getLong("stamina")==170&&state.getLong("rmb")==985,
            "Rapid retry mutated the balance");
        int[] prices={25,35,45,55,65};
        for(int i=0;i<prices.length;i++){
            long before=state.getLong("rmb");
            check(StaminaPurchase.apply(state,Collections.<String,String>emptyMap(),now+3L*(i+1)),
                "Original daily slot "+(i+2)+" rejected");
            check(state.getLong("rmb")==before-prices[i],"Wrong original diamond price");
        }
        check(state.getInt("staminaPurchaseUsed")==6&&state.getLong("stamina")==770,
            "Six purchases did not grant exactly 720 AP");
        try{
            StaminaPurchase.apply(state,Collections.<String,String>emptyMap(),now+30);
            throw new AssertionError("Daily limit bypassed");
        }catch(StaminaPurchase.Conflict expected){}
        long nextDay=(day+1)*86400L-28800L+1;
        check(StaminaPurchase.used(state,nextDay)==0,"China-day counter did not reset");
        check(StaminaPurchase.apply(state,Collections.<String,String>emptyMap(),nextDay),
            "First next-day purchase rejected");
        check(state.getInt("staminaPurchaseUsed")==1,"Next day did not restart at tier one");
        JSONObject broke=role(40,14);
        try{
            StaminaPurchase.apply(broke,Collections.<String,String>emptyMap(),now);
            throw new AssertionError("Insufficient diamonds charged");
        }catch(StaminaPurchase.Conflict expected){}
        check(broke.getLong("stamina")==40&&broke.getLong("rmb")==14,
            "Rejected purchase mutated balances");
        JSONObject full=role(1900,100);
        try{
            StaminaPurchase.apply(full,Collections.<String,String>emptyMap(),now);
            throw new AssertionError("Stamina hard cap bypassed");
        }catch(StaminaPurchase.Conflict expected){}
        check(full.getLong("rmb")==100,"Full storage consumed diamonds");
        System.out.println("StaminaPurchaseSelfTest passed");
    }
}
