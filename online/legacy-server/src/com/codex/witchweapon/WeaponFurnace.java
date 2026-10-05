package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.ArrayList;
import java.util.Collections;
import java.security.SecureRandom;

/** The five original 3020007 E.M.E Aggregator stages, with local combat/reward balance. */
final class WeaponFurnace {
    static final long CHAPTER=3020007L;
    private static final long FIRST=3120007001L;
    private static final long LAST=3120007005L;
    private static final long DAY_OFFSET=8L*3600L;
    private final JSONObject stages;
    private final JSONObject coreItems;

    static final class Settlement {
        final JSONObject next;
        final byte[] response;
        Settlement(JSONObject next,byte[] response){this.next=next;this.response=response;}
    }

    // diamond.txt rows 2-5: the first through fourth paid random material.
    private static final int[] EXTRA_MATERIAL_PRICES={5,10,10,15};
    private static final int SPECIFIED_CORE_AMOUNT=2;
    private static final int RANDOM_CORE_CHOICES=1+EXTRA_MATERIAL_PRICES.length;
    private static final SecureRandom RANDOM=new SecureRandom();
    private static final int MAX_CHOICE_REPLAY_KEYS=128;

    static WeaponFurnace bundled() throws Exception {
        InputStream in=WeaponFurnace.class.getResourceAsStream("/weapon_furnace_catalog.json");
        if(in==null)throw new IOException("Bundled weapon furnace catalog missing");
        try {
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1){
                if(out.size()+n>256*1024)throw new IOException("Weapon furnace catalog too large");
                out.write(buffer,0,n);
            }
            return new WeaponFurnace(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
        }finally{in.close();}
    }

    WeaponFurnace(JSONObject data) throws Exception {
        if(data.optInt("schemaVersion",0)!=1)throw new IOException("Unsupported furnace catalog schema");
        stages=data.getJSONObject("stages");coreItems=data.getJSONObject("weaponCoreItems");
        if(stages.length()!=5 || coreItems.length()<50)
            throw new IOException("Incomplete original furnace source table");
        for(long id=FIRST;id<=LAST;id++){
            JSONObject stage=stages.getJSONObject(Long.toString(id));
            if(stage.getLong("id")!=id || stage.getLong("chapterId")!=CHAPTER ||
                stage.getInt("recommendedLevel")!=25+(int)(id-FIRST)*10 ||
                stage.getInt("staminaVictory")!=10 || stage.getInt("staminaEnter")!=0 ||
                !Long.toString(id).equals(stage.getJSONObject("combatJson")
                    .getJSONObject("EnemyLayer").getString("levelID")))
                throw new IOException("Invalid original furnace stage identity");
            if(stage.getJSONArray("enemies").length()!=5 ||
                stage.getJSONArray("originalDropItems").length()==0 ||
                Base64.decode(stage.getJSONObject("combatMobInfo").getString("base64"),Base64.DEFAULT).length==0)
                throw new IOException("Incomplete furnace encounter");
        }
    }

    static boolean contains(long stage){return stage>=FIRST && stage<=LAST;}
    static int roleLevel(JSONObject state,JSONObject catalog)throws Exception{
        int level=state.optInt("starterProfile",0)==1?1:5;
        long exp=state.optLong("exp",0);
        JSONObject costs=catalog.getJSONObject("roleLevels");
        while(level<100){
            long cost=costs.optLong(Integer.toString(level),Long.MAX_VALUE);
            if(cost<=0 || exp<cost)break;
            exp-=cost;level++;
        }
        return level;
    }
    void install(JSONObject responses) throws Exception {
        for(long id=FIRST;id<=LAST;id++){
            JSONObject stage=stages.getJSONObject(Long.toString(id));
            String suffix="#"+id;
            responses.put("/combat/mob/json"+suffix,new JSONObject()
                .put("type","application/json")
                .put("body",stage.getJSONObject("combatJson").toString()));
            responses.put("/combat/mob/info"+suffix,new JSONObject()
                .put("type","application/octet-stream")
                .put("base64",stage.getJSONObject("combatMobInfo").getString("base64")));
        }
    }

