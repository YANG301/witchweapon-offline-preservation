package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;

/** Original /level/sweep wire result with account-local, atomic mainline rewards. */
final class StageSweep {
    static final class Result {
        final JSONObject state;
        final byte[] response;
        Result(JSONObject state,byte[] response){this.state=state;this.response=response;}
    }
    private static final int MAX_BATCH=10;
    private static final int MAX_REPLAY_RECORDS=256;
    private static final long GOLD_PER_CLEAR=1000;

    static long positive(Map<String,String> args,String key)throws IOException{
        String raw=args.get(key);
        if(raw==null || !raw.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid sweep "+key);
        try{return Long.parseLong(raw);}
        catch(NumberFormatException ex){throw new IOException("Invalid sweep "+key,ex);}
    }
    static int quantity(Map<String,String> args)throws IOException{
        long count=positive(args,"count");
        if(count>MAX_BATCH)throw new IOException("Sweep count exceeds batch limit");
        return (int)count;
    }
    static String identity(Map<String,String> args)throws Exception{
        String raw=args.get("idempotency");
        if(raw!=null){
            if(raw.length()>128 || !raw.matches("[A-Za-z0-9._:-]+"))
                throw new IOException("Invalid sweep request identity");
            return digest("idempotency\u0000"+raw);
        }
        String time=args.get("time"),sign=args.get("sign");
        if(time!=null && !time.matches("[0-9]{1,19}"))
            throw new IOException("Invalid native sweep time");
        if(sign!=null && !sign.matches("[A-Za-z0-9._~+/=-]{8,512}"))
            throw new IOException("Invalid native sweep sign");
        // NetMsgBase supplies time/sign as shared authentication fields. Two
        // deliberate taps may have the same values, so they are not a nonce.
        // Only a caller-supplied idempotency key can identify a true retry.
        return null;
    }
    static String digest(String text)throws Exception{
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder(64);
        for(byte b:bytes)hex.append(Character.forDigit((b>>>4)&15,16))
                            .append(Character.forDigit(b&15,16));
        return hex.toString();
    }
    private static JSONObject progress(JSONObject state,long stageId)throws Exception{
        JSONObject all=state.optJSONObject("mainlineStages");
        JSONObject item=all==null?null:all.optJSONObject(Long.toString(stageId));
        if(item!=null)return item;
        if(stageId==LocalSave.STAGE && state.optInt("wins",0)>0)
            return new JSONObject().put("wins",state.optInt("wins",0))
                .put("stars",state.optInt("stars",0))
                .put("attempts",state.optInt("attempts",0))
                .put("firstRewardClaimed",true);
        return new JSONObject();
    }
    private static JSONObject writableProgress(JSONObject state,long stageId)throws Exception{
        JSONObject all=state.optJSONObject("mainlineStages");
        if(all==null){all=new JSONObject();state.put("mainlineStages",all);}
        String id=Long.toString(stageId);
        JSONObject item=all.optJSONObject(id);
        if(item==null){item=progress(state,stageId);all.put(id,item);}
        return item;
    }
    static boolean eligible(JSONObject state,StageCatalog stages,JSONObject stage)throws Exception{
        if(stage==null || !stage.optBoolean("supported",false))return false;
        if(!"1".equals(stage.optJSONObject("source").optJSONObject("instance")
            .optString("instance_repeatable","")))return false;
        JSONObject progress=progress(state,stage.getLong("id"));
        // The temporary simple-campaign-v1 encounter has no reliable star
        // score: the original client may report zero even after a real win.
        // Only this catalog profile treats a completed encounter as three
        // stars; reconstructed/original stages still require earned stars.
        boolean threeStars=progress.optInt("stars",0)==3 ||
            stages!=null && stages.openAllMainline() && progress.optInt("wins",0)>0;
        return progress.optInt("wins",0)>0 && threeStars &&
               progress.optBoolean("firstRewardClaimed",true);
    }
    static JSONObject replayLedger(JSONObject state){
        JSONObject ledger=state.optJSONObject("sweepReplay");
        return ledger==null?new JSONObject():ledger;
    }
    static void trim(JSONObject ledger)throws Exception{
        while(ledger.length()>MAX_REPLAY_RECORDS){
            String oldest=null;long at=Long.MAX_VALUE;
            for(java.util.Iterator<String> it=ledger.keys();it.hasNext();){
                String key=it.next();long value=ledger.getJSONObject(key).optLong("at",0);
                if(value<at){at=value;oldest=key;}
            }
            if(oldest==null)break;
            ledger.remove(oldest);
        }
    }
    static Result settle(JSONObject state,StageCatalog stages,JSONObject catalog,
                         Map<String,String> args,long now)throws Exception{
        long chapterId=positive(args,"chapid"),stageId=positive(args,"instanceid");
        int count=quantity(args);
        if(stages==null || !stages.supported(stageId) || stages.chapterOf(stageId)!=chapterId)
            throw new IOException("Sweep stage does not belong to chapter");
        JSONObject stage=stages.stage(stageId);
        String requestIdentity=identity(args);
        String fingerprint=digest(chapterId+"\u0000"+stageId+"\u0000"+count);
        JSONObject prior=requestIdentity==null?null:replayLedger(state).optJSONObject(requestIdentity);
        if(prior!=null){
            if(!fingerprint.equals(prior.optString("fingerprint","")))
                throw new IOException("Conflicting sweep retry");
            return new Result(state,Base64.decode(prior.getString("response"),Base64.DEFAULT));
        }
        if(!state.optBoolean("roleCreated",false) || state.optBoolean("namePending",false))
            throw new IOException("Sweep requires a named role");
        if(state.optBoolean("active",false))throw new IOException("Cannot sweep during battle");
        if(!eligible(state,stages,stage))throw new IOException("Sweep requires a three-star repeatable clear");
        // A manual clear pays the entry charge once and the victory charge
        // once. Sweeping skips combat, not either part of that original price.
        long entry=stage.optLong("staminaEnter",-1);
        long victory=stage.optLong("staminaVictory",-1);
        if(entry<0 || entry>100 || victory<1 || victory>100)
            throw new IOException("Invalid stage stamina cost");
        long unitCost=Math.addExact(entry,victory);
        long totalCost=Math.multiplyExact(unitCost,count);
        long stamina=state.optLong("stamina",200);
        if(stamina<totalCost)throw new IOException("Insufficient stamina for sweep");
        // Match the manual clear's local Gold/role-EXP rule. Instance.txt
        // provides candidate drops but no rates, so listed materials rotate
        // deterministically; first-clear story currency is never repeated.
        long expEach=5L;
        long expTotal=Math.multiplyExact(expEach,count);
        if(expTotal>Integer.MAX_VALUE)throw new IOException("Sweep experience exceeds wire range");
        JSONObject next=new JSONObject(state.toString());
        if(catalog==null)throw new IOException("Sweep item catalog unavailable");
        LocalEconomy.init(next,catalog);
        next.put("stamina",stamina-totalCost);
        next.put("gold",Math.addExact(state.getLong("gold"),Math.multiplyExact(GOLD_PER_CLEAR,count)));
        next.put("exp",Math.addExact(state.getLong("exp"),expTotal));
        JSONObject progress=writableProgress(next,stageId);
        progress.put("sweeps",Math.addExact(progress.optInt("sweeps",0),count));
        progress.put("attempts",Math.addExact(progress.optInt("attempts",0),count));
        next.put("mainlineSweepCount",Math.addExact(next.optInt("mainlineSweepCount",0),count));
        if(stageId==LocalSave.STAGE)
            next.put("attempts",Math.addExact(next.optInt("attempts",0),count));
        ProtoWire result=new ProtoWire().set(3,stamina-totalCost).set(4,expTotal)
            .set(2,new byte[0]);
        long priorClears=Math.addExact(progress(state,stageId).optLong("wins",0),
            progress(state,stageId).optLong("sweeps",0));
        for(int i=0;i<count;i++){
            ProtoWire gold=new ProtoWire().set(1,13).set(3,GOLD_PER_CLEAR)
                .set(4,GOLD_PER_CLEAR);
            ProtoWire drop=MainlineBattleRewards.grantListedDrop(next,catalog,stage,
                Math.addExact(priorClears,i));
            ProtoWire loot=new ProtoWire().add(1,gold.bytes()).add(1,drop.bytes())
                .set(2,new byte[0]);
            result.add(1,loot.bytes());
        }
        byte[] response=result.bytes();
        if(requestIdentity!=null){
            JSONObject ledger=replayLedger(next);
            ledger.put(requestIdentity,new JSONObject().put("fingerprint",fingerprint)
                .put("response",Base64.encodeToString(response,Base64.NO_WRAP))
                .put("at",now));
            trim(ledger);
            next.put("sweepReplay",ledger);
        }
        next.put("lastSweepAt",now);
        return new Result(next,response);
    }
}
