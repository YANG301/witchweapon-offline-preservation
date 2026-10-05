package com.codex.witchweapon;

import java.io.IOException;
import org.json.JSONObject;

/** Lazy, account-local AP regeneration; no per-account timers or background jobs. */
final class StaminaRecovery {
    // Original clientexel/constant.txt: STAMINA_RESTORE_PERIOD=300 seconds.
    static final long PERIOD_SECONDS=300;
    // Original characterlevelinfo.txt: 60,62,...,100 at levels 1..21,
    // then 101,...,179 at levels 22..100. This formula matches all 100 rows.
    private static final String ANCHOR="staminaRegenAt";
    private static final String CAP="staminaRegenCap";
    private StaminaRecovery(){}

    static int capAtLevel(int level){
        int safe=Math.max(1,Math.min(100,level));
        return safe<=21 ? 60+2*(safe-1) : 100+(safe-21);
    }

    static int level(JSONObject save,JSONObject catalog)throws Exception{
        if(catalog!=null)return WeaponFurnace.roleLevel(save,catalog);
        return save.optInt("starterProfile",0)==1?1:5;
    }

    /** Mutates only when a capacity/clock/value change must be persisted. */
    static boolean advance(JSONObject save,int level,long now)throws Exception{
        return advanceAtCap(save,capAtLevel(level),now);
    }

    static boolean advanceSaved(JSONObject save,long now)throws Exception{
        int fallback=capAtLevel(save.optInt("starterProfile",0)==1?1:5);
        return advanceAtCap(save,save.optInt(CAP,fallback),now);
    }

    /** Reconcile a reward/spend in the same commit without minting AP after its response was built. */
    static void reconcileMutation(JSONObject save,int level,long now)throws Exception{
        int cap=capAtLevel(level);
        long stamina=save.optLong("stamina",200);
        long anchor=save.optLong(ANCHOR,0);
        if(stamina<0 || anchor<0 || now<0)throw new IOException("Invalid stamina state");
        save.put(CAP,cap);
        if(stamina>=cap){
            if(anchor!=0)save.put(ANCHOR,0);
        }else if(anchor==0)save.put(ANCHOR,now);
    }

    private static boolean advanceAtCap(JSONObject save,int cap,long now)throws Exception{
        if(now<0)throw new IOException("Invalid server time");
        if(cap<1 || cap>179)throw new IOException("Invalid stamina capacity");
        long stamina=save.optLong("stamina",200);
        if(stamina<0)throw new IOException("Invalid stamina balance");
        long anchor=save.optLong(ANCHOR,0);
        if(anchor<0)throw new IOException("Invalid stamina recovery clock");
        if(stamina>=cap && anchor==0 && !save.has(CAP))
            return false; // Untouched over-cap legacy/new saves need no migration write.
        boolean changed=false;
        if(save.optInt(CAP,0)!=cap){save.put(CAP,cap);changed=true;}

        if(stamina>=cap){
            // Earned, purchased and starter AP above the natural cap is kept.
            // Time spent full cannot be banked for later expenditure.
            if(anchor!=0){save.put(ANCHOR,0);changed=true;}
            return changed;
        }
        if(anchor==0){
            // Legacy saves have no trustworthy depletion time. Start now.
            save.put(ANCHOR,now);return true;
        }
        if(now<=anchor)return changed; // Ignore clock rollback; never mint AP.
        long earned=(now-anchor)/PERIOD_SECONDS;
        if(earned==0)return changed;
        long applied=Math.min((long)cap-stamina,earned);
        save.put("stamina",stamina+applied);
        save.put(ANCHOR,stamina+applied>=cap?0:anchor+applied*PERIOD_SECONDS);
        return true;
    }

    /** Keep the fractional interval when spending below cap; start at crossing. */
    static void beforeCommit(JSONObject previous,JSONObject next,long now)throws Exception{
        long stamina=next.optLong("stamina",200);
        if(stamina<0)throw new IOException("Invalid stamina balance");
        long old=previous==null?stamina:previous.optLong("stamina",200);
        long oldAnchor=previous==null?0:previous.optLong(ANCHOR,0);
        long anchor=next.optLong(ANCHOR,0);
        if(anchor<0)throw new IOException("Invalid stamina recovery clock");
        if(stamina==old || anchor!=oldAnchor)return;
        int cap=next.optInt(CAP,capAtLevel(next.optInt("starterProfile",0)==1?1:5));
        if(cap<1 || cap>179)throw new IOException("Invalid stamina capacity");
        if(stamina>=cap)next.put(ANCHOR,0);
        else if(old>=cap || anchor==0)next.put(ANCHOR,now);
    }

    /** Protocol timestamp for the next-point countdown in the original UI. */
    static long protocolTime(JSONObject save,long now){
        long anchor=save.optLong(ANCHOR,0);
        return anchor>0 && anchor<=now?anchor:now;
    }
}
