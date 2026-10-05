package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

/** CN/25 permanent achievements (quest_type 1) and guide tasks (type 5). */
final class ProgressionTasks {
    private static final int MAX_KILL_STAT_LENGTH=8192,MAX_KILL_STAT_ROWS=256;
    private static final long MAX_KILLS_PER_BATTLE=10000;
    private static ProgressionTasks singleton;
    private final JSONArray tasks;
    private final Map<Long,JSONObject> byId=new HashMap<Long,JSONObject>();

    private ProgressionTasks(JSONObject source)throws Exception{
        if(source.getInt("schemaVersion")!=1)throw new IOException("Unknown task catalog");
        tasks=source.getJSONArray("tasks");
        if(tasks.length()!=92)throw new IOException("Incomplete original permanent task catalog");
        int achievement=0,guide=0;
        for(int i=0;i<tasks.length();i++){
            JSONObject task=tasks.getJSONObject(i);long id=task.getLong("id");
            int category=task.getInt("questType");
            if(category==1)achievement++;
            else if(category==5)guide++;
            else throw new IOException("Unexpected permanent quest type");
            if(byId.put(id,task)!=null)throw new IOException("Duplicate permanent task ID");
        }
        if(achievement!=50||guide!=42)throw new IOException("Incomplete original quest types");
    }
    static synchronized ProgressionTasks bundled()throws Exception{
        if(singleton!=null)return singleton;
        InputStream input=ProgressionTasks.class.getResourceAsStream("/progression_tasks_catalog.json");
        if(input==null)throw new IOException("Original permanent task catalog missing");
        try{
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int n;
            while((n=input.read(buffer))!=-1)bytes.write(buffer,0,n);
            singleton=new ProgressionTasks(new JSONObject(new String(bytes.toByteArray(),"UTF-8")));
            return singleton;
        }finally{input.close();}
    }
    private static JSONObject claims(JSONObject state)throws Exception{
        JSONObject result=state.optJSONObject("progressionTaskClaims");
        if(result==null){result=new JSONObject();state.put("progressionTaskClaims",result);}
        return result;
    }
    /** The two weapon achievements were formerly served by CosmeticAchievements. */
    static boolean permanentClaimed(JSONObject state,long id){
        String key=Long.toString(id);
        JSONObject claimed=state.optJSONObject("progressionTaskClaims");
        if(claimed!=null&&claimed.optBoolean(key,false))return true;
        JSONObject old=state.optJSONObject("cosmeticAchievementClaims");
        return (id==501060001L||id==501060002L)&&old!=null&&old.optBoolean(key,false);
    }
    private static boolean predecessorClaimed(JSONObject state,JSONObject claimed,long id){
        if(id==0||claimed.optBoolean(Long.toString(id),false)||permanentClaimed(state,id))return true;
        String key=Long.toString(id);
        for(String ledger:new String[]{"mainStoryTaskClaims","cosmeticAchievementClaims"}){
            JSONObject other=state.optJSONObject(ledger);
            if(other!=null&&other.optBoolean(key,false))return true;
        }
        JSONObject guide=state.optJSONObject("tutorialTasks");
        return guide!=null&&guide.optInt(key,-1)==1;
    }
    private static long roleLevel(JSONObject state,JSONObject catalog){
        long level=state.optInt("starterProfile",0)==1?1:5;
        long exp=state.optLong("exp",0);
        JSONObject costs=catalog.optJSONObject("roleLevels");
        while(costs!=null&&level<100){
            long cost=costs.optLong(Long.toString(level),Long.MAX_VALUE);
            if(cost<=0||exp<cost)break;
            exp-=cost;level++;
        }
        return level;
    }
    private static int countServants(JSONObject state,int field,long minimum)throws Exception{
        JSONObject owned=state.optJSONObject("ownedServants");if(owned==null)return 0;
        int count=0;
        for(Iterator<String> it=owned.keys();it.hasNext();){
            ProtoWire servant=LocalEconomy.decode(owned.getString(it.next()));
            if(servant.number(field,0)>=minimum)count++;
        }
        return count;
    }
    private static int countWeapons(JSONObject state,long awakened)throws Exception{
        JSONObject owned=state.optJSONObject("ownedServants");if(owned==null)return 0;
        Set<Long> weapons=new HashSet<Long>();
        for(Iterator<String> it=owned.keys();it.hasNext();){
            ProtoWire servant=LocalEconomy.decode(owned.getString(it.next()));
            for(ProtoWire.Field field:servant.fields)if(field.number==13&&field.type==2){
                ProtoWire weapon=ProtoWire.parse(field.data);long id=weapon.number(1,0);
                // Svmod.WeaponInstance field 4 is WeaponSpellPromoteLv;
                // the original type-062 threshold 2 denotes awakening.
                if(id>0&&(awakened<=0||weapon.number(4,0)>=awakened))weapons.add(id);
            }
        }
        return weapons.size();
    }
    private static long progress(JSONObject state,JSONObject catalog,JSONObject task,
                                 JSONObject claimed)throws Exception{
        String type=task.getString("type");long target=task.optLong("arg1",0),arg2=task.optLong("arg2",0);
        if(type.equals("001"))return roleLevel(state,catalog);
        if(type.equals("010"))return countServants(state,2,1);
        if(type.equals("011"))return countServants(state,2,arg2);
        if(type.equals("012"))return countServants(state,4,arg2);
        if(type.equals("013"))return countServants(state,5,arg2);
        if(type.equals("014"))return countServants(state,9,arg2);
        if(type.equals("060"))return countServants(state,12,arg2);
        if(type.equals("062"))return countWeapons(state,arg2);
        if(type.equals("065"))return countWeapons(state,0);
        if(type.equals("021")){
            long stage=task.optLong("arg3",0);
            long wins=TaskStageProgress.wins(state,stage);
            return wins>0?wins:stage==3110001002L?Math.max(0,state.optLong("wins",0)):0;
        }
        if(type.equals("007"))return task.optLong("arg3",0)>0&&
            predecessorClaimed(state,claimed,task.optLong("arg3",0))?1:0;
        if(type.equals("043"))return state.optLong("mainlineStaminaSpent",0);
        if(type.equals("022")&&arg2==3)return LocalDaily.mainlineClears(state,3);
        if(type.equals("042"))return Math.max(state.optLong("staminaPurchasesTotal",0),
            Math.max(0,state.optLong("staminaPurchaseUsed",0)));
        if(type.equals("070"))return state.optBoolean("guildJoined",false)?1:0;
        if(type.equals("100"))return Math.max(0,state.optLong("enemyKillsTotal",0));
        // Support hiring and being hired have no authoritative transaction
        // counters yet. Show their configured rows without inventing progress.
        return 0;
    }
    private static boolean supported(JSONObject task){
        String type=task.optString("type","");
        return type.equals("001")||type.equals("010")||type.equals("011")||
            type.equals("012")||type.equals("013")||type.equals("014")||
            type.equals("021")||type.equals("060")||type.equals("062")||type.equals("065")||
            type.equals("007")||type.equals("043")||type.equals("022")||
            type.equals("042")||type.equals("070")||type.equals("100");
    }
    private static boolean ready(JSONObject state,JSONObject catalog,JSONObject task,
                                 JSONObject claimed)throws Exception{
        if(!state.optBoolean("roleCreated",false)||!supported(task))return false;
        long front=task.optLong("front",0);
        if(!predecessorClaimed(state,claimed,front))return false;
        long target=task.optLong("arg1",0);
        return target>0&&progress(state,catalog,task,claimed)>=target;
    }
    /** Call only for successful mainline battle/sweep mutations, before save commit. */
    static void recordMainlineStaminaSpent(JSONObject before,JSONObject after)throws Exception{
        long spent=Math.max(0,before.optLong("stamina",0)-after.optLong("stamina",0));
        if(spent>0)after.put("mainlineStaminaSpent",
            Math.addExact(after.optLong("mainlineStaminaSpent",0),spent));
    }
    /** Call after a successful purchase; the existing daily ledger proves the increment. */
    static void recordStaminaPurchase(JSONObject before,JSONObject after)throws Exception{
        long oldUsed=Math.max(0,before.optLong("staminaPurchaseUsed",0));
        long newUsed=Math.max(0,after.optLong("staminaPurchaseUsed",0));
        long added=before.optLong("staminaPurchaseDay",Long.MIN_VALUE)==
            after.optLong("staminaPurchaseDay",Long.MIN_VALUE)?Math.max(0,newUsed-oldUsed):newUsed;
        if(added>0)after.put("staminaPurchasesTotal",Math.addExact(
            Math.max(before.optLong("staminaPurchasesTotal",0),oldUsed),added));
    }
    /** A verified current membership also proves the original one-time join achievement. */
    static void recordGuildMembership(JSONObject state)throws Exception{state.put("guildJoined",true);}
    /** Record only inside a newly accepted battle settlement, never on a replay or sweep.
     * Original MonsterEntity.ExecDeath (0x3E76C14) counts ID=powerRank in
     * BattleData.entityIDs; CombinDic (0x12C8490) sends killed as
     * monsterID=powerRank=count|... . Optional malformed telemetry must not
     * reject a legitimate settlement or turn a partial parse into progress.
     */
    static void recordBattleKills(JSONObject state,Map<String,String> args)throws Exception{
        String raw=args.get("killed");
        if(raw==null||raw.isEmpty()||raw.equals("0")||raw.length()>MAX_KILL_STAT_LENGTH)return;
        String[] rows=raw.split("\\|",-1);
        if(rows.length>MAX_KILL_STAT_ROWS)return;
        Set<String> keys=new HashSet<String>();long total=0;
        for(String row:rows){
            // The preserved monster table uses twelve-digit IDs in namespaces 331/332.
            // Unrecognized namespaces and non-native separators are ignored.
            if(!row.matches("33[12][0-9]{9}=[1-3]=[1-9][0-9]{0,4}"))return;
            int last=row.lastIndexOf('=');
            if(!keys.add(row.substring(0,last)))return;
            long count=Long.parseLong(row.substring(last+1));
            if(count>MAX_KILLS_PER_BATTLE-total)return;
            total+=count;
        }
        long previous=Math.max(0,state.optLong("enemyKillsTotal",0));
        state.put("enemyKillsTotal",previous>Long.MAX_VALUE-total?Long.MAX_VALUE:previous+total);
    }
    byte[] taskList(JSONObject state,JSONObject catalog,byte[] seed)throws Exception{
        return list(state,catalog,seed,false);
    }
    /** /achievement/all is a separate Achievemod.Result in the original client.
     * Native GetAllAchieve.ParseProtoBuf (0x3F08168) uses Result.Parser.
     * GetAchiveByProtobuf (0x3F7C654) converts MetaInfo.Meta (int, field 4)
     * to one string in AchievementMeta.Args; Args is not its wire schema.
     */
    byte[] achievementList(JSONObject state,JSONObject catalog,byte[] seed)throws Exception{
        return list(state,catalog,seed,true);
    }
    private byte[] list(JSONObject state,JSONObject catalog,byte[] seed,boolean achievementsOnly)
            throws Exception{
        ProtoWire result=ProtoWire.parse(seed);
        JSONObject claimed=state.optJSONObject("progressionTaskClaims");
        if(claimed==null)claimed=new JSONObject();
        // Refresh rows already present in an older fixture or cosmetic list.
        // Keeping the seed's status would leave real claims looking unfinished.
        for(Iterator<ProtoWire.Field> it=result.fields.iterator();it.hasNext();){
            ProtoWire.Field field=it.next();
            if((field.number==1||field.number==2)&&field.type==2){
                long id=ProtoWire.parse(field.data).number(field.number==1?1:3,0);
                if(achievementsOnly||byId.containsKey(id))it.remove();
            }
        }
        for(int i=0;i<tasks.length();i++){
            JSONObject task=tasks.getJSONObject(i);long id=task.getLong("id");
            if(achievementsOnly&&task.getInt("questType")!=1)continue;
            int status=permanentClaimed(state,id)?1:
                ready(state,catalog,task,claimed)?0:-1;
            long progress=Math.max(0,progress(state,catalog,task,claimed));
            result.add(1,new ProtoWire().set(1,id).set(2,status).set(3,1)
                .text(4,task.getString("type")).bytes());
            result.add(2,new ProtoWire().set(1,task.getInt("questType"))
                .text(2,task.getString("type")).set(3,id)
                .set(4,Math.min(task.optLong("arg1",0),progress)).bytes());
        }
        return result.bytes();
    }
    private static byte[] rewardWire(JSONObject task)throws Exception{
        ProtoWire loot=new ProtoWire();JSONArray rewards=task.getJSONArray("rewards");
        for(int i=0;i<rewards.length();i++){
            JSONObject reward=rewards.getJSONObject(i);
            int type=reward.getInt("type");long id=reward.getLong("id");
            long amount=reward.optLong("count",0)>0?reward.getLong("count"):
                reward.optLong("value",0);
            ProtoWire item=new ProtoWire().set(1,type);
            if(id>0)item.set(2,id);
            if(type==2||type==3)item.set(4,amount);
            else item.set(3,amount).set(4,amount);
            loot.add(1,item.bytes());
        }
        return loot.bytes();
    }
    boolean handlesJob(String raw){
        if(raw==null||!raw.matches("[1-9][0-9]{0,18}"))return false;
        try{return byId.containsKey(Long.parseLong(raw));}
        catch(NumberFormatException e){return false;}
    }
    boolean handlesAchievement(String raw){
        return handlesJob(raw)&&byId.get(Long.parseLong(raw)).optInt("questType",0)==1;
    }
    byte[] claimAchievement(JSONObject state,JSONObject catalog,Map<String,String> args)
            throws Exception{
        String raw=args.get("jobid");
        if(!handlesAchievement(raw))throw new IOException("Unknown permanent achievement");
        String type=args.get("type");
        if(type!=null&&(!type.matches("[0-9]{1,3}")||Integer.parseInt(type)!=
                Integer.parseInt(byId.get(Long.parseLong(raw)).getString("type"))))
            throw new IOException("Wrong achievement type");
        return claim(state,catalog,args);
    }
    byte[] claim(JSONObject state,JSONObject catalog,Map<String,String> args)throws Exception{
        LocalDaily.requireRole(state,args);
        String raw=args.get("jobid");
        if(!handlesJob(raw))throw new IOException("Unknown permanent task");
        JSONObject task=byId.get(Long.parseLong(raw));
        JSONObject claimed=claims(state);
        if(permanentClaimed(state,task.getLong("id"))){
            // Preserve the old cosmetic claim and adopt it into the canonical
            // ledger without granting either currency or Kanban a second time.
            claimed.put(raw,true);
            return rewardWire(task);
        }
        if(!ready(state,catalog,task,claimed))throw new IOException("Permanent task incomplete");
        LocalEconomy.init(state,catalog);
        JSONArray rewards=task.getJSONArray("rewards");boolean inventory=false;
        for(int i=0;i<rewards.length();i++){
            JSONObject reward=rewards.getJSONObject(i);
            LocalEconomy.grantItemReward(state,catalog,reward,1);
            if(reward.getInt("type")==2||reward.getInt("type")==3)inventory=true;
        }
        if(inventory)state.put("inventoryRevision",
            Math.addExact(state.optLong("inventoryRevision",0),1));
        claimed.put(raw,true);
        return rewardWire(task);
    }
}
