package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.Collections;

/** The twelve locally reconstructed Barrier Maze encounters on their original APK stage IDs. */
final class BarrierLabyrinth {
    static final class Group {
        final JSONObject state;
        final byte[] response;
        Group(JSONObject state,byte[] response){this.state=state;this.response=response;}
    }
    // offline_maze_round.py selected these original InstanceMobList rows for its
    // twelve waves. This is a fixed local expedition, not an original server roll.
    private static final long[] STAGES={
        3130001026L,3130001021L,3130001008L,3130001012L,
        3130001013L,3130001027L,3130001009L,3130001028L,
        3130001003L,3130001005L,3130001022L,3130001025L
    };
    // The preserved offline expedition repeats its five configured enemies
    // across up to eight waves. Its reconstructed combat values overwhelm a
    // fresh level-five party, so scale only the maze-specific MobInfo stats.
    private static final int MOB_HP_DIVISOR=4;
    private static final int MOB_ATTACK_DIVISOR=5;
    private static final int DAILY_RESETS=1; // APK constant CORE_INSTANCE_ENTER_LIMIT.

    private BarrierLabyrinth() {}

    static int rounds(){return STAGES.length;}
    static boolean supports(long stage){
        for(long id:STAGES)if(id==stage)return true;
        return false;
    }
    static long stageForRound(int round)throws IOException{
        if(round<1 || round>STAGES.length)throw new IOException("Maze run already complete");
        return STAGES[round-1];
    }
    static String fixtureKey(String combatPath,int round)throws IOException{
        if(!combatPath.equals("/combat/mob/json") && !combatPath.equals("/combat/mob/info"))
            throw new IOException("Unknown maze encounter fixture");
        return combatPath+"#"+stageForRound(round);
    }

    /**
     * Install per-stage aliases from the author's twelve preserved encounters.
     * StageCatalog may already have copied the old aliases; both orders work.
     */
    static void install(JSONObject responses)throws Exception{
        for(int round=1;round<=STAGES.length;round++){
            long stage=STAGES[round-1];
            String oldSuffix="#"+StageCatalog.FORMER_MAZE_ENTRY+"@"+round;
            String copiedSuffix="#"+StageCatalog.MAZE_TRIAL+"@"+round;
            JSONObject rawJson=source(responses,"/combat/mob/json",copiedSuffix,oldSuffix);
            JSONObject battle=new JSONObject(rawJson.getString("body"));
            JSONObject enemy=battle.getJSONObject("EnemyLayer");
            String sourceId=enemy.getString("levelID");
            if(!sourceId.equals(Long.toString(StageCatalog.FORMER_MAZE_ENTRY)) &&
               !sourceId.equals(Long.toString(StageCatalog.MAZE_TRIAL)))
                throw new IOException("Unexpected maze encounter level ID");
            if(enemy.getJSONArray("areas").length()==0)
                throw new IOException("Maze encounter has no combat area");
            enemy.put("levelID",Long.toString(stage));
            responses.put("/combat/mob/json#"+stage,new JSONObject()
                .put("type","application/json").put("body",battle.toString()));

            JSONObject rawMob=source(responses,"/combat/mob/info",copiedSuffix,oldSuffix);
            if(!"application/octet-stream".equals(rawMob.getString("type")) ||
               Base64.decode(rawMob.getString("base64"),Base64.DEFAULT).length==0)
                throw new IOException("Maze encounter mob catalog missing");
            byte[] originalMob=Base64.decode(rawMob.getString("base64"),Base64.DEFAULT);
            byte[] balancedMob=balanceMobCatalog(originalMob);
            responses.put("/combat/mob/info#"+stage,new JSONObject()
                .put("type","application/octet-stream")
                .put("base64",Base64.encodeToString(balancedMob,Base64.NO_WRAP)));
        }
    }
    private static byte[] balanceMobCatalog(byte[] original)throws IOException{
        ProtoWire basket=ProtoWire.parse(original);
        int mobCount=0;
        for(ProtoWire.Field field:basket.fields){
            if(field.number!=5)continue; // combatmod.Basket.MobInfos
            if(field.type!=2)throw new IOException("Invalid maze MobInfo wire type");
            ProtoWire mob=ProtoWire.parse(field.data);
            long id=mob.number(6,0);
            // The offline-only 407 spawn buff makes non-critical damage 1.
            // Removing just this attachment lets a starter team damage it;
            // 406's original counterattack identity remains intact.
            long localBuff=id==331080240701L?90300071L:0;
            List<Long> spawnBuffs=mob.integers(1);
            if(localBuff!=0){
                if(spawnBuffs.size()!=1 || spawnBuffs.get(0)!=localBuff)
                    throw new IOException("Unexpected local maze spawn buff");
                mob.clear(1);
            }else if(spawnBuffs.contains(90300071L)){
                throw new IOException("Unexpected maze spawn buff owner");
            }
            int hp=0,physical=0,magical=0;
            for(ProtoWire.Field stat:mob.fields){
                int divisor;
                if(stat.number==30){divisor=MOB_HP_DIVISOR;hp++;}
                else if(stat.number==31){divisor=MOB_ATTACK_DIVISOR;physical++;}
                else if(stat.number==32){divisor=MOB_ATTACK_DIVISOR;magical++;}
                else continue;
                if(stat.type!=0 || stat.value<=0 || stat.value>Integer.MAX_VALUE)
                    throw new IOException("Invalid preserved maze combat stat");
                stat.value=Math.max(1,(stat.value+divisor-1)/divisor);
            }
            if(id<=0 || hp!=1 || physical!=1 || magical!=1)
                throw new IOException("Incomplete preserved maze MobInfo");
            field.data=mob.bytes();
            mobCount++;
        }
        if(mobCount==0)throw new IOException("Maze encounter has no MobInfos");
        return basket.bytes();
    }
    private static JSONObject source(JSONObject responses,String route,String copied,String old)
            throws IOException{
        JSONObject result=responses.optJSONObject(route+copied);
        if(result==null)result=responses.optJSONObject(route+old);
        if(result==null)throw new IOException("Preserved maze fixture missing: "+route+copied);
        return result;
    }

