package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.UUID;

/** Five original type-4 stone slates; combat waves are an explicit temporary placeholder. */
final class StoneSlateBattle {
    private static StoneSlateBattle singleton;
    private final Map<Long,JSONObject> stages=new HashMap<Long,JSONObject>();

    StoneSlateBattle(JSONObject source)throws Exception{
        if(source.optInt("schemaVersion",0)!=1 ||
            !"temporary-placeholder-single-wave".equals(source.optString("mode","")))
            throw new IOException("Unexpected stone slate catalog");
        JSONObject rows=source.getJSONObject("stages");
        if(rows.length()!=5)throw new IOException("Incomplete stone slate catalog");
        for(long id=3100005001L;id<=3100005005L;id++){
            JSONObject row=rows.getJSONObject(Long.toString(id));
            JSONObject original=row.getJSONObject("source").getJSONObject("instance");
            JSONArray rewards=row.getJSONArray("rewards");
            if(row.getLong("id")!=id || row.getInt("type")!=4 ||
                !"4".equals(original.getString("instance_type")) ||
                rewards.length()!=1 || rewards.getJSONObject(0).getInt("type")!=99 ||
                rewards.getJSONObject(0).getLong("value")!=100 ||
                !"99".equals(original.getString("reward_type1")) ||
                !"100".equals(original.getString("reward_value1")) ||
                !"0".equals(original.getString("instance_stamina_enter")) ||
                !"0".equals(original.getString("instance_stamina_victory")))
                throw new IOException("Invalid original stone slate reward or ID");
            JSONObject combat=row.getJSONObject("combatJson");
            if(!Long.toString(id).equals(combat.getJSONObject("EnemyLayer").getString("levelID")) ||
                combat.getJSONObject("EnemyLayer").getJSONArray("areas").length()==0 ||
                Base64.decode(row.getJSONObject("combatMobInfo").getString("base64"),0).length==0)
                throw new IOException("Incomplete temporary stone slate combat");
            stages.put(id,row);
        }
    }

    static synchronized StoneSlateBattle bundled()throws Exception{
        if(singleton!=null)return singleton;
        InputStream input=StoneSlateBattle.class.getResourceAsStream("/stone_slate_catalog.json");
        if(input==null)throw new IOException("Stone slate catalog missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int count;
            while((count=input.read(buffer))!=-1){
                if(out.size()+count>1024*1024)throw new IOException("Stone slate catalog too large");
                out.write(buffer,0,count);
            }
            singleton=new StoneSlateBattle(new JSONObject(new String(out.toByteArray(),"UTF-8")));
            return singleton;
        }finally{input.close();}
    }

    static boolean contains(long id){return id>=3100005001L && id<=3100005005L;}
    static long strictStage(Map<String,String> args)throws IOException{
        String raw=args.get("instanceid"),nativeId=args.get("challengeid");
        long nativeStage=0;
        if(nativeId!=null){
            if(!nativeId.matches("[1-5]"))throw new IOException("Invalid original stone slate challenge ID");
            int restriction=Integer.parseInt(nativeId);
            nativeStage=restriction==1?3100005005L:3100004999L+restriction;
        }
        if(raw==null && nativeStage!=0)raw=Long.toString(nativeStage);
        if(raw==null || !raw.matches("310000500[1-5]"))throw new IOException("Invalid stone slate ID");
        if(nativeStage!=0 && nativeStage!=Long.parseLong(raw))throw new IOException("Conflicting stone slate IDs");
        return Long.parseLong(raw);
    }
    private static void requireRole(JSONObject state)throws IOException{
        if(!state.optBoolean("roleCreated",false))throw new IOException("Stone slate requires created role");
    }
    private static JSONObject progress(JSONObject state,long id){
        JSONObject all=state.optJSONObject("stoneSlateStages");
        JSONObject row=all==null?null:all.optJSONObject(Long.toString(id));
        return row==null?new JSONObject():row;
    }
    private static JSONObject writable(JSONObject state,long id)throws Exception{
        JSONObject all=state.optJSONObject("stoneSlateStages");
        if(all==null){all=new JSONObject();state.put("stoneSlateStages",all);}
        JSONObject row=all.optJSONObject(Long.toString(id));
        if(row==null){row=new JSONObject();all.put(Long.toString(id),row);}
        return row;
    }

    void install(JSONObject responses)throws Exception{
        for(Map.Entry<Long,JSONObject> entry:stages.entrySet()){
            JSONObject row=entry.getValue();String suffix="#"+entry.getKey();
            responses.put("/combat/mob/json"+suffix,new JSONObject().put("type","application/json")
                .put("body",row.getJSONObject("combatJson").toString()));
            responses.put("/combat/mob/info"+suffix,new JSONObject().put("type","application/octet-stream")
                .put("base64",row.getJSONObject("combatMobInfo").getString("base64")));
        }
    }