    private static long day(long now){return (now+DAY_OFFSET)/86400L;}
    private static int todayCount(JSONObject state,long now){
        return state.optLong("furnaceDay",-1)==day(now)?state.optInt("furnaceCoreClaims",0):0;
    }
    private static int todayRuns(JSONObject state,long now){
        return state.optLong("furnaceDay",-1)==day(now)?state.optInt("furnaceDailyRuns",0):0;
    }
    private static JSONObject progress(JSONObject state,long id){
        JSONObject all=state.optJSONObject("furnaceStages");
        JSONObject found=all==null?null:all.optJSONObject(Long.toString(id));
        return found==null?new JSONObject():found;
    }
    private static JSONObject writableProgress(JSONObject state,long id)throws Exception{
        JSONObject all=state.optJSONObject("furnaceStages");
        if(all==null){all=new JSONObject();state.put("furnaceStages",all);}
        String key=Long.toString(id);JSONObject p=all.optJSONObject(key);
        if(p==null){p=new JSONObject();all.put(key,p);}return p;
    }
    private boolean unlocked(JSONObject state,long id,int roleLevel,boolean openAccess)throws Exception{
        if(openAccess)return true;
        if(roleLevel<stages.getJSONObject(Long.toString(id)).getInt("recommendedLevel"))return false;
        return id==FIRST || progress(state,id-1).optInt("wins",0)>0;
    }
    /** Add the missing chapter to the original Chaps response after mainline progress. */
    void appendProgress(ProtoWire all,JSONObject state,int roleLevel,long now)throws Exception{
        appendProgress(all,state,roleLevel,now,false);
    }
    void appendProgress(ProtoWire all,JSONObject state,int roleLevel,long now,boolean openAccess)throws Exception{
        ProtoWire chapter=new ProtoWire().set(1,CHAPTER).set(3,1);
        for(long id=FIRST;id<=LAST;id++){
            JSONObject p=progress(state,id);boolean passed=p.optInt("wins",0)>0;
            int stars=p.optInt("stars",0);
            chapter.add(2,new ProtoWire().set(1,id).set(2,passed?1:0)
                .set(3,stars==3?1:0).set(4,unlocked(state,id,roleLevel,openAccess)?1:0)
                .set(6,p.optInt("attempts",0)).set(7,passed&&stars==3?1:0).bytes());
        }
        all.add(1,chapter.bytes());
        // The native panel displays its remaining selections as 2 - field 2.
        // Total runs can exceed two; only fulfilled core selections use this quota.
        int usedSelections=Math.max(0,Math.min(2,todayCount(state,now)));
        all.set(2,usedSelections).set(3,state.optLong("furnaceLastBattleAt",0))
            .set(5,usedSelections);
    }

    void validateStart(JSONObject state,JSONObject catalog,long id,int roleLevel,long now,
                       String weapon)throws Exception{
        validateStart(state,catalog,id,roleLevel,now,false,weapon);
    }
    void validateStart(JSONObject state,JSONObject catalog,long id,int roleLevel,long now,
                       boolean openAccess,String weapon)throws Exception{
        if(!contains(id) || !unlocked(state,id,roleLevel,openAccess))
            throw new IOException("Weapon furnace depth unavailable or locked");
        if(!state.optBoolean("roleCreated",false))throw new IOException("Role required");
        if(todayCount(state,now)>=2)throw new IOException("Furnace core selections exhausted");
        if(state.optLong("stamina",0)<10)throw new IOException("Insufficient stamina for furnace");
        if(catalog==null || catalog.optJSONObject("items")==null ||
            catalog.optJSONObject("weapons")==null)
            throw new IOException("Item catalog unavailable");
        selectedCore(state,catalog,weapon);
    }
    void recordStart(JSONObject next,long id)throws Exception{
        JSONObject p=writableProgress(next,id);
        p.put("attempts",p.optInt("attempts",0)+1);
        next.remove("furnaceBattleResponse");
        next.remove("furnaceSettlementKey");
        // A previous victory can still have an unclaimed material choice.
        // Starting another battle must not discard that earned reward.
        // Keep the last paid response available for a late network retry.
        // The next victorious settlement replaces this choice context.
    }