    private static double roleMaximumHP(byte[] roleTemplate)throws Exception{
        double[] attributes=ProtoWire.parse(roleTemplate).doubles(1);
        double value=attributes.length==0?1:attributes[0];
        return Double.isFinite(value) && value>0?value:1;
    }
    static int roleHP(JSONObject state,byte[] roleTemplate)throws Exception{
        double fallback=roleMaximumHP(roleTemplate);
        double maximum=state.optDouble("mazeRoleMaxHP",fallback);
        if(!Double.isFinite(maximum) || maximum<=0)maximum=fallback;
        double ratio=state.optDouble("mazeHP",1);
        if(!Double.isFinite(ratio))ratio=1;
        return (int)Math.max(1,Math.min(Integer.MAX_VALUE,
            Math.round(maximum*Math.max(0.01,Math.min(1,ratio)))));
    }
    static int resetsRemaining(JSONObject state,long now){
        long today=LocalDaily.day(now);
        long savedDay=state.optLong("mazeResetDay",Long.MIN_VALUE);
        int used=savedDay>=today?state.optInt("mazeResetsUsed",0):0;
        return Math.max(0,DAILY_RESETS-Math.max(0,used));
    }
    static int pendingBonus(JSONObject state)throws IOException{
        int round=state.optInt("mazePendingBonus",0);
        if(round==0)return 0; // Old saves already received their checkpoint reward.
        if(round<1 || round>STAGES.length || round%3!=0 ||
           state.optInt("mazeRound",1)!=round+1)
            throw new IOException("Invalid pending maze checkpoint");
        return round;
    }
    static byte[] info(JSONObject state,byte[] roleTemplate,long now)throws Exception{
        return info(state,roleTemplate,now,state.optInt("starterProfile",0)==1?1:5);
    }
    static byte[] info(JSONObject state,byte[] roleTemplate,long now,int roleLevel)throws Exception{
        ProtoWire info=new ProtoWire();
        // The original client requires exactly sixteen aligned entries:
        // twelve fights plus a zero-ID reward node after each third fight.
        // GetCSCInfo.ParseProtoBuf rejects both arrays unless Count == 16.
        for(int index=0;index<STAGES.length;index++){
            info.add(3,STAGES[index]);info.add(4,MazeRules.enemyLevel(roleLevel,index+1));
            if((index+1)%3==0){info.add(3,0);info.add(4,0);}
        }
        for(long servant:availableServants(state)){
            info.add(1,servant);
            info.add(2,Math.round(Math.max(0,Math.min(1000,
                state.optDouble("mazeEnergy_"+servant,1000)))));
        }
        // SetTeamPanelControl.Init treats field 7 as already selected, not as
        // the full owned candidate list. OpenSelectMyView reads its candidates
        // separately from UserInfo.ServantCore.ObservableServants.
        for(long servant:selectedGroup(state))info.add(7,servant);
        info.set(17,roleHP(state,roleTemplate));
        // The native detail panel uses this base level for a CharacterLevelInfo
        // lookup (1-100). Actual per-floor enemy levels, including 101-105,
        // are aligned in field 4 and in the encounter JSON/MobInfo payload.
        info.set(22,roleLevel);
        int round=Math.max(1,Math.min(STAGES.length+1,state.optInt("mazeRound",1)));
        // Rewards are applied with each local checkpoint. Skip their display
        // slots when reporting the next active combat position to the UI.
        int serial=round+(round-1)/3;
        if(pendingBonus(state)>0)serial--; // Chest occupies the fourth node.
        info.set(24,serial);
        info.set(25,resetsRemaining(state,now));
        info.set(27,1); // Entry is open at level 1; only reset attempts are limited.
        return info.bytes();
    }