    JSONObject begin(JSONObject state,long id,Map<String,String> args,long now)throws Exception{
        requireRole(state);
        if(!contains(id))throw new IOException("Unknown stone slate");
        if(progress(state,id).optBoolean("rewardClaimed",false))
            throw new IOException("Stone slate already completed");
        String key=args.get("idempotency");
        // NetMsgBase normally supplies idempotency. Permit the minimal native
        // rid+instanceid form too; an active same-stage retry remains read-only.
        if(key==null)key="slate-"+UUID.randomUUID().toString();
        if(key.isEmpty() || key.length()>128)throw new IOException("Invalid stone slate start identity");
        if(state.optBoolean("active",false)){
            if(state.optLong("activeStage",0)==id)return state;
            // Match existing normal/daily entry semantics: a local defeat or
            // abandoned load may leave the shared active marker behind. The
            // new explicit entry owns activeStage; late results of the former
            // stage remain guarded by their own stage checks.
        }
        // A transport retry of an already failed/cancelled attempt must not reopen it.
        if(key.equals(state.optString("stoneSlateStartKey","")) &&
            state.optLong("stoneSlateStage",0)==id)return state;
        JSONObject next=new JSONObject(state.toString());
        next.put("active",true).put("activeStage",id).put("startKey",key)
            .put("stoneSlateStage",id).put("stoneSlateStartKey",key).put("battleStartedAt",now);
        next.remove("stoneSlateLastResponse");next.remove("battleResponse");
        next.remove("activeBattleServants");
        // Native CSC has a separate preparation marker and may have no shared
        // activeStage. Invalidate an abandoned round, without advancing it or
        // touching its saved HP, energy, completed-round cache or rewards.
        next.remove("mazePreparedRound");
        JSONObject row=writable(next,id);
        row.put("attempts",Math.addExact(row.optLong("attempts",0),1));
        return next;
    }

    static final class Settlement{
        final JSONObject next;final byte[] response;
        Settlement(JSONObject next,byte[] response){this.next=next;this.response=response;}
    }
    Settlement settle(JSONObject state,Map<String,String> args,long now,boolean cancel)throws Exception{
        requireRole(state);long id=strictStage(args);
        JSONObject old=progress(state,id);
        if(!cancel && old.optBoolean("rewardClaimed",false))
            return new Settlement(null,Base64.decode(old.getString("responseBase64"),0));
        if(cancel && old.optBoolean("rewardClaimed",false))
            return new Settlement(null,new ProtoWire().set(1,state.optLong("stamina",200))
                .set(2,StaminaRecovery.protocolTime(state,now)).set(4,new byte[0]).bytes());
        String supplied=args.get("battleStartKey");
        if(supplied!=null && !supplied.equals(state.optString("stoneSlateStartKey","")))
            throw new IOException("Stale stone slate settlement");
        if(state.optLong("stoneSlateStage",0)!=id || state.optLong("activeStage",0)!=id)
            throw new IOException("Unexpected stone slate settlement");
        if(!state.optBoolean("active",false)){
            if(state.has("stoneSlateLastResponse"))
                return new Settlement(null,Base64.decode(state.getString("stoneSlateLastResponse"),0));
            throw new IOException("No active stone slate battle");
        }
        String pass=args.get("pass");
        if(pass!=null && !pass.equals("0") && !pass.equals("1"))
            throw new IOException("Invalid stone slate result");
        boolean won=!cancel && !"0".equals(pass);
        JSONObject next=new JSONObject(state.toString());next.put("active",false);
        ProtoWire result=new ProtoWire().set(1,next.optLong("stamina",200))
            .set(2,StaminaRecovery.protocolTime(next,now)).set(4,new byte[0]);
        JSONObject row=writable(next,id);
        if(won){
            next.put("rmb",Math.addExact(next.optLong("rmb",0),100));
            row.put("wins",1).put("rewardClaimed",true).put("completedAt",now);
            // Native ChallengeMode already calls AddRMBForChallenge(100)
            // before this asynchronous response. LootList.Parse accumulates
            // another type-99 object, so returning one here would display 200.
            // The server credits 100 atomically; its response deliberately has
            // no diamond loot object, EXP, gold or stamina charge.
            // The native winner marks ChallengeState[challengeId-1]. There is
            // no verified original CloseLevel event; role field 117 persists
            // those same completion bits on the next role refresh/reconnect.
        }
        byte[] bytes=result.bytes();
        if(won)row.put("responseBase64",Base64.encodeToString(bytes,Base64.NO_WRAP));
        next.put("lastSettlementAt",now).put("stoneSlateLastResponse",Base64.encodeToString(bytes,Base64.NO_WRAP));
        return new Settlement(next,bytes);
    }

