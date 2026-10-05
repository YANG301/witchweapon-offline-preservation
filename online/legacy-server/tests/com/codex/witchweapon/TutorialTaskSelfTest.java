package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** Isolated guide-job state, original fixture compatibility, and persistence. */
public final class TutorialTaskSelfTest {
    private static final long[] IDS={
        509005002L,509005003L,509005004L,509005005L,509005006L,509005009L,
        509005010L,509005011L,509021001L,509021002L,509021003L
    };
    private static void require(boolean value,String message){
        if(!value)throw new AssertionError(message);
    }
    private static long status(byte[] payload,long id)throws Exception{
        ProtoWire result=ProtoWire.parse(payload);
        for(ProtoWire.Field field:result.fields)if(field.number==1&&field.type==2){
            ProtoWire job=ProtoWire.parse(field.data);
            if(job.number(1,0)==id){
                require(job.number(3,0)==1&&job.number(5,0)==1,
                    "Original guide-job flags were removed: "+id);
                return job.number(2,Long.MIN_VALUE);
            }
        }
        throw new AssertionError("Original guide job missing: "+id);
    }
    private static ProtoWire battleJob(byte[] payload,long id)throws Exception{
        ProtoWire battle=ProtoWire.parse(payload);
        ProtoWire extra=ProtoWire.parse(battle.data(4));
        ProtoWire achievement=ProtoWire.parse(extra.data(2));
        for(ProtoWire.Field field:achievement.fields)if(field.number==1&&field.type==2){
            ProtoWire job=ProtoWire.parse(field.data);
            if(job.number(1,0)==id)return job;
        }
        return null;
    }
    private static byte[] listed(JSONObject state,byte[] seed)throws Exception{
        return LocalDaily.taskList(state,seed,1700000000L);
    }
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static JSONObject read(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: responses.json test-dir");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[0]).toPath()),
            StandardCharsets.UTF_8));
        byte[] seed=Base64.decode(responses.getJSONObject("/task/all").getString("base64"),Base64.DEFAULT);
        JSONObject catalog=responses.getJSONObject("_catalog");
        // Native PushGuideStoryProgress parses BattleResult.ExtraInfo before
        // dispatching the next guide event. Keep unrelated seed data intact.
        ProtoWire priorJob=new ProtoWire().set(1,123456L).set(2,1);
        ProtoWire priorAchievement=new ProtoWire().add(1,priorJob.bytes());
        ProtoWire priorExtra=new ProtoWire().set(3,1).set(2,priorAchievement.bytes());
        byte[] battleSeed=new ProtoWire().set(1,77).set(2,888)
            .set(4,priorExtra.bytes()).set(5,9).bytes();
        long[] resultStages={3150001001L,3150001004L,3150001005L,3150001006L};
        long[] resultJobs={509005002L,509021001L,509021002L,509021003L};
        for(int i=0;i<resultStages.length;i++){
            byte[] reply=LocalDaily.guideBattleResult(new JSONObject(),resultStages[i],battleSeed);
            ProtoWire battle=ProtoWire.parse(reply);
            ProtoWire extra=ProtoWire.parse(battle.data(4));
            ProtoWire job=battleJob(reply,resultJobs[i]);
            require(battle.number(1,0)==77&&battle.number(2,0)==888&&
                battle.number(5,0)==9&&extra.number(3,0)==1&&
                battleJob(reply,123456L)!=null&&job!=null&&
                job.number(2,-1)==0&&job.number(3,0)==1&&
                job.number(5,0)==1&&"021".equals(
                    new String(job.data(4),StandardCharsets.UTF_8)),
                "Guide battle reply omitted its matching original job or changed seed data: "+resultStages[i]);
            for(long storyJob:new long[]{509005004L,509005005L,509005006L}){
                ProtoWire story=battleJob(reply,storyJob);
                if(resultStages[i]==3150001005L)
                    require(story!=null&&story.number(2,-1)==0&&story.number(5,0)==1&&
                        "005".equals(new String(story.data(4),StandardCharsets.UTF_8)),
                        "1005 result did not immediately report its preceding story: "+storyJob);
                else require(story==null,"Unrelated battle reported an unfinished story job");
            }
        }
        require(Arrays.equals(battleSeed,new ProtoWire().set(1,77).set(2,888)
            .set(4,priorExtra.bytes()).set(5,9).bytes()),"Battle result seed was mutated");
        JSONObject preclaimedStory=new JSONObject().put("tutorialTasks",
            new JSONObject().put("509005004",1));
        byte[] keptClaim=LocalDaily.guideBattleResult(preclaimedStory,3150001005L,battleSeed);
        require(battleJob(keptClaim,509005004L).number(2,-1)==1&&
            battleJob(keptClaim,509005005L).number(2,-1)==0,
            "1005 result downgraded a previously claimed story job");
        JSONObject starter=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("namePending",true);
        for(long id:IDS)require(status(listed(starter,seed),id)==-1,
            "New account inherited a claimed guide job: "+id);
        require(starter.has("tutorialTasks"),"Guide status storage was not initialized");
        String beforeIncomplete=starter.toString();
        try{
            LocalDaily.claimGuideTask(starter,"509005003",new byte[0]);
            throw new AssertionError("Incomplete naming job was claimed");
        }catch(LocalDaily.Conflict expected){}
        require(beforeIncomplete.equals(starter.toString()),
            "Rejected guide claim changed the save");

        JSONObject named=new JSONObject(starter.toString()).put("namePending",false);
        LocalDaily.observe(named,starter,"/role/rename",1700000000L);
        require(status(listed(named,seed),509005003L)==0&&
            status(listed(named,seed),509005004L)==-1&&
            status(listed(named,seed),509005002L)==-1,
            "Naming did not finish exactly its own original task");
        byte[] claim=LocalEconomy.respond(named,catalog,"/task/update",
            Collections.singletonMap("jobid","509005003"),new byte[0]);
        require(claim.length==0&&status(listed(named,seed),509005003L)==1,
            "Naming task claim did not persist without invented reward");
        String afterClaim=named.toString();
        LocalEconomy.respond(named,catalog,"/task/update",
            Collections.singletonMap("jobid","509005003"),new byte[0]);
        require(afterClaim.equals(named.toString()),"Repeated guide claim changed state");

        long[] stages={3150001001L,3150001005L,3150001006L};
        long[] tasks={509005002L,509021002L,509021003L};
        JSONObject current=named;
        for(int i=0;i<stages.length;i++){
            JSONObject next=new JSONObject(current.toString());
            next.put("tutorialWins_"+stages[i],1);
            LocalDaily.observe(next,current,"/level/pushGuideProgress",1700000000L);
            require(status(listed(next,seed),tasks[i])==0,
                "Tutorial battle did not complete its matching guide task: "+stages[i]);
            require(status(listed(next,seed),509021001L)==-1,
                "Basestation route incorrectly completed the smelter job");
            for(long storyJob:new long[]{509005004L,509005005L,509005006L})
                require(status(listed(next,seed),storyJob)==(i==0?-1:0),
                    "Pre-1005 story milestones did not match the battle route");
            for(int j=i+1;j<tasks.length;j++)require(status(listed(next,seed),tasks[j])==-1,
                "Future tutorial battle task completed early");
            JSONObject retry=new JSONObject(next.toString());
            LocalDaily.observe(retry,next,"/level/pushGuideProgress",1700000000L);
            require(next.toString().equals(retry.toString()),
                "Repeated tutorial settlement changed guide progress");
            current=next;
        }
        JSONObject previousFirstShow=new JSONObject(named.toString());
        previousFirstShow.put("tutorialWins_3150001004",1);
        LocalDaily.observe(previousFirstShow,named,"/level/pushGuideProgress",1700000000L);
        require(status(listed(previousFirstShow,seed),509021001L)==0 &&
            status(listed(previousFirstShow,seed),509005002L)==-1 &&
            status(listed(previousFirstShow,seed),509021002L)==-1,
            "Previously saved 1004 first-show route lost its guide task");
        JSONObject reloaded=new JSONObject(current.toString());
        require(status(listed(reloaded,seed),509005002L)==0&&
            status(listed(reloaded,seed),509021001L)==-1&&
            status(listed(reloaded,seed),509005003L)==1,
            "Guide progress did not survive a save reload");
        for(long id:new long[]{509005004L,509005005L,509005006L})
            require(status(listed(reloaded,seed),id)==0,
                "Story guide job was lost after its 1005 milestone: "+id);
        for(long id:new long[]{509005009L,509005010L,509005011L})
            require(status(listed(reloaded,seed),id)==-1,
                "Unobserved story guide task was invented as completed: "+id);
        JSONObject oldChapterSave=new JSONObject(named.toString())
            .put("tutorialWins_3150001005",1);
        byte[] recovered=listed(oldChapterSave,seed);
        for(long id:new long[]{509005004L,509005005L,509005006L})
            require(status(recovered,id)==0,
                "A pre-fix 1005 winner would replay the earlier story: "+id);
        String afterRecovery=oldChapterSave.toString();
        listed(oldChapterSave,seed);
        require(afterRecovery.equals(oldChapterSave.toString()),
            "Re-reading /task/all changed recovered story milestones");

        JSONObject mistaken=new JSONObject(named.toString())
            .put("tutorialWins_3150001001",1);
        mistaken.getJSONObject("tutorialTasks").put("509021001",1);
        String mistakenBefore=mistaken.toString();
        try{
            LocalDaily.claimGuideTask(mistaken,"509021001",new byte[0]);
            throw new AssertionError("1001-only winner claimed the 1004 job");
        }catch(LocalDaily.Conflict expected){}
        require(mistakenBefore.equals(mistaken.toString()),
            "Rejected wrong-stage guide claim changed the save");
        require(status(listed(mistaken,seed),509005002L)==0&&
            status(listed(mistaken,seed),509021001L)==-1&&
            !mistaken.getJSONObject("tutorialTasks").has("509021001")&&
            mistaken.getInt("tutorialWins_3150001001")==1,
            "Previously misassigned 1001 win did not migrate to its original job");

        JSONObject legacy=new JSONObject().put("roleCreated",true);
        for(long id:IDS)if(id!=509005002L)require(status(listed(legacy,seed),id)==1,
            "Preserved account fixture guide state was changed: "+id);
        require(!legacy.has("tutorialTasks"),"Legacy account was migrated to starter guide jobs");
        require(Arrays.equals(seed,Base64.decode(responses.getJSONObject("/task/all").getString("base64"),
            Base64.DEFAULT)),"Fixture was modified");

        File root=new File(args[1]);
        require(root.isDirectory(),"Test directory missing");
        File account=new File(root,"account");
        require(account.mkdir(),"Fresh account directory required");
        LocalSave save=new LocalSave(account);
        save.respond("/role/create",Collections.<String,String>emptyMap(),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        byte[] initial=save.respond("/task/all",Collections.<String,String>emptyMap(),seed,catalog);
        require(status(initial,509005002L)==-1&&status(initial,509005003L)==-1&&
            status(initial,509021001L)==-1,
            "Real role task endpoint reused claimed tutorial fixture");
        File saveFile=new File(account,"offline_save_v1.json");
        byte[] beforeInvalid=Files.readAllBytes(saveFile.toPath());
        try{
            save.respond("/task/update",form("jobid","509005003"),new byte[0],catalog);
            throw new AssertionError("Real endpoint claimed an unfinished guide task");
        }catch(LocalDaily.Conflict expected){}
        require(Arrays.equals(beforeInvalid,Files.readAllBytes(saveFile.toPath())),
            "Rejected guide claim changed a persisted account");
        try{
            save.respond("/task/update",form("jobid","509005002"),new byte[0],catalog);
            throw new AssertionError("Unfinished basestation job was claimed");
        }catch(LocalDaily.Conflict expected){}
        require(Arrays.equals(beforeInvalid,Files.readAllBytes(saveFile.toPath())),
            "Rejected basestation claim changed a persisted account");
        save.respond("/level/startBattle",form("instanceid","3150001001",
            "idempotency","task-1001"),new byte[0],null);
        byte[] firstResult=save.respond("/level/pushGuideProgress",form("instanceid","3150001001",
            "pass","1"),battleSeed,null);
        require(battleJob(firstResult,509005002L)!=null&&
            battleJob(firstResult,509021001L)==null&&
            Arrays.equals(firstResult,save.respond("/level/pushGuideProgress",
                form("instanceid","3150001001","pass","1"),new byte[0],null)),
            "Real first-battle response did not immediately update the correct job or replay the cached result");
        byte[] afterFirstBattle=save.respond("/task/all",
            Collections.<String,String>emptyMap(),seed,catalog);
        require(status(afterFirstBattle,509005002L)==0&&
            status(afterFirstBattle,509021001L)==-1&&
            read(account).getInt("tutorialWins_3150001001")==1,
            "Real 1001 settlement did not finish only its original task");
        long beforeBaseClaimExp=read(account).getLong("exp");
        long beforeBaseClaimGold=read(account).getLong("gold");
        save.respond("/task/update",form("jobid","509005002"),new byte[0],catalog);
        require(status(save.respond("/task/all",Collections.<String,String>emptyMap(),
            seed,catalog),509005002L)==1&&
            read(account).getLong("exp")==beforeBaseClaimExp&&
            read(account).getLong("gold")==beforeBaseClaimGold,
            "Original basestation task claim did not persist or invented a reward");
        save.respond("/role/rename",form("rolename","新手玩家"),
            Base64.decode(responses.getJSONObject("/role/rename").getString("base64"),Base64.DEFAULT),catalog);
        byte[] renamed=save.respond("/task/all",Collections.<String,String>emptyMap(),seed,catalog);
        require(status(renamed,509005003L)==0,
            "Real role rename did not complete the original naming task");
        byte[] update=save.respond("/task/update",form("jobid","509005003"),
            Base64.decode(responses.getJSONObject("/task/update").getString("base64"),Base64.DEFAULT),catalog);
        require(update.length==0&&status(save.respond("/task/all",
            Collections.<String,String>emptyMap(),seed,catalog),509005003L)==1,
            "Real role task endpoint did not persist the claim");
        LocalSave restart=new LocalSave(account);
        require(status(restart.respond("/task/all",Collections.<String,String>emptyMap(),seed,catalog),
            509005003L)==1&&status(restart.respond("/task/all",
            Collections.<String,String>emptyMap(),seed,catalog),509005002L)==1,
            "Task claim was lost after server restart");
        File formerOpeningDir=new File(root,"former-opening");
        require(formerOpeningDir.mkdir(),"Fresh former-opening account directory required");
        LocalSave formerOpening=new LocalSave(formerOpeningDir);
        formerOpening.respond("/role/create",Collections.<String,String>emptyMap(),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        formerOpening.respond("/level/startBattle",form("instanceid","3150001004",
            "idempotency","task-1004"),new byte[0],null);
        formerOpening.respond("/level/pushGuideProgress",form("instanceid","3150001004",
            "pass","1"),new byte[0],null);
        byte[] formerTasks=formerOpening.respond("/task/all",
            Collections.<String,String>emptyMap(),seed,catalog);
        require(status(formerTasks,509021001L)==0&&status(formerTasks,509005002L)==-1&&
            read(formerOpeningDir).getInt("tutorialWins_3150001004")==1,
            "Real 1004 settlement did not preserve its original separate job");
        File failedBattleDir=new File(root,"failed-guide-battle");
        require(failedBattleDir.mkdir(),"Fresh failed-battle account directory required");
        LocalSave failedBattle=new LocalSave(failedBattleDir);
        failedBattle.respond("/role/create",Collections.<String,String>emptyMap(),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        failedBattle.respond("/level/startBattle",form("instanceid","3150001005",
            "idempotency","failed-1005"),new byte[0],null);
        byte[] failedResult=failedBattle.respond("/level/pushGuideProgress",
            form("instanceid","3150001005","pass","0"),battleSeed,null);
        require(Arrays.equals(failedResult,battleSeed)&&
            status(failedBattle.respond("/task/all",Collections.<String,String>emptyMap(),
                seed,catalog),509021002L)==-1&&
            status(failedBattle.respond("/task/all",Collections.<String,String>emptyMap(),
                seed,catalog),509005004L)==-1&&
            read(failedBattleDir).optInt("tutorialWins_3150001005",0)==0,
            "Failed tutorial battle emitted a completed job or changed win state");
        File chapterBattleDir=new File(root,"chapter-guide-battle");
        require(chapterBattleDir.mkdir(),"Fresh chapter-battle account directory required");
        LocalSave chapterBattle=new LocalSave(chapterBattleDir);
        chapterBattle.respond("/role/create",Collections.<String,String>emptyMap(),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        chapterBattle.respond("/level/startBattle",form("instanceid","3150001005",
            "idempotency","won-1005"),new byte[0],null);
        byte[] chapterResult=chapterBattle.respond("/level/pushGuideProgress",
            form("instanceid","3150001005","pass","1"),battleSeed,null);
        for(long id:new long[]{509005004L,509005005L,509005006L,509021002L})
            require(battleJob(chapterResult,id)!=null&&
                status(chapterBattle.respond("/task/all",Collections.<String,String>emptyMap(),
                    seed,catalog),id)==0,
                "1005 victory did not atomically update client and save: "+id);
        require(Arrays.equals(chapterResult,chapterBattle.respond("/level/pushGuideProgress",
            form("instanceid","3150001005","pass","1"),new byte[0],null))&&
            read(chapterBattleDir).getInt("tutorialWins_3150001005")==1,
            "Repeated 1005 settlement lost its cached progress or awarded a second win");
        File namedAtCreate=new File(root,"named-at-create");
        require(namedAtCreate.mkdir(),"Fresh pre-named account directory required");
        LocalSave preNamed=new LocalSave(namedAtCreate);
        preNamed.respond("/role/create",form("name","提前命名"),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        require(read(namedAtCreate).getBoolean("namePending")&&
            status(preNamed.respond("/task/all",Collections.<String,String>emptyMap(),seed,catalog),
            509005003L)==-1,"Provisional create name skipped the original naming scene");
        preNamed.respond("/role/rename",form("name","正式命名"),
            Base64.decode(responses.getJSONObject("/role/rename").getString("base64"),Base64.DEFAULT),catalog);
        require(!read(namedAtCreate).getBoolean("namePending")&&
            status(preNamed.respond("/task/all",Collections.<String,String>emptyMap(),seed,catalog),
            509005003L)==0,"The original naming submission did not finish its task");
        preNamed.respond("/role/create",form("name","重放建角"),
            Base64.decode(responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),catalog);
        require("正式命名".equals(read(namedAtCreate).getString("name")),
            "Replayed role creation overwrote the confirmed name");
        System.out.println("TUTORIAL_TASK_PASS");
    }
}