    /** Recover the first unclaimed choice erased by the previously deployed start handler. */
    private void recoverFormerChoice(JSONObject state,JSONObject next)throws Exception{
        if(state.has("furnacePendingChoiceItems") || state.has("furnaceChoiceKey") ||
            state.optBoolean("furnacePendingChoiceInitialGranted",false) ||
            state.optBoolean("furnaceLegacyChoiceRecovered",false) ||
            state.optInt("furnaceDailyRuns",0)!=1 ||
            state.optInt("furnaceCoreClaims",0)!=1 ||
            state.optLong("furnaceLastBattleAt",0)<=0)return;
        JSONObject previous=state.optJSONObject("lastBattle");
        if(previous==null || !"1".equals(previous.optString("pass","")))return;
        long previousId=previous.optLong("instanceid",0);
        if(!contains(previousId) || progress(state,previousId).optInt("wins",0)!=1)return;
        next.put("furnacePendingChoiceItems",new JSONArray(stages.getJSONObject(
            Long.toString(previousId)).getJSONArray("originalDropItems").toString()));
        next.put("furnacePendingChoiceKey","recovered-"+state.optLong("furnaceLastBattleAt",0));
        next.put("furnaceChoicePurchases",0);
        next.put("furnaceChoiceBoughtItems",new JSONArray());
        next.remove("furnaceChoiceUnidentifiedResponse");
        next.remove("furnaceChoiceUnidentifiedKey");
        next.put("furnaceLegacyChoiceRecovered",true);
    }

    /** Resolve an abandoned choice before a later victory replaces the battle panel. */
    private static void grantFormerChoice(JSONObject next,JSONObject catalog,ProtoWire response)
            throws Exception{
        JSONArray pending=next.optJSONArray("furnacePendingChoiceItems");
        if(pending==null)return;
        String oldKey=next.optString("furnacePendingChoiceKey","");
        if(oldKey.isEmpty() || oldKey.equals(next.optString("startKey","")) || pending.length()==0)
            throw new IOException("Invalid previous furnace material choice");
        if(next.optBoolean("furnacePendingChoiceInitialGranted",false)){
            // Since the initial random material is now granted in the battle
            // result, this pending list only represents the optional paid
            // extra pick. Abandoning it must not mint another free material.
            next.remove("furnacePendingChoiceItems");
            next.remove("furnacePendingChoiceKey");
            next.remove("furnacePendingChoiceInitialGranted");
            next.remove("furnaceChoicePurchases");
            next.remove("furnaceChoiceBoughtItems");
            return;
        }
        long item=pending.getLong(0);
        grant(next,catalog,item,1);
        response.add(3,loot(item,1).bytes());
        next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
        next.put("furnaceAutoClaimedChoices",next.optInt("furnaceAutoClaimedChoices",0)+1);
        next.remove("furnacePendingChoiceItems");next.remove("furnacePendingChoiceKey");
        next.remove("furnacePendingChoiceInitialGranted");
        next.remove("furnaceChoicePurchases");
        next.remove("furnaceChoiceBoughtItems");
    }

    private long selectedCore(JSONObject state,JSONObject catalog,String raw)throws Exception{
        if(raw==null || !raw.matches("[1-9][0-9]{0,18}"))
            throw new IOException("Missing selected furnace weapon");
        long weapon;
        try{weapon=Long.parseLong(raw);}catch(NumberFormatException ex){throw new IOException("Invalid selected weapon",ex);}
        String key=Long.toString(weapon);
        if(!catalog.getJSONObject("weapons").has(key) || !coreItems.has(key))
            throw new IOException("Selected weapon has no original core item");
        JSONObject owned=state.optJSONObject("ownedServants");
        if(owned==null)throw new IOException("Owned servants unavailable");
        long servant=catalog.getJSONObject("weapons").getJSONObject(key).getLong("servant");
        String sid=Long.toString(servant);
        if(!owned.has(sid))throw new IOException("Selected weapon is not owned");
        ProtoWire character=ProtoWire.parse(Base64.decode(owned.getString(sid),Base64.DEFAULT));
        boolean found=false;
        for(ProtoWire.Field f:character.fields)if(f.number==13&&f.type==2 &&
            ProtoWire.parse(f.data).number(1,0)==weapon){found=true;break;}
        if(!found)throw new IOException("Selected weapon is not owned");
        return coreItems.getLong(key);
    }
    private static void grant(JSONObject state,JSONObject catalog,long item,long amount)throws Exception{
        String key=Long.toString(item);
        if(!catalog.getJSONObject("items").has(key))throw new IOException("Furnace reward item absent from catalog");
        JSONObject bag=state.getJSONObject("items");
        long after=Math.addExact(bag.optLong(key,0),amount);
        if(after>LocalEconomy.stackCap(catalog,key))throw new IOException("Furnace item stack full");
        bag.put(key,after);
    }
    private static ProtoWire loot(long item,long count){
        return new ProtoWire().set(1,3).set(2,item).set(3,count).set(4,count);
    }

