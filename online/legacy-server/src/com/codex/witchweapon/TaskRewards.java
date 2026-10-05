package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Original BatchUpdateQuest: explicit job IDs and parallel achievement types.
 * The caller supplies a save clone and commits it only after this method returns.
 */
final class TaskRewards {
    private static final int MAX_JOBS = 128;
    private static final int MAX_RECEIPTS = 32;
    // Clear this ledger whenever the corresponding task claim ledgers are reset.
    private static final String RECEIPTS = "taskBatchReceipts";

    private static final class Request {
        final String[] ids,types;
        final String identity;
        Request(String[] ids,String[] types,String identity){
            this.ids=ids;this.types=types;this.identity=identity;
        }
    }
    private static final class Job {
        int status,questType;
        String type;
        boolean hasMeta;
    }

    private TaskRewards(){}

    private static String[] tokens(String raw,String name)throws LocalDaily.InvalidRequest{
        if(raw==null||raw.trim().isEmpty()||raw.length()>4096)
            throw new LocalDaily.InvalidRequest("Batch needs explicit "+name);
        // Preserved BatchUpdateQuest uses ListAndSplitTagToString(..., '|').
        // Keep the earlier comma form for tools, but reject mixed separators.
        if(raw.indexOf('|')>=0&&raw.indexOf(',')>=0)
            throw new LocalDaily.InvalidRequest("Mixed task separators");
        String[] result=raw.trim().split(raw.indexOf('|')>=0?"\\|":",",-1);
        if(result.length==0||result.length>MAX_JOBS)
            throw new LocalDaily.InvalidRequest("Task batch too large");
        for(int i=0;i<result.length;i++)result[i]=result[i].trim();
        return result;
    }

    private static String achievementType(String raw)throws LocalDaily.InvalidRequest{
        if(raw==null||!raw.matches("[0-9]{1,3}"))
            throw new LocalDaily.InvalidRequest("Invalid achievement type");
        int value=Integer.parseInt(raw);
        if(value==0)throw new LocalDaily.InvalidRequest("Invalid achievement type");
        return Integer.toString(value);
    }

    private static Request request(Map<String,String> args)throws LocalDaily.InvalidRequest{
        // The native batch message uses plural names; individual UpdateQuest
        // uses jobid/typeid. Accept the old tool form only when unambiguous.
        if(args.containsKey("jobids")&&args.containsKey("jobid")||
                args.containsKey("typeids")&&args.containsKey("typeid"))
            throw new LocalDaily.InvalidRequest("Ambiguous batch task fields");
        String rawIds=args.get(args.containsKey("jobids")?"jobids":"jobid"),
            rawTypes=args.get(args.containsKey("typeids")?"typeids":"typeid");
        String[] ids=tokens(rawIds,"jobids"),types=tokens(rawTypes,"typeids");
        if(ids.length!=types.length)
            throw new LocalDaily.InvalidRequest("Batch jobid/typeid lengths differ");
        if(ids.length>1&&(rawIds.indexOf('|')>=0)!=(rawTypes.indexOf('|')>=0))
            throw new LocalDaily.InvalidRequest("Batch separators differ");
        Set<String> seen=new HashSet<String>();
        StringBuilder identity=new StringBuilder();
        for(int i=0;i<ids.length;i++){
            if(!ids[i].matches("[1-9][0-9]{0,18}"))
                throw new LocalDaily.InvalidRequest("Invalid batch jobid");
            try{Long.parseLong(ids[i]);}
            catch(NumberFormatException e){
                throw new LocalDaily.InvalidRequest("Invalid batch jobid");
            }
            if(!seen.add(ids[i]))throw new LocalDaily.InvalidRequest("Duplicate batch jobid");
            types[i]=achievementType(types[i]);
            if(i>0)identity.append(',');
            identity.append(ids[i]).append(':').append(types[i]);
        }
        return new Request(ids,types,identity.toString());
    }

    private static Map<String,Job> snapshot(JSONObject state,JSONObject catalog,long now)
            throws Exception{
        byte[] result=LocalDaily.taskList(state,new byte[0],now);
        result=CosmeticAchievements.taskList(state,catalog,result);
        result=MainStoryTasks.bundled().taskList(state,result);
        Map<String,Job> jobs=new HashMap<String,Job>();
        ProtoWire wire=ProtoWire.parse(result);
        for(ProtoWire.Field field:wire.fields)if(field.number==1&&field.type==2){
            ProtoWire row=ProtoWire.parse(field.data);
            String id=Long.toString(row.number(1,0));
            Job job=new Job();job.status=(int)row.number(2,-1);
            job.type=achievementType(new String(row.data(4),StandardCharsets.UTF_8));
            if(jobs.put(id,job)!=null)
                throw new LocalDaily.InvalidRequest("Duplicate authoritative task");
        }
        for(ProtoWire.Field field:wire.fields)if(field.number==2&&field.type==2){
            ProtoWire row=ProtoWire.parse(field.data);
            Job job=jobs.get(Long.toString(row.number(3,0)));
            if(job==null)continue;
            String type=achievementType(new String(row.data(2),StandardCharsets.UTF_8));
            if(job.hasMeta||!job.type.equals(type))
                throw new LocalDaily.InvalidRequest("Invalid authoritative task meta");
            job.questType=(int)row.number(1,0);job.hasMeta=true;
        }
        return jobs;
    }

