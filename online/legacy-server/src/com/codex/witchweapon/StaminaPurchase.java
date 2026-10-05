package com.codex.witchweapon;

import java.io.IOException;
import java.util.Map;
import org.json.JSONObject;

/** Diamond-to-stamina exchange from the original CN diamond.txt table. */
final class StaminaPurchase {
    // diamond.txt (channel 25): ten price rows exist, but the original
    // STAMINA_EVERYDAY constant permits six purchases per China calendar day.
    private static final int[] PRICE={15,25,35,45,55,65};
    private static final int STAMINA_PER_PURCHASE=120;
    private static final int HARD_CAP=2000; // constant.txt STAMINA_CAP_INSIDE

    static final class Invalid extends IOException { Invalid(String text){super(text);} }
    static final class Conflict extends IOException { Conflict(String text){super(text);} }

    private StaminaPurchase(){}

    static boolean handles(String path) {
        return path.equals("/resource/buy/stamina") || path.equals("/time/getStamina") ||
            path.equals("/game/resource/buy/stamina") || path.equals("/game/time/getStamina");
    }

    static boolean buy(String path) {
        return path.equals("/resource/buy/stamina") || path.equals("/game/resource/buy/stamina");
    }

    static int used(JSONObject state,long now)throws Invalid {
        if(state.optLong("staminaPurchaseDay",Long.MIN_VALUE)!=LocalDaily.day(now))return 0;
        int result=state.optInt("staminaPurchaseUsed",-1);
        if(result<0||result>PRICE.length)throw new Invalid("Invalid stamina purchase ledger");
        return result;
    }

    static boolean apply(JSONObject state,Map<String,String> args,long now)throws Exception {
        if(!state.optBoolean("roleCreated",false)||state.optLong("legacyRoleId",0)<1)
            throw new Invalid("Role required for stamina purchase");
        String role=args.get("roleid");
        if(role!=null&&!role.equals(Long.toString(state.getLong("legacyRoleId"))))
            throw new Invalid("Stamina role does not belong to account");
        // The native message sends no request ID. Repeated taps/retries during
        // one HTTP round trip must not buy the same grant twice.
        long last=state.optLong("staminaPurchaseLastAt",0);
        if(last>0&&now>=last&&now-last<=2)return false;
        int bought=used(state,now);
        if(bought>=PRICE.length)throw new Conflict("Daily stamina purchase limit");
        long diamonds=state.optLong("rmb",0),stamina=state.optLong("stamina",0);
        if(diamonds<PRICE[bought])throw new Conflict("Insufficient diamonds");
        if(stamina<0||stamina>HARD_CAP-STAMINA_PER_PURCHASE)
            throw new Conflict("Stamina storage is full");
        state.put("rmb",diamonds-PRICE[bought]);
        state.put("stamina",stamina+STAMINA_PER_PURCHASE);
        state.put("staminaPurchaseDay",LocalDaily.day(now));
        state.put("staminaPurchaseUsed",bought+1);
        state.put("staminaPurchaseLastAt",now);
        return true;
    }
}
