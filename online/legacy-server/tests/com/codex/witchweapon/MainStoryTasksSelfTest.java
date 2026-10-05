package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;

/** Checks original StoryQuest classification, progress and once-only rewards. */
public final class MainStoryTasksSelfTest {
    private static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    private static Map<String,String> args(long id){
        Map<String,String> form=new HashMap<String,String>();
        form.put("roleid","7");form.put("jobid",Long.toString(id));return form;
    }
    private static JSONObject account()throws Exception{
        return new JSONObject().put("starterProfile",1).put("cosmeticProfile",1)
            .put("roleCreated",true).put("legacyRoleId",7).put("exp",0)
            .put("gold",1000).put("rmb",0).put("ownedServants",new JSONObject());
    }
    private static byte[] listed(JSONObject state,JSONObject catalog,byte[] seed)throws Exception{
        return MainStoryTasks.bundled().taskList(state,
            CosmeticAchievements.taskList(state,catalog,seed));
    }
    private static ProtoWire job(byte[] response,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2){
                ProtoWire job=ProtoWire.parse(field.data);
                if(job.number(1,0)==id)return job;
            }
        throw new AssertionError("StoryQuest missing: "+id);
    }
    private static ProtoWire meta(byte[] response,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==2&&field.type==2){
                ProtoWire meta=ProtoWire.parse(field.data);
                if(meta.number(3,0)==id)return meta;
            }
        throw new AssertionError("StoryQuest meta missing: "+id);
    }
    public static void main(String[] argv)throws Exception{
        if(argv.length!=1)throw new IllegalArgumentException("Pass offline_responses.json");
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(Paths.get(argv[0])),
            StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");
        byte[] seed=Base64.getDecoder().decode(fixtures.getJSONObject("/task/all").getString("base64"));
        JSONObject state=account();
        byte[] all=listed(state,catalog,seed);
        int story=0;java.util.Set<Long> ids=new java.util.HashSet<Long>();
        for(ProtoWire.Field field:ProtoWire.parse(all).fields)if(field.number==2&&field.type==2){
            ProtoWire row=ProtoWire.parse(field.data);
            if(row.number(1,0)==6){story++;check(ids.add(row.number(3,0)),"Duplicate StoryQuest ID");}
        }
        check(story==106,"Original shared StoryQuest must have exactly 106 entries");
        check(job(all,502021004L).number(2,0)==-1&&
            meta(all,502021004L).number(1,0)==6,
            "Chapter-two quest must be StoryQuest and initially incomplete");
        check(!MainStoryTasks.bundled().handlesJob("502001001")&&
            MainStoryTasks.bundled().handlesJob("502021004"),
            "Existing cosmetic StoryQuest ownership must not be duplicated");

        JSONObject stages=new JSONObject().put("3110002010",new JSONObject().put("wins",1))
            .put("3110003010",new JSONObject().put("wins",1));
        state.put("mainlineStages",stages);
        all=listed(state,catalog,seed);
        check(job(all,502021004L).number(2,-1)==0&&
            job(all,502021005L).number(2,0)==-1,
            "Pre-cleared successor must wait for predecessor claim");
        MainStoryTasks.bundled().claim(state,catalog,args(502021004L));
        check(state.getLong("rmb")==10&&state.getLong("gold")==6000,
            "First chapter story quest must grant its original reward");
        MainStoryTasks.bundled().claim(state,catalog,args(502021004L));
        check(state.getLong("rmb")==10&&state.getLong("gold")==6000,
            "Retry must not pay the StoryQuest twice");
        check(job(listed(state,catalog,seed),502021005L).number(2,-1)==0,
            "Pre-cleared successor must unlock after claiming its predecessor");

        state.put("mazeBestCleared",3);
        check(job(listed(state,catalog,seed),502021080L).number(2,-1)==0&&
            job(listed(state,catalog,seed),502021081L).number(2,0)==-1,
            "Maze StoryQuest must use maze progress, not chapter wins");

        ProtoWire servant=new ProtoWire().set(4,3).set(5,1);
        state.getJSONObject("ownedServants").put("1001",LocalEconomy.encode(servant));
        check(job(listed(state,catalog,seed),502012001L).number(2,-1)==0&&
            job(listed(state,catalog,seed),502013001L).number(2,-1)==0,
            "Original rank and star StoryQuests must read owned servants");

        JSONObject other=account();
        other.put("dailyBattleStages",new JSONObject()
            .put("3120005001",new JSONObject().put("wins",3).put("sweeps",1))
            .put("3120001001",new JSONObject().put("wins",1))
            .put("3120006001",new JSONObject().put("wins",2)));
        other.put("furnaceStages",new JSONObject()
            .put("3120007001",new JSONObject().put("wins",7)));
        byte[] actual=listed(other,catalog,seed);
        for(long id:new long[]{502021018L,502021034L,502021038L,502021070L}){
            check(job(actual,id).number(2,-1)==0 && meta(actual,id).number(4,0)==1,
                "Existing daily/furnace clear must immediately complete its story task: "+id);
        }
        check(job(actual,502021071L).number(2,0)==-1 && meta(actual,502021071L).number(4,-1)==0,
            "A depth-one furnace clear must not complete depth two");
        MainStoryTasks.bundled().claim(other,catalog,args(502021070L));
        long material=other.getJSONObject("items").optLong("40230001",0);
        MainStoryTasks.bundled().claim(other,catalog,args(502021070L));
        check(other.getJSONObject("items").optLong("40230001",0)==material && material==5,
            "An existing furnace clear pays its original task reward once");
        other.getJSONObject("furnaceStages").put("3120007002",new JSONObject().put("wins",1));
        check(job(listed(other,catalog,seed),502021071L).number(2,-1)==0,
            "Next furnace task unlocks after its predecessor is claimed and exact depth clears");
        JSONObject attemptOnly=account().put("furnaceStages",new JSONObject()
            .put("3120007001",new JSONObject().put("attempts",3).put("stars",3)))
            .put("dailyBattleStages",new JSONObject()
            .put("3120005001",new JSONObject().put("wins",0).put("attempts",2)));
        check(job(listed(attemptOnly,catalog,seed),502021070L).number(2,0)==-1 &&
            job(listed(attemptOnly,catalog,seed),502021034L).number(2,0)==-1,
            "Failed attempts and unlocked stages must not manufacture task completion");
        JSONObject migrated=account().put("mainlineStages",new JSONObject()
            .put("3120007001",new JSONObject().put("wins",2)))
            .put("furnaceStages",new JSONObject().put("3120007001",new JSONObject().put("wins",7)));
        check(TaskStageProgress.wins(migrated,3120007001L)==7,
            "Overlapping migration ledgers must never duplicate clear counts");
        check(job(listed(other,catalog,seed),502021004L).number(2,0)==-1,
            "StoryQuest progress must stay isolated per account");
        other.remove("cosmeticProfile");
        check(job(listed(other,catalog,seed),502001001L).number(2,0)==-1,
            "Shared StoryQuest must remain visible for an older account");
        System.out.println("MAIN_STORY_TASKS_SELF_TEST_OK");
    }
}