    private static byte[] replay(JSONObject state,Request request,long today)throws Exception{
        JSONArray receipts=state.optJSONArray(RECEIPTS);
        if(receipts==null)return null;
        for(int i=receipts.length()-1;i>=0;i--){
            JSONObject receipt=receipts.optJSONObject(i);
            if(receipt==null||!request.identity.equals(receipt.optString("request","")))continue;
            int category=receipt.optInt("questType",0);
            if(category!=6&&(category!=2||receipt.optLong("day",Long.MIN_VALUE)!=today))continue;
            return Base64.decode(receipt.getString("response"),Base64.DEFAULT);
        }
        return null;
    }

    private static void remember(JSONObject state,Request request,int category,long today,
                                 byte[] response)throws Exception{
        JSONArray existing=state.optJSONArray(RECEIPTS),kept=new JSONArray();
        if(existing!=null)for(int i=0;i<existing.length();i++){
            JSONObject receipt=existing.optJSONObject(i);
            if(receipt==null)continue;
            int kind=receipt.optInt("questType",0);
            if(kind==6||kind==2&&receipt.optLong("day",Long.MIN_VALUE)==today)kept.put(receipt);
        }
        JSONObject receipt=new JSONObject().put("request",request.identity)
            .put("questType",category)
            .put("response",Base64.encodeToString(response,Base64.NO_WRAP));
        if(category==2)receipt.put("day",today);
        kept.put(receipt);
        JSONArray bounded=new JSONArray();
        for(int i=Math.max(0,kept.length()-MAX_RECEIPTS);i<kept.length();i++)
            bounded.put(kept.getJSONObject(i));
        state.put(RECEIPTS,bounded);
    }

    static byte[] claimBatch(JSONObject state,JSONObject catalog,Map<String,String> args,
                             long now,boolean verifiedGuildMember)throws Exception{
        LocalDaily.requireRole(state,args);
        Request requested=request(args);
        long today=LocalDaily.day(now);
        byte[] previous=replay(state,requested,today);
        if(previous!=null)return previous;

        // Validate the entire batch before any claim. A reward can unlock its
        // successor, but that successor belongs to the next native button click.
        Map<String,Job> jobs=snapshot(state,catalog,now);
        int category=0;
        for(int i=0;i<requested.ids.length;i++){
            Job job=jobs.get(requested.ids[i]);
            if(job==null||!job.hasMeta||job.questType!=2&&job.questType!=6)
                throw new LocalDaily.InvalidRequest("Unsupported batch task");
            if(!requested.types[i].equals(job.type))
                throw new LocalDaily.InvalidRequest("Wrong batch achievement type");
            if(category!=0&&category!=job.questType)
                throw new LocalDaily.InvalidRequest("Mixed task categories in batch");
            category=job.questType;
            if(job.status!=0)throw new LocalDaily.Conflict("Batch task is not ready");
            if(job.questType==2&&!LocalDaily.dailyTask(requested.ids[i])||
               job.questType==6&&!CosmeticAchievements.handlesJob(requested.ids[i])&&
                   !MainStoryTasks.bundled().handlesJob(requested.ids[i]))
                throw new LocalDaily.InvalidRequest("Task claim handler unavailable");
        }

        ProtoWire combined=new ProtoWire();
        for(int i=0;i<requested.ids.length;i++){
            Map<String,String> single=new HashMap<String,String>(args);
            single.put("jobid",requested.ids[i]);single.put("typeid",requested.types[i]);
            byte[] response;
            if(category==2)
                response=LocalDaily.claimTask(state,catalog,single,now,verifiedGuildMember);
            else if(CosmeticAchievements.handlesJob(requested.ids[i]))
                response=CosmeticAchievements.claim(state,catalog,single);
            else response=MainStoryTasks.bundled().claim(state,catalog,single);
            // Native LootList.Parse already aggregates resource Value and item
            // Num. Preserve each original LootObject without multiplying either.
            for(ProtoWire.Field field:ProtoWire.parse(response).fields)
                if(field.number==1&&field.type==2)combined.add(1,field.data);
        }
        byte[] response=combined.bytes();
        remember(state,requested,category,today,response);
        return response;
    }
}