    /** Five distinct original weapon cores: one free and four original paid picks.
     * The original server weights are unavailable; use an unbiased local sample. */
    private JSONArray randomCoreChoices(JSONObject catalog,long specifiedCore)throws Exception{
        Set<Long> unique=new HashSet<Long>();
        for(String weapon:coreItems.keySet()){
            long core=coreItems.getLong(weapon);
            if(core!=specifiedCore && catalog.getJSONObject("items").has(Long.toString(core)))
                unique.add(core);
        }
        ArrayList<Long> pool=new ArrayList<Long>(unique);
        if(pool.size()<RANDOM_CORE_CHOICES)throw new IOException("Furnace core choice pool incomplete");
        Collections.sort(pool);
        Collections.shuffle(pool,RANDOM);
        JSONArray choices=new JSONArray();
        for(int i=0;i<RANDOM_CORE_CHOICES;i++)choices.put(pool.get(i));
        return choices;
    }

    private static String choicePool(JSONArray pending)throws Exception{
        ArrayList<Long> pool=new ArrayList<Long>();
        for(int i=0;i<pending.length();i++)pool.add(pending.getLong(i));
        Collections.sort(pool);
        StringBuilder result=new StringBuilder();
        for(long item:pool){if(result.length()>0)result.append(',');result.append(item);}
        return result.toString();
    }