    /** CSC group response is a CscInstance, not CommonInfo. */
    static Group group(JSONObject state,Map<String,String> args,byte[] roleTemplate,long now)
            throws Exception{
        return group(state,args,roleTemplate,now,state.optInt("starterProfile",0)==1?1:5);
    }
    static Group group(JSONObject state,Map<String,String> args,byte[] roleTemplate,long now,int roleLevel)
            throws Exception{
        String raw=args.containsKey("servantcardids")?args.get("servantcardids"):
            args.get("svcardids");
        if(raw==null)throw new IOException("Missing maze servant group");
        // The local service has no mercenary hire state. Accept the empty wire
        // values the native client sends, but never invent an unavailable hire.
        for(String key:new String[]{"mercenaryownerids","mercenarysvcardids",
                "mercenarygarrisontimes"})
            if(args.containsKey(key) && !args.get(key).isEmpty())
                throw new IOException("Maze mercenary group unavailable");
        List<Long> party=parseParty(raw);
        if(party.isEmpty())throw new IOException("Maze challenge group is empty");
        JSONObject owned=state.optJSONObject("ownedServants");
        if(owned==null && !party.isEmpty())throw new IOException("Maze servant inventory unavailable");
        for(long id:party)if(!owned.has(Long.toString(id)))
            throw new IOException("Maze party includes unowned servant");
        JSONObject next=new JSONObject(state.toString());
        migrateGroup(next);
        if(next.optBoolean("mazeRosterLocked",false) &&
            (next.optInt("mazeRound",1)>1 || next.optInt("mazePreparedRound",0)>0) &&
            !new HashSet<Long>(availableServants(next)).equals(new HashSet<Long>(party)))
            throw new IOException("Reset maze before changing the challenge group");
        next.put("mazeRoster",new JSONArray(party)).put("mazeRosterLocked",true);
        JSONArray remembered=next.optJSONArray("mazeParty");
        if(remembered!=null)for(int i=0;i<remembered.length();i++)
            if(!party.contains(remembered.getLong(i))){next.remove("mazeParty");break;}
        return new Group(next,info(next,roleTemplate,now,roleLevel));
    }
    private static List<Long> parseParty(String raw)throws IOException{
        ArrayList<Long> result=new ArrayList<Long>();
        if(raw.isEmpty())return result;
        Set<Long> unique=new HashSet<Long>();
        for(String token:raw.split("[|,]",-1)){
            if(!token.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid maze servant group");
            long id;
            try{id=Long.parseLong(token);}catch(NumberFormatException ex){
                throw new IOException("Invalid maze servant group",ex);
            }
            if(!unique.add(id))throw new IOException("Duplicate maze servant group member");
            result.add(id);
            if(result.size()>12)throw new IOException("Maze party exceeds original twelve-servant limit");
        }
        return result;
    }

    /** Version-zero mazeParty mixed a challenge group and a single battle team. */
    static void migrateGroup(JSONObject state)throws Exception{
        if(state.optInt("mazeGroupVersion",0)>=1)return;
        JSONArray old=state.optJSONArray("mazeParty");
        if(old!=null && old.length()>4){
            state.put("mazeRoster",new JSONArray(old.toString())).put("mazeRosterLocked",true);
            state.remove("mazeParty");
        }else state.put("mazeRosterLocked",false);
        state.put("mazeGroupVersion",1);
    }
    static List<Long> availableServants(JSONObject state)throws Exception{
        ArrayList<Long> result=new ArrayList<Long>();
        JSONArray roster=state.optJSONArray("mazeRoster");
        if(state.optBoolean("mazeRosterLocked",false) && roster!=null){
            for(int i=0;i<roster.length();i++)result.add(roster.getLong(i));
        }else{
            JSONObject owned=state.optJSONObject("ownedServants");
            if(owned!=null)for(Iterator<String> it=owned.keys();it.hasNext();)result.add(Long.parseLong(it.next()));
            Collections.sort(result);
        }
        return result;
    }
    static List<Long> selectedGroup(JSONObject state)throws Exception{
        List<Long> available=availableServants(state);
        if(state.optBoolean("mazeRosterLocked",false))return available;
        // Native field-7 members are confirmed/locked. An initial automatic
        // twelve would leave no room to add owned candidates or confirm.
        return Collections.emptyList();
    }
    static List<Long> selectBattleParty(JSONObject state,String raw)throws Exception{
        List<Long> party;
        if(raw==null || raw.isEmpty()){
            JSONArray remembered=state.optJSONArray("mazeParty");
            party=new ArrayList<Long>();
            if(remembered!=null)for(int i=0;i<remembered.length();i++)party.add(remembered.getLong(i));
            if(party.isEmpty()){
                List<Long> available=availableServants(state);
                party.addAll(available.subList(0,Math.min(3,available.size())));
            }
        }else party=parseParty(raw);
        if(party.isEmpty() || party.size()>4)throw new IOException("Maze battle requires one to four servants");
        List<Long> available=availableServants(state);
        JSONObject owned=state.getJSONObject("ownedServants");
        for(long id:party)if(!available.contains(id) || !owned.has(Long.toString(id)))
            throw new IOException("Maze battle servant outside challenge group");
        if(!state.optBoolean("mazeRosterLocked",false)){
            // Compatibility for older clients that prepare a battle before
            // posting the twelve-card group: retain a full challenge pool.
            ArrayList<Long> roster=new ArrayList<Long>(party);
            for(long id:available)if(!roster.contains(id) && roster.size()<12)roster.add(id);
            state.put("mazeRoster",new JSONArray(roster)).put("mazeRosterLocked",true);
        }
        state.put("mazeParty",new JSONArray(party));return party;
    }

    static byte[] dynamicJson(byte[] original,int level)throws Exception{
        JSONObject battle=new JSONObject(new String(original,java.nio.charset.StandardCharsets.UTF_8));
        JSONObject enemy=battle.getJSONObject("EnemyLayer");
        enemy.put("lvMin",level).put("lvMax",level);
        retargetStatIds(enemy,level);
        return battle.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
    }
    private static void retargetStatIds(Object node,int level)throws Exception{
        if(node instanceof JSONArray){
            JSONArray array=(JSONArray)node;
            for(int i=0;i<array.length();i++)retargetStatIds(array.get(i),level);
        }else if(node instanceof JSONObject){
            JSONObject object=(JSONObject)node;
            for(Iterator<String> it=object.keys();it.hasNext();){
                String key=it.next();Object value=object.get(key);
                if(key.equals("statID")){
                    String raw=object.getString(key);
                    if(!raw.matches("[1-9][0-9]*-[123]-[1-9][0-9]*"))
                        throw new IOException("Invalid preserved maze stat ID");
                    object.put(key,raw.substring(0,raw.lastIndexOf('-')+1)+level);
                }else retargetStatIds(value,level);
            }
        }
    }
    static byte[] dynamicMob(byte[] original,int level)throws Exception{
        ProtoWire basket=ProtoWire.parse(original);
        Map<Long,ProtoWire> types=new java.util.HashMap<Long,ProtoWire>();
        for(ProtoWire.Field field:basket.fields)if(field.number==6 && field.type==2){
            ProtoWire type=ProtoWire.parse(field.data);types.put(type.number(1,0),type);
        }
        int count=0;
        for(ProtoWire.Field field:basket.fields)if(field.number==5 && field.type==2){
            ProtoWire mob=ProtoWire.parse(field.data);
            int oldLevel=(int)mob.number(3,0),rank=(int)mob.number(4,0);
            ProtoWire type=types.get(mob.number(25+rank,0));
            if(rank<1 || rank>3 || type==null)throw new IOException("Missing maze mob growth type");
            for(ProtoWire.Field stat:mob.fields)if(stat.number>=30 && stat.number<=34){
                if(stat.type!=0 || stat.value<0)throw new IOException("Invalid maze combat stat");
                int slot=(int)type.number(stat.number==30?7:stat.number<=32?8:9,-1);
                double ratio=MazeRules.growth(level,slot)/MazeRules.growth(oldLevel,slot);
                stat.value=Math.min(Integer.MAX_VALUE,Math.round(stat.value*ratio));
            }
            mob.set(3,level);field.data=mob.bytes();count++;
        }
        if(count==0)throw new IOException("Maze mob catalog empty");
        return basket.bytes();
    }

    static void requireCurrentStage(JSONObject state,String requested)throws IOException{
        if(pendingBonus(state)>0)throw new IOException("Maze checkpoint must be claimed first");
        if(!Long.toString(stageForRound(state.optInt("mazeRound",1))).equals(requested))
            throw new IOException("Unexpected maze settlement stage");
    }
    static void requireRoleStage(JSONObject state,Map<String,String> args)throws IOException{
        if(pendingBonus(state)>0)throw new IOException("Maze checkpoint must be claimed first");
        // Original GetCSCRoleInfo sends NetMsgField.instid. Older local tests
        // constructed an empty form, so only validate when the field is sent.
        if(args.containsKey("instid"))requireCurrentStage(state,args.get("instid"));
    }
    static void recordVictory(JSONObject state,int round)throws Exception{
        stageForRound(round);
        state.put("mazeBestCleared",Math.max(round,state.optInt("mazeBestCleared",0)));
        if(round==STAGES.length)
            state.put("mazeCompletedRuns",state.optInt("mazeCompletedRuns",0)+1);
    }
    static JSONObject reset(JSONObject state,long now)throws Exception{
        if(state.optBoolean("active",false))throw new IOException("Cannot reset during battle");
        if(pendingBonus(state)>0)throw new IOException("Claim maze checkpoint before reset");
        if(resetsRemaining(state,now)==0)throw new IOException("No maze resets remaining today");
        JSONObject next=new JSONObject(state.toString());
        next.put("mazeBestCleared",Math.max(next.optInt("mazeBestCleared",0),
            Math.max(0,Math.min(STAGES.length,next.optInt("mazeRound",1)-1))));
        next.put("mazeResetDay",LocalDaily.day(now));
        next.put("mazeResetsUsed",state.optLong("mazeResetDay",Long.MIN_VALUE)>=LocalDaily.day(now)?
            state.optInt("mazeResetsUsed",0)+1:1);
        next.put("mazeRuns",next.optInt("mazeRuns",0)+1);
        next.put("mazeRound",1).put("mazeHP",1);
        next.remove("mazeRoster");next.remove("mazeParty");
        next.put("mazeGroupVersion",1).put("mazeRosterLocked",false);
        next.remove("mazePreparedRoleLevel");next.remove("mazePreparedEnemyLevel");
        next.remove("battleMazeRound");next.remove("mazeRoleMaxHP");
        next.remove("mazePreparedRound");next.remove("mazeRoundSettled");
        next.remove("lastCscCommitIdentity");next.remove("lastCscCommitResponse");
        next.remove("mazeLastBonusRound");next.remove("mazeLastBonusResponse");
        ArrayList<String> energy=new ArrayList<String>();
        for(Iterator<String> it=next.keys();it.hasNext();){
            String key=it.next();if(key.startsWith("mazeEnergy_"))energy.add(key);
        }
        for(String key:energy)next.remove(key);
        return next;
    }
}
