package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** The six original Daily Inspection groups (the furnace has its own route). */
final class DailyBattle {
    static final class Settlement {
        final JSONObject state;
        final byte[] response;
        Settlement(JSONObject state,byte[] response){this.state=state;this.response=response;}
    }

    private static final long[] SET_IDS={3020001L,3020002L,3020003L,3020004L,3020005L,3020006L};
    private static final DailyBattle BUNDLED=load();
    private final Map<Long,JSONObject> stages=new LinkedHashMap<Long,JSONObject>();
    private final Map<Long,List<Long>> groups=new LinkedHashMap<Long,List<Long>>();

    private static DailyBattle load(){
        try(InputStream in=DailyBattle.class.getResourceAsStream("/daily_stage_catalog.json")){
            if(in==null)throw new IOException("Bundled daily catalog missing");
            ByteArrayOutputStream output=new ByteArrayOutputStream();
            byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1){
                if(output.size()+n>1024*1024)throw new IOException("Daily catalog exceeds limit");
                output.write(buffer,0,n);
            }
            return new DailyBattle(new JSONObject(new String(output.toByteArray(),StandardCharsets.UTF_8)));
        }catch(Exception ex){throw new IllegalStateException("Invalid daily catalog",ex);}
    }

    static DailyBattle bundled(){return BUNDLED;}

    DailyBattle(JSONObject data)throws Exception{
        if(data.getInt("schemaVersion")!=1 ||
                !"one-room-local-reconstruction".equals(data.getString("mode")))
            throw new IOException("Unknown daily battle profile");
        JSONObject entries=data.getJSONObject("stages");
        if(entries.length()!=40)throw new IOException("Daily catalog must contain forty stages");
        for(long setId:SET_IDS)groups.put(setId,new ArrayList<Long>());
        for(java.util.Iterator<String> it=entries.keys();it.hasNext();){
            String key=it.next();
            if(!key.matches("312000[1-6]00[1-7]"))throw new IOException("Invalid daily stage ID");
            long stageId=Long.parseLong(key);
            JSONObject stage=entries.getJSONObject(key);
            long setId=stage.getLong("setId");
            if(stage.getLong("id")!=stageId || !groups.containsKey(setId) ||
                    stageId/1000!=setId+100000L ||
                    stage.getInt("difficulty")!=stageId%1000 ||
                    stage.getInt("staminaOnWin")!=10 ||
                    stage.getLong("rewardItem")<1)
                throw new IOException("Invalid daily stage metadata");
            int limit=stage.getInt("dailyLimit");
            if(limit!=(setId<=3020004L?2:3))throw new IOException("Invalid daily attempt limit");
            JSONArray weekdays=stage.getJSONArray("weekdays");
            if(weekdays.length()<1 || weekdays.length()>7)throw new IOException("Invalid daily weekdays");
            JSONObject battle=stage.getJSONObject("combatJson");
            if(!key.equals(battle.getJSONObject("EnemyLayer").getString("levelID")))
                throw new IOException("Daily combat level mismatch");
            if(Base64.decode(stage.getString("combatMobInfo"),Base64.DEFAULT).length==0)
                throw new IOException("Daily combat mob data missing");
            stages.put(stageId,stage);
            groups.get(setId).add(stageId);
        }
        for(long setId:SET_IDS){
            List<Long> ids=groups.get(setId);Collections.sort(ids);
            int count=setId<=3020004L?7:6;
            if(ids.size()!=count)throw new IOException("Incomplete daily stage group");
            for(int i=0;i<count;i++)if(ids.get(i)!=3120000000L+(setId-3020000L)*1000L+i+1)
                throw new IOException("Missing daily stage difficulty");
        }
    }

    boolean supports(long id){return stages.containsKey(id);}

    void install(JSONObject responses)throws Exception{
        for(Map.Entry<Long,JSONObject> pair:stages.entrySet()){
            String suffix="#"+pair.getKey();
            JSONObject stage=pair.getValue();
            responses.put("/combat/mob/json"+suffix,new JSONObject()
                .put("type","application/json")
                .put("body",stage.getJSONObject("combatJson").toString()));
            responses.put("/combat/mob/info"+suffix,new JSONObject()
                .put("type","application/octet-stream")
                .put("base64",stage.getString("combatMobInfo")));
        }
    }

    static long chinaDay(long epochSeconds){return Math.floorDiv(epochSeconds+28800L,86400L);}
    private static int weekday(long epochSeconds){return (int)Math.floorMod(chinaDay(epochSeconds)+3L,7L)+1;}
    private static int attempts(JSONObject state,long setId,long today){
        JSONObject daily=state.optJSONObject("dailyBattleAttempts");
        if(daily==null || daily.optLong("day",Long.MIN_VALUE)!=today)return 0;
        return daily.optInt(String.valueOf(setId),0);
    }
    /** Level.BattleCount is per difficulty. The native daily panel adds all
     *  difficulties in a set to obtain its remaining shared attempts. */
    private long fallbackStage(JSONObject state,long setId){
        long recent=state.optLong("dailyBattleStage",0);
        JSONObject stage=stages.get(recent);
        return stage!=null && stage.optLong("setId",0)==setId
            ?recent:groups.get(setId).get(0);
    }
    private JSONObject stageAttempts(JSONObject state,long today)throws Exception{
        JSONObject previous=state.optJSONObject("dailyBattleStageAttempts");
        if(previous!=null && previous.optLong("day",Long.MIN_VALUE)==today)
            return new JSONObject(previous.toString());
        JSONObject migrated=new JSONObject().put("day",today);
        // Saves written before per-level accounting only recorded the group
        // total. Attribute that day's existing plays to the most recent
        // stage when known; otherwise use the first difficulty in the set.
        for(long setId:SET_IDS){
            int used=Math.max(0,attempts(state,setId,today));
            if(used>0)migrated.put(String.valueOf(fallbackStage(state,setId)),used);
        }
        return migrated;
    }
    private int battleCount(JSONObject state,long stageId,long today){
        JSONObject stage=stages.get(stageId);
        if(stage==null)return 0;
        long setId=stage.optLong("setId",0);
        // Old saves can contain a group total above today's limit. Preserve
        // that value for start validation, but never publish a count that
        // makes the native panel display a negative remaining balance.
        int total=Math.min(stage.optInt("dailyLimit",0),
            Math.max(0,attempts(state,setId,today)));
        if(total==0)return 0;
        JSONObject perStage=state.optJSONObject("dailyBattleStageAttempts");
        if(perStage==null || perStage.optLong("day",Long.MIN_VALUE)!=today)
            return fallbackStage(state,setId)==stageId?total:0;
        int remaining=total,result=0;
        for(long id:groups.get(setId)){
            int value=Math.max(0,perStage.optInt(String.valueOf(id),0));
            int visible=Math.min(value,remaining);
            if(id==stageId)result=visible;
            remaining-=visible;
        }
        if(remaining>0 && fallbackStage(state,setId)==stageId)result+=remaining;
        return result;
    }
    private static JSONObject stageRecord(JSONObject state,long stageId){
        JSONObject all=state.optJSONObject("dailyBattleStages");
        JSONObject result=all==null?null:all.optJSONObject(String.valueOf(stageId));
        return result==null?new JSONObject():result;
    }
    private boolean open(JSONObject state,JSONObject stage,long now,boolean openAccess)throws Exception{
        long stageId=stage.getLong("id"),setId=stage.getLong("setId");
        if(attempts(state,setId,chinaDay(now))>=stage.getInt("dailyLimit"))return false;
        if(openAccess)return true;
        boolean dateOpen=false;
        JSONArray weekdays=stage.getJSONArray("weekdays");
        for(int i=0;i<weekdays.length();i++)if(weekdays.getInt(i)==weekday(now))dateOpen=true;
        if(!dateOpen)return false;
        if(stage.getInt("difficulty")<=1)return true;
        return stageRecord(state,stageId-1).optInt("wins",0)>0;
    }

    /** Appends the six daily chapters absent from the author's fixed seed. */
    byte[] progress(byte[] seed,JSONObject state,long now)throws Exception{
        return progress(seed,state,now,false);
    }
    byte[] progress(byte[] seed,JSONObject state,long now,boolean openAccess)throws Exception{
        ProtoWire all=ProtoWire.parse(seed);
        for(java.util.Iterator<ProtoWire.Field> it=all.fields.iterator();it.hasNext();){
            ProtoWire.Field field=it.next();
            if(field.number!=1 || field.type!=2)continue;
            long chapter=ProtoWire.parse(field.data).number(1,0);
            if(groups.containsKey(chapter))it.remove();
        }
        for(long setId:SET_IDS){
            ProtoWire chapter=new ProtoWire().set(1,setId).set(3,1);
            for(long stageId:groups.get(setId)){
                JSONObject stage=stages.get(stageId),record=stageRecord(state,stageId);
                boolean passed=record.optInt("wins",0)>0;
                int stars=record.optInt("stars",0);
                chapter.add(2,new ProtoWire().set(1,stageId)
                    .set(2,passed?1:0).set(3,stars==3?1:0)
                    .set(4,open(state,stage,now,openAccess)?1:0)
                    .set(6,battleCount(state,stageId,chinaDay(now)))
                    .set(7,passed&&stars==3?1:0).bytes());
            }
            all.add(1,chapter.bytes());
        }
        return all.bytes();
    }

    /** Returns the same object for an idempotent retry, or a new save snapshot. */
    JSONObject begin(JSONObject state,long stageId,Map<String,String> args,long now)throws Exception{
        return begin(state,stageId,args,now,false);
    }
    JSONObject begin(JSONObject state,long stageId,Map<String,String> args,long now,
                     boolean openAccess)throws Exception{
        JSONObject stage=stages.get(stageId);
        if(stage==null)throw new IOException("Daily stage unavailable");
        if(!state.optBoolean("roleCreated",false))throw new IOException("Game role required");
        String key=args.get("idempotency");
        if(key==null || key.isEmpty() || key.length()>128)throw new IOException("Daily start identity required");
        long today=chinaDay(now);
        if(stageId==state.optLong("dailyBattleStage",0) &&
                today==state.optLong("dailyBattleDay",Long.MIN_VALUE) &&
                key.equals(state.optString("dailyBattleKey","")))return state;
        if(!open(state,stage,now,openAccess))throw new IOException("Daily stage closed or attempt limit reached");
        if(state.optLong("stamina",200)<stage.getInt("staminaOnWin"))
            throw new IOException("Insufficient stamina for daily battle");
        JSONObject next=new JSONObject(state.toString());
        JSONObject count=next.optJSONObject("dailyBattleAttempts");
        if(count==null || count.optLong("day",Long.MIN_VALUE)!=today)
            count=new JSONObject().put("day",today);
        long setId=stage.getLong("setId");
        JSONObject perStage=stageAttempts(state,today);
        String stageKey=String.valueOf(stageId);
        perStage.put(stageKey,Math.addExact(perStage.optInt(stageKey,0),1));
        count.put(String.valueOf(setId),count.optInt(String.valueOf(setId),0)+1);
        next.put("dailyBattleAttempts",count);
        next.put("dailyBattleStageAttempts",perStage);
        next.put("dailyBattleDay",today).put("dailyBattleStage",stageId).put("dailyBattleKey",key);
        next.put("active",true).put("activeStage",stageId).put("startKey",key)
            .put("battleStartedAt",now);
        next.remove("dailyBattleResponse");
        return next;
    }

    private static boolean result(Map<String,String> args)throws IOException{
        String value=null;
        for(String field:new String[]{"pass","isWin","iswin","win"})if(args.containsKey(field)){
            String candidate=args.get(field);
            if(value!=null && !value.equalsIgnoreCase(candidate))throw new IOException("Conflicting daily result");
            value=candidate;
        }
        if("1".equals(value) || "true".equalsIgnoreCase(value))return true;
        if("0".equals(value) || "false".equalsIgnoreCase(value))return false;
        throw new IOException("Missing or invalid daily result");
    }
    private static int stars(Map<String,String> args,boolean win)throws IOException{
        String raw=args.containsKey("stars")?args.get("stars"):args.get("starNum");
        if(raw==null)return win?3:0;
        try{int value=Integer.parseInt(raw);if(value>=0 && value<=3)return value;}
        catch(NumberFormatException ignored){}
        throw new IOException("Invalid daily stars");
    }

    Settlement settle(JSONObject state,JSONObject itemCatalog,Map<String,String> args,long now)throws Exception{
        long stageId=state.optLong("dailyBattleStage",0);
        JSONObject stage=stages.get(stageId);
        if(stage==null)throw new IOException("No daily battle to settle");
        if(args.containsKey("instanceid") && !String.valueOf(stageId).equals(args.get("instanceid")))
            throw new IOException("Wrong daily settlement stage");
        if(state.has("dailyBattleResponse") && !state.optBoolean("active",false))
            return new Settlement(state,Base64.decode(state.getString("dailyBattleResponse"),Base64.DEFAULT));
        if(!state.optBoolean("active",false) || state.optLong("activeStage",0)!=stageId)
            throw new IOException("Daily battle is not active");
        boolean won=result(args);
        int starCount=stars(args,won);
        JSONObject next=new JSONObject(state.toString());
        next.put("active",false).put("lastSettlementAt",now);
        long stamina=next.optLong("stamina",200);
        ProtoWire outcome=new ProtoWire().set(1,stamina);
        if(won){
            long price=stage.getInt("staminaOnWin");
            if(stamina<price)throw new IOException("Insufficient stamina at settlement");
            next.put("stamina",stamina-price);
            outcome.set(1,stamina-price);
            JSONObject all=next.optJSONObject("dailyBattleStages");
            if(all==null){all=new JSONObject();next.put("dailyBattleStages",all);}
            JSONObject progress=all.optJSONObject(String.valueOf(stageId));
            if(progress==null){progress=new JSONObject();all.put(String.valueOf(stageId),progress);}
            progress.put("wins",progress.optInt("wins",0)+1);
            progress.put("stars",Math.max(progress.optInt("stars",0),starCount));
            LocalEconomy.init(next,itemCatalog);
            long reward=stage.getLong("rewardItem");
            LocalEconomy.grantItemReward(next,itemCatalog,new JSONObject()
                .put("type",3).put("id",reward).put("value",1).put("count",0),1);
            next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
            outcome.add(3,new ProtoWire().set(1,3).set(2,reward).set(4,1).bytes());
            next.put("exp",Math.addExact(next.optLong("exp",0),5));
            outcome.set(5,5);
        }
        if(won)StaminaRecovery.reconcileMutation(next,StaminaRecovery.level(next,itemCatalog),now);
        ProgressionTasks.recordBattleKills(next,args);
        outcome.set(2,StaminaRecovery.protocolTime(next,now));
        byte[] response=outcome.bytes();
        next.put("dailyBattleResponse",Base64.encodeToString(response,Base64.NO_WRAP));
        return new Settlement(next,response);
    }

    /** The native SweepPanel uses /level/sweep for daily and mainline alike. */
    Settlement sweep(JSONObject state,JSONObject itemCatalog,Map<String,String> args,long now,
                     boolean openAccess)throws Exception{
        long setId=StageSweep.positive(args,"chapid");
        long stageId=StageSweep.positive(args,"instanceid");
        int count=StageSweep.quantity(args);
        JSONObject stage=stages.get(stageId);
        if(stage==null || stage.getLong("setId")!=setId)
            throw new IOException("Daily sweep stage does not belong to chapter");
        String requestIdentity=StageSweep.identity(args);
        String fingerprint=StageSweep.digest(setId+"\u0000"+stageId+"\u0000"+count);
        JSONObject prior=requestIdentity==null?null:
            StageSweep.replayLedger(state).optJSONObject(requestIdentity);
        if(prior!=null){
            if(!fingerprint.equals(prior.optString("fingerprint","")))
                throw new IOException("Conflicting sweep retry");
            return new Settlement(state,Base64.decode(prior.getString("response"),Base64.DEFAULT));
        }
        if(!state.optBoolean("roleCreated",false) || state.optBoolean("namePending",false))
            throw new IOException("Daily sweep requires a named role");
        if(state.optBoolean("active",false))throw new IOException("Cannot sweep during battle");
        JSONObject cleared=stageRecord(state,stageId);
        if(cleared.optInt("wins",0)<1 || cleared.optInt("stars",0)!=3)
            throw new IOException("Daily sweep requires a three-star clear");
        long today=chinaDay(now);
        int used=Math.max(0,attempts(state,setId,today));
        int limit=stage.getInt("dailyLimit");
        if(!open(state,stage,now,openAccess) || used>limit-count)
            throw new IOException("Daily sweep attempt limit reached or stage closed");
        long stamina=state.optLong("stamina",200);
        long cost=Math.multiplyExact(stage.getLong("staminaOnWin"),count);
        if(stamina<cost)throw new IOException("Insufficient stamina for daily sweep");
        if(itemCatalog==null)throw new IOException("Daily sweep item catalog unavailable");
        JSONObject next=new JSONObject(state.toString());
        LocalEconomy.init(next,itemCatalog);
        long reward=stage.getLong("rewardItem");
        ProtoWire response=new ProtoWire().set(3,stamina-cost).set(4,5L*count)
            .set(2,new byte[0]);
        for(int i=0;i<count;i++){
            LocalEconomy.grantItemReward(next,itemCatalog,new JSONObject()
                .put("type",3).put("id",reward).put("value",1).put("count",0),1);
            ProtoWire item=new ProtoWire().set(1,3).set(2,reward).set(3,1).set(4,1);
            response.add(1,new ProtoWire().add(1,item.bytes())
                .set(2,new byte[0]).bytes());
        }
        next.put("stamina",stamina-cost);
        next.put("exp",Math.addExact(state.optLong("exp",0),5L*count));
        next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
        JSONObject group=next.optJSONObject("dailyBattleAttempts");
        if(group==null || group.optLong("day",Long.MIN_VALUE)!=today)
            group=new JSONObject().put("day",today);
        group.put(String.valueOf(setId),used+count);
        next.put("dailyBattleAttempts",group);
        JSONObject perStage=stageAttempts(state,today);
        String key=String.valueOf(stageId);
        perStage.put(key,Math.addExact(perStage.optInt(key,0),count));
        next.put("dailyBattleStageAttempts",perStage);
        JSONObject all=next.optJSONObject("dailyBattleStages");
        all.getJSONObject(key).put("sweeps",Math.addExact(cleared.optInt("sweeps",0),count));
        byte[] encoded=response.bytes();
        if(requestIdentity!=null){
            JSONObject ledger=StageSweep.replayLedger(next);
            ledger.put(requestIdentity,new JSONObject().put("fingerprint",fingerprint)
                .put("response",Base64.encodeToString(encoded,Base64.NO_WRAP))
                .put("at",now));
            StageSweep.trim(ledger);
            next.put("sweepReplay",ledger);
        }
        next.put("lastSweepAt",now);
        StaminaRecovery.reconcileMutation(next,StaminaRecovery.level(next,itemCatalog),now);
        return new Settlement(next,encoded);
    }
}
