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

/** The original shared-channel quest_type=6 StoryQuest entries. */
final class MainStoryTasks {
    private static MainStoryTasks singleton;
    private final JSONArray tasks;
    private final Map<Long,JSONObject> byId=new HashMap<Long,JSONObject>();

    private MainStoryTasks(JSONObject source)throws Exception{
        if(source.getInt("schemaVersion")!=1 ||
           !"f0165092dd04ca8b1dff6b232a6f42b258276da10685db67a35a93c854c10a90"
               .equals(source.getString("sourceSha256")))
            throw new IOException("Unexpected original main story task catalog");
        tasks=source.getJSONArray("tasks");
        if(tasks.length()!=106)throw new IOException("Incomplete original main story tasks");
        int delegated=0;
        Set<Long> ids=new HashSet<Long>();
        for(int i=0;i<tasks.length();i++){
            JSONObject task=tasks.getJSONObject(i);long id=task.getLong("id");
            if(task.getInt("questType")!=6 || !ids.add(id))
                throw new IOException("Duplicate or non-story task in original catalog");
            if(CosmeticAchievements.handlesJob(Long.toString(id)))delegated++;
            else {
                String type=task.getString("type");
                if(!type.equals("012")&&!type.equals("013")&&
                   !type.equals("021")&&!type.equals("023"))
                    throw new IOException("Unsupported original story task type");
                byId.put(id,task);
            }
        }
        if(delegated!=17||byId.size()!=89)
            throw new IOException("Unexpected original story delegation count");
        for(int i=0;i<tasks.length();i++){
            JSONObject task=tasks.getJSONObject(i);
            for(String key:new String[]{"front","next"}){
                long related=task.optLong(key,0);
                if(related>0&&!ids.contains(related))
                    throw new IOException("Story task chain is incomplete");
            }
        }
    }

    static synchronized MainStoryTasks bundled()throws Exception{
        if(singleton!=null)return singleton;
        InputStream input=MainStoryTasks.class.getResourceAsStream("/main_story_tasks_catalog.json");
        if(input==null)throw new IOException("Original main story task catalog missing");
        try{
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            byte[] buffer=new byte[4096];int n;
            while((n=input.read(buffer))!=-1)bytes.write(buffer,0,n);
            singleton=new MainStoryTasks(new JSONObject(new String(bytes.toByteArray(),"UTF-8")));
            return singleton;
        }finally{input.close();}
    }

    private static JSONObject claims(JSONObject state)throws Exception{
        JSONObject result=state.optJSONObject("mainStoryTaskClaims");
        if(result==null){result=new JSONObject();state.put("mainStoryTaskClaims",result);}
        return result;
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

    private static long progress(JSONObject state,JSONObject task)throws Exception{
        String type=task.getString("type");long arg2=task.optLong("arg2",0);
        if(type.equals("012"))return countServants(state,4,arg2);
        if(type.equals("013"))return countServants(state,5,arg2);
        if(type.equals("021")){
            return TaskStageProgress.wins(state,task.getLong("arg3"));
        }
        if(type.equals("023"))return state.optLong("mazeBestCleared",0);
        throw new IOException("Unsupported main story task type");
    }

    private static boolean predecessorClaimed(JSONObject state,JSONObject claims,long id){
        if(id==0)return true;
        if(claims.optBoolean(Long.toString(id),false))return true;
        JSONObject cosmetic=state.optJSONObject("cosmeticAchievementClaims");
        return cosmetic!=null&&cosmetic.optBoolean(Long.toString(id),false);
    }

    private static boolean ready(JSONObject state,JSONObject task,JSONObject claimed)throws Exception{
        if(!state.optBoolean("roleCreated",false)||
           !predecessorClaimed(state,claimed,task.optLong("front",0)))return false;
        long target=task.optLong("arg1",0);
        return target>0&&progress(state,task)>=target;
    }

    byte[] taskList(JSONObject state,byte[] seed)throws Exception{
        ProtoWire result=ProtoWire.parse(seed);
        JSONObject claimed=state.optJSONObject("mainStoryTaskClaims");
        if(claimed==null)claimed=new JSONObject();
        Set<Long> existing=new HashSet<Long>();
        for(ProtoWire.Field field:result.fields)if(field.number==1&&field.type==2)
            existing.add(ProtoWire.parse(field.data).number(1,0));
        for(int i=0;i<tasks.length();i++){
            JSONObject task=tasks.getJSONObject(i);long id=task.getLong("id");
            if(!byId.containsKey(id)||existing.contains(id))continue;
            long target=task.optLong("arg1",0),value=Math.max(0,progress(state,task));
            int status=claimed.optBoolean(Long.toString(id),false)?1:
                ready(state,task,claimed)?0:-1;
            result.add(1,new ProtoWire().set(1,id).set(2,status).set(3,1)
                .text(4,task.getString("type")).bytes());
            result.add(2,new ProtoWire().set(1,6).text(2,task.getString("type"))
                .set(3,id).set(4,Math.min(target,value)).bytes());
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

    byte[] claim(JSONObject state,JSONObject catalog,Map<String,String> args)throws Exception{
        LocalDaily.requireRole(state,args);
        String raw=args.get("jobid");
        if(!handlesJob(raw))throw new IOException("Unknown main story task");
        JSONObject task=byId.get(Long.parseLong(raw));
        JSONObject claimed=claims(state);
        if(claimed.optBoolean(raw,false))return rewardWire(task);
        if(!ready(state,task,claimed))throw new IOException("Main story task incomplete");
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