    byte[] progress(byte[] seed,JSONObject state)throws Exception{
        ProtoWire all=ProtoWire.parse(seed);ProtoWire chapter=null;
        for(ProtoWire.Field f:all.fields)if(f.number==1 && f.type==2){
            ProtoWire candidate=ProtoWire.parse(f.data);
            if(candidate.number(1,0)==3000005L){chapter=candidate;break;}
        }
        if(chapter==null){chapter=new ProtoWire().set(1,3000005L);}
        chapter.clear(2);
        for(long id=3100005001L;id<=3100005005L;id++){
            JSONObject row=progress(state,id);boolean won=row.optBoolean("rewardClaimed",false);
            chapter.add(2,new ProtoWire().set(1,id).set(2,won?1:0).set(3,won?1:0)
                .set(4,won?0:1).set(6,row.optLong("attempts",0)).set(7,0).bytes());
        }
        boolean replaced=false;
        for(ProtoWire.Field f:all.fields)if(f.number==1 && f.type==2 &&
                ProtoWire.parse(f.data).number(1,0)==3000005L){f.data=chapter.bytes();replaced=true;}
        if(!replaced)all.add(1,chapter.bytes());
        return all.bytes();
    }

    static long challengeBits(JSONObject state){
        long bits=0;
        for(long id=3100005001L;id<=3100005005L;id++){
            if(!progress(state,id).optBoolean("rewardClaimed",false))continue;
            int challenge=id==3100005005L?1:(int)(id-3100004999L);
            bits|=1L<<(challenge-1);
        }
        return bits;
    }

    byte[] role(JSONObject state,Map<String,String> args,byte[] seed,JSONObject catalog)throws Exception{
        long id=state.optLong("activeStage",0);
        if(!state.optBoolean("active",false) || !contains(id))throw new IOException("No active stone slate role");
        JSONObject stage=stages.get(id);
        if(LocalEconomy.number(args.get("challengeid"),-1)!=stage.getLong("challengeId"))
            throw new IOException("Mismatched stone slate restricted role");
        JSONArray variants=stage.getJSONObject("source").getJSONArray("challengeRows");
        JSONObject row=null;
        String rawServants=args.get("svcardids"),rawWeapons=args.get("wpids");
        if(rawServants!=null || rawWeapons!=null){
            if(rawServants==null || rawWeapons==null)throw new IOException("Incomplete stone slate roster");
            String[] selectedServants=rawServants.split("[|,;]",-1),selectedWeapons=rawWeapons.split("[|,;]",-1);
            if(selectedServants.length!=4 || selectedWeapons.length!=4)
                throw new IOException("Invalid stone slate roster size");
            // The native request already contains its channel's original four
            // servants/weapons. Select only an exact original table variant;
            // this handles mainland/international differences without trusting
            // a client-provided channel or fabricating a different party.
            for(int i=0;i<variants.length();i++){
                JSONObject variant=variants.getJSONObject(i);boolean match=true;
                for(int slot=0;slot<4;slot++)if(
                    !selectedServants[slot].equals(variant.getString("servant_id"+(slot+1))) ||
                    !selectedWeapons[slot].equals(variant.getString("servant_weapon_id"+(slot+1))))match=false;
                if(match){row=variant;break;}
            }
            if(row==null)throw new IOException("Unlisted original stone slate roster");
        }else{
            // Compatibility for old minimal test/read callers; the live
            // native path above chooses its actual tuple. This fallback is
            // explicitly the preserved mainland/shared roster, not a claim
            // about the installed APK's channel.
            for(int i=0;i<variants.length();i++){
                JSONObject variant=variants.getJSONObject(i);String group=variant.getString("channel_group");
                if(group.equals("0") || group.equals("22")){row=variant;break;}
            }
        }
        if(row==null)throw new IOException("Original stone slate mainland roster unavailable");
        long[] servants=new long[4],weapons=new long[4];
        for(int i=0;i<4;i++){
            servants[i]=Long.parseLong(row.getString("servant_id"+(i+1)));
            weapons[i]=Long.parseLong(row.getString("servant_weapon_id"+(i+1)));
        }
        TutorialBattleFixtures.ChallengeRole role=new TutorialBattleFixtures.ChallengeRole(id,
            stage.getLong("challengeId"),Integer.parseInt(row.getString("role_level")),
            Integer.parseInt(row.getString("servant_level")),Integer.parseInt(row.getString("servant_rank")),
            Integer.parseInt(row.getString("servant_star")),Integer.parseInt(row.getString("servant_weapon")),servants,weapons);
        return LocalEconomy.scriptedGuideCombat(args,seed,catalog,role);
    }
}