    /** SweepPanel expects a SweepResult containing one LootResult per clear. */
    Settlement sweep(JSONObject state,JSONObject catalog,Map<String,String> args,long now,
                     boolean openAccess)throws Exception{
        long chapter=StageSweep.positive(args,"chapid");
        long id=StageSweep.positive(args,"instanceid");
        int count=StageSweep.quantity(args);
        if(chapter!=CHAPTER || !contains(id))
            throw new IOException("Furnace sweep stage does not belong to chapter");
        String requestIdentity=StageSweep.identity(args);
        String fingerprint=StageSweep.digest(chapter+"\u0000"+id+"\u0000"+count);
        JSONObject prior=requestIdentity==null?null:
            StageSweep.replayLedger(state).optJSONObject(requestIdentity);
        if(prior!=null){
            if(!fingerprint.equals(prior.optString("fingerprint","")))
                throw new IOException("Conflicting sweep retry");
            return new Settlement(null,Base64.decode(prior.getString("response"),Base64.DEFAULT));
        }
        if(!state.optBoolean("roleCreated",false) || state.optBoolean("namePending",false))
            throw new IOException("Furnace sweep requires a named role");
        if(state.optBoolean("active",false))throw new IOException("Cannot sweep during battle");
        JSONObject cleared=progress(state,id);
        if(cleared.optInt("wins",0)<1 || cleared.optInt("stars",0)!=3)
            throw new IOException("Furnace sweep requires a three-star clear");
        if(catalog==null || catalog.optJSONObject("items")==null)
            throw new IOException("Furnace sweep item catalog unavailable");
        if(!unlocked(state,id,roleLevel(state,catalog),openAccess))
            throw new IOException("Furnace sweep stage locked");
        int claims=todayCount(state,now),runs=todayRuns(state,now);
        if(claims>=2 || count>2-claims)
            throw new IOException("Furnace core selections exhausted");
        String weapon=state.optString("furnaceSelectedWeapon","");
        Long selected=null;
        if(!weapon.isEmpty())try{selected=selectedCore(state,catalog,weapon);}
        catch(IOException ignored){
            // A stale selection does not consume the remaining core quota.
        }
        if(selected==null)throw new IOException("Furnace sweep requires selected weapon");
        long cost=Math.multiplyExact(10L,count);
        long stamina=state.optLong("stamina",200);
        if(stamina<cost)throw new IOException("Insufficient furnace sweep stamina");
        JSONObject next=new JSONObject(state.toString());
        LocalEconomy.init(next,catalog);
        ProtoWire response=new ProtoWire().set(2,new byte[0]).set(3,stamina-cost).set(4,0);
        JSONArray drops=stages.getJSONObject(Long.toString(id)).getJSONArray("originalDropItems");
        int depth=(int)(id-FIRST)+1;
        for(int i=0;i<count;i++){
            ProtoWire one=new ProtoWire().set(2,new byte[0]);
            Set<Long> unique=new HashSet<Long>();
            for(int j=0;j<drops.length();j++){
                long item=drops.getLong(j);
                if(!unique.add(item))continue;
                grant(next,catalog,item,depth);
                one.add(1,loot(item,depth).bytes());
            }
            long initial=randomCoreChoices(catalog,selected).getLong(0);
            grant(next,catalog,initial,1);
            one.add(1,loot(initial,1).bytes());
            if(claims<2){
                grant(next,catalog,selected,SPECIFIED_CORE_AMOUNT);
                one.add(1,loot(selected,SPECIFIED_CORE_AMOUNT).bytes());
                claims++;
            }
            response.add(1,one.bytes());
        }
        next.put("stamina",stamina-cost);
        next.put("furnaceDay",day(now));
        next.put("furnaceDailyRuns",Math.addExact(runs,count));
        next.put("furnaceCoreClaims",claims);
        next.put("furnaceLastBattleAt",now);
        JSONObject p=writableProgress(next,id);
        p.put("sweeps",Math.addExact(p.optInt("sweeps",0),count));
        p.put("attempts",Math.addExact(p.optInt("attempts",0),count));
        next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
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
        StaminaRecovery.reconcileMutation(next,StaminaRecovery.level(next,catalog),now);
        return new Settlement(next,encoded);
    }
    Settlement settle(JSONObject state,JSONObject catalog,Map<String,String> args,long now)throws Exception{
        try{return settleChecked(state,catalog,args,now);}
        catch(Exception ex){
            // Categories are fixed strings. Never log form values, account
            // identity, item IDs, or exception messages from a live request.
            System.err.println("FURNACE_SETTLEMENT_REJECT "+settlementRejectCategory(ex));
            throw ex;
        }
    }
    private static String settlementRejectCategory(Exception ex){
        String message=ex.getMessage();
        if("Invalid furnace stage".equals(message))return "INVALID_STAGE";
        if("Unexpected furnace settlement stage".equals(message))return "STAGE_MISMATCH";
        if("No active furnace battle".equals(message))return "NOT_ACTIVE";
        if("Invalid furnace victory flag".equals(message))return "INVALID_PASS";
        if("Invalid furnace stars".equals(message))return "INVALID_STARS";
        if("Insufficient furnace stamina".equals(message))return "STAMINA";
        if("Furnace item stack full".equals(message))return "ITEM_CAP";
        if("Furnace reward item absent from catalog".equals(message))return "ITEM_CATALOG";
        if("Invalid previous furnace material choice".equals(message))return "PENDING_CHOICE";
        if(ex instanceof IOException)return "OTHER_IO";
        if(ex instanceof org.json.JSONException)return "CATALOG";
        if(ex instanceof ArithmeticException)return "VALUE_OVERFLOW";
        return "OTHER";
    }
    private Settlement settleChecked(JSONObject state,JSONObject catalog,Map<String,String> args,long now)
            throws Exception{
        long id;
        String requestedId=args.get("instanceid");
        if(requestedId==null || requestedId.isEmpty() || "0".equals(requestedId))
            id=state.optLong("activeStage",0);
        else try{id=Long.parseLong(requestedId);}catch(NumberFormatException ex){
            throw new IOException("Invalid furnace stage",ex);
        }
        if(!contains(id) || state.optLong("activeStage",0)!=id)
            throw new IOException("Unexpected furnace settlement stage");
        if(!state.optBoolean("active",false)){
            if(state.has("furnaceBattleResponse") &&
                state.optString("furnaceSettlementKey").equals(state.optString("startKey")))
                return new Settlement(null,Base64.decode(state.getString("furnaceBattleResponse"),Base64.DEFAULT));
            throw new IOException("No active furnace battle");
        }
        String pass=args.get("pass");
        if(!"0".equals(pass) && !"1".equals(pass))throw new IOException("Invalid furnace victory flag");
        int stars=0;
        try{stars=Integer.parseInt(args.get("stars"));}catch(Exception ignored){}
        if(stars<0||stars>3)throw new IOException("Invalid furnace stars");
        JSONObject next=new JSONObject(state.toString());next.put("active",false);
        next.remove("furnaceBattleWeapon");
        recoverFormerChoice(state,next);
        ProtoWire response=new ProtoWire().set(1,next.optLong("stamina",200))
            .set(4,new byte[0]);
        if("1".equals(pass)){
            int claims=todayCount(state,now),runs=todayRuns(state,now);
            long cost=claims<2?10:20;
            long stamina=next.optLong("stamina",0);
            if(stamina<cost)throw new IOException("Insufficient furnace stamina");
            next.put("stamina",stamina-cost);response.set(1,stamina-cost);
            int depth=(int)(id-FIRST)+1;
            LocalEconomy.init(next,catalog);
            grantFormerChoice(next,catalog,response);
            JSONArray drops=stages.getJSONObject(Long.toString(id)).getJSONArray("originalDropItems");
            Set<Long> unique=new HashSet<Long>();
            for(int i=0;i<drops.length();i++){
                long item=drops.getLong(i);
                if(!unique.add(item))continue;
                long count=depth;
                grant(next,catalog,item,count);
                response.add(3,loot(item,count).bytes());
            }
            long specifiedCore=0;
            if(claims<2){
                String requested=args.get("wantweapon");
                String previous=state.optString("furnaceSelectedWeapon","");
                String bound=state.optString("furnaceBattleWeapon","");
                boolean awarded=false;
                String[] candidates=state.has("furnaceBattleWeapon")
                    ?new String[]{bound}:new String[]{requested,previous};
                for(String weapon:candidates){
                    if(weapon==null || weapon.isEmpty() || "0".equals(weapon))continue;
                    long core;
                    try{core=selectedCore(next,catalog,weapon);}catch(IOException ex){
                        // A stale or unowned weapon cannot mint a core or
                        // invalidate a finished battle.
                        continue;
                    }
                    grant(next,catalog,core,SPECIFIED_CORE_AMOUNT);
                    response.add(6,loot(core,SPECIFIED_CORE_AMOUNT).bytes());
                    next.put("furnaceSelectedWeapon",weapon);
                    specifiedCore=core;awarded=true;break;
                }
                if(!awarded)next.put("furnaceCoreSkipped",next.optInt("furnaceCoreSkipped",0)+1);
                next.put("furnaceCoreClaims",awarded?claims+1:claims);
            }else next.put("furnaceCoreClaims",claims);
            JSONArray choices=randomCoreChoices(catalog,specifiedCore);
            for(int i=0;i<choices.length();i++)response.add(7,loot(choices.getLong(i),1).bytes());
            // OneOfRandom must be a member of RandomLoot, including the free
            // pick. The native panel marks that slot as obtained by item ID.
            long initialChoice=choices.getLong(0);
            grant(next,catalog,initialChoice,1);
            response.set(8,loot(initialChoice,1).bytes());
            next.put("furnacePendingChoiceItems",choices);
            next.put("furnacePendingChoiceKey",state.optString("startKey"));
            next.put("furnacePendingChoiceInitialGranted",true);
            next.put("furnaceChoicePurchases",0);
            next.put("furnaceChoiceBoughtItems",new JSONArray());
            next.remove("furnaceChoiceUnidentifiedResponse");
            next.remove("furnaceChoiceUnidentifiedKey");
            next.remove("furnaceChoiceResponse");
            next.remove("furnaceChoiceKey");
            next.put("furnaceDailyRuns",runs+1);next.put("furnaceDay",day(now));
            JSONObject p=writableProgress(next,id);
            p.put("wins",p.optInt("wins",0)+1);
            p.put("stars",Math.max(p.optInt("stars",0),stars));
            next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
        }
        next.put("furnaceLastBattleAt",now);
        next.put("furnaceSettlementKey",state.optString("startKey"));
        next.put("lastSettlementAt",now);
        next.put("lastBattle",new JSONObject(args));
        ProgressionTasks.recordBattleKills(next,args);
        if("1".equals(pass))
            StaminaRecovery.reconcileMutation(next,StaminaRecovery.level(next,catalog),now);
        response.set(2,StaminaRecovery.protocolTime(next,now));
        byte[] encoded=response.bytes();
        next.put("furnaceBattleResponse",Base64.encodeToString(encoded,Base64.NO_WRAP));
        return new Settlement(next,encoded);
    }

    /** Buy an unclaimed random material from the last victorious battle. */
    Settlement chooseMaterials(JSONObject state,JSONObject catalog,Map<String,String> args,long now)throws Exception{
        String identity=args.get("idempotency");
        if(identity!=null){
            if(identity.isEmpty() || identity.length()>128 ||
                !identity.matches("[A-Za-z0-9._:-]+"))
                throw new IOException("Invalid furnace choice request identity");
            identity=StageSweep.digest("furnace-choice\u0000"+identity);
            JSONObject ledger=state.optJSONObject("furnaceChoiceRequests");
            JSONObject prior=ledger==null?null:ledger.optJSONObject(identity);
            if(prior!=null){
                if(!prior.optString("materials","").equals(
                        args.get("materials")==null?"":args.get("materials")) ||
                    !prior.optString("choicePool","").equals(
                        args.get("choicePool")==null?"":args.get("choicePool")))
                    throw new IOException("Conflicting furnace choice retry");
                return new Settlement(null,Base64.decode(prior.getString("response"),Base64.DEFAULT));
            }
        }else{
            // The original request has only rid, time and sign. A duplicate
            // cannot be distinguished from a second tap, so at most one
            // unidentified purchase is allowed for this battle.
            String current=state.optString("furnacePendingChoiceKey",
                state.optString("furnaceChoiceKey",""));
            if(!current.isEmpty() && current.equals(
                    state.optString("furnaceChoiceUnidentifiedKey","")) &&
                state.has("furnaceChoiceUnidentifiedResponse"))
                return new Settlement(null,Base64.decode(
                    state.getString("furnaceChoiceUnidentifiedResponse"),Base64.DEFAULT));
        }
        JSONArray pending=state.optJSONArray("furnacePendingChoiceItems");
        if(pending==null){
            if(identity==null && state.has("furnaceChoiceResponse"))
                return new Settlement(null,Base64.decode(state.getString("furnaceChoiceResponse"),Base64.DEFAULT));
            throw new IOException("No pending furnace material choice");
        }
        String choiceKey=state.optString("furnacePendingChoiceKey","");
        if(choiceKey.isEmpty() ||
            (state.optBoolean("active",false) && choiceKey.equals(state.optString("startKey"))))
            throw new IOException("Furnace choice is not ready");
        String raw=args.get("materials");
        String suppliedPool=args.get("choicePool");
        if(suppliedPool!=null && !choicePool(pending).equals(suppliedPool))
            throw new IOException("Conflicting furnace choice pool");
        // The preserved ChooseMaterials request only sends rid. The server
        // chooses the next unclaimed offered item; an explicit material list
        // remains accepted for older local clients.
        if(raw!=null && (raw.isEmpty() || raw.length()>512))
            throw new IOException("Invalid furnace material choice");
        Set<Long> offered=new HashSet<Long>();
        for(int i=0;i<pending.length();i++)offered.add(pending.getLong(i));
        if(offered.isEmpty())throw new IOException("No furnace materials were offered");
        int purchases=state.optInt("furnaceChoicePurchases",0);
        if(purchases<0 || purchases>=EXTRA_MATERIAL_PRICES.length)
            throw new IOException("Furnace material choices exhausted");
        Set<Long> claimed=new HashSet<Long>();
        if(state.optBoolean("furnacePendingChoiceInitialGranted",false))
            claimed.add(pending.getLong(0));
        JSONArray bought=state.optJSONArray("furnaceChoiceBoughtItems");
        if(bought!=null)for(int i=0;i<bought.length();i++)claimed.add(bought.getLong(i));
        long selected=0;
        if(raw==null){
            ArrayList<Long> remaining=new ArrayList<Long>();
            for(int i=0;i<pending.length();i++){
                long candidate=pending.getLong(i);
                if(!claimed.contains(candidate))remaining.add(candidate);
            }
            if(!remaining.isEmpty())selected=remaining.get(RANDOM.nextInt(remaining.size()));
        }else{
            java.util.regex.Matcher numbers=java.util.regex.Pattern.compile("[0-9]{1,18}").matcher(raw);
            while(numbers.find()){
                long candidate=Long.parseLong(numbers.group());
                if(offered.contains(candidate) && !claimed.contains(candidate)){
                    selected=candidate;break;
                }
            }
        }
        if(selected==0)throw new IOException("No unclaimed furnace materials remain");
        int price=EXTRA_MATERIAL_PRICES[purchases];
        long diamonds=state.optLong("rmb",0);
        if(diamonds<price)throw new IOException("Insufficient diamonds for furnace choice");
        JSONObject next=new JSONObject(state.toString());
        LocalEconomy.init(next,catalog);
        grant(next,catalog,selected,1);
        next.put("rmb",diamonds-price);
        next.put("inventoryRevision",Math.addExact(next.optLong("inventoryRevision",0),1));
        next.put("furnaceChoicePurchases",purchases+1);
        JSONArray updated=bought==null?new JSONArray():new JSONArray(bought.toString());
        updated.put(selected);next.put("furnaceChoiceBoughtItems",updated);
        byte[] response=new ProtoWire().set(8,loot(selected,1).bytes()).bytes();
        next.put("furnaceChoiceResponse",Base64.encodeToString(response,Base64.NO_WRAP));
        next.put("furnaceChoiceKey",choiceKey);
        if(identity!=null){
            JSONObject ledger=next.optJSONObject("furnaceChoiceRequests");
            if(ledger==null){ledger=new JSONObject();next.put("furnaceChoiceRequests",ledger);}
            ledger.put(identity,new JSONObject().put("choiceKey",choiceKey)
                .put("materials",raw==null?"":raw)
                .put("choicePool",suppliedPool==null?"":suppliedPool)
                .put("response",Base64.encodeToString(response,Base64.NO_WRAP)));
            JSONArray formerOrder=next.optJSONArray("furnaceChoiceRequestOrder");
            JSONArray order=new JSONArray();
            if(formerOrder!=null)for(int i=0;i<formerOrder.length();i++)
                order.put(formerOrder.getString(i));
            order.put(identity);
            if(order.length()>MAX_CHOICE_REPLAY_KEYS){
                JSONArray recent=new JSONArray();
                for(int i=order.length()-MAX_CHOICE_REPLAY_KEYS;i<order.length();i++)
                    recent.put(order.getString(i));
                for(int i=0;i<order.length()-MAX_CHOICE_REPLAY_KEYS;i++)
                    ledger.remove(order.getString(i));
                order=recent;
            }
            next.put("furnaceChoiceRequestOrder",order);
        }else{
            next.put("furnaceChoiceUnidentifiedResponse",
                Base64.encodeToString(response,Base64.NO_WRAP));
            next.put("furnaceChoiceUnidentifiedKey",choiceKey);
        }
        claimed.add(selected);
        boolean available=false;
        for(int i=0;i<pending.length();i++)if(!claimed.contains(pending.getLong(i))){
            available=true;break;
        }
        if(!available || purchases+1>=EXTRA_MATERIAL_PRICES.length){
            next.remove("furnacePendingChoiceItems");next.remove("furnacePendingChoiceKey");
            next.remove("furnacePendingChoiceInitialGranted");
        }
        return new Settlement(next,response);
    }
}
