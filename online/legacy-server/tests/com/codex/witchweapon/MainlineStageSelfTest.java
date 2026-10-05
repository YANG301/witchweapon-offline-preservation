package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Account-local mainline and former-maze migration regression checks. */
public final class MainlineStageSelfTest {
    private static void check(boolean yes,String message){if(!yes)throw new AssertionError(message);}
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }
    private static JSONObject save(File dir)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8));
    }
    private static byte[] call(LocalSave user,String route,Map<String,String> args,
                               JSONObject responses,StageCatalog stages)throws Exception{
        JSONObject fixture=responses.getJSONObject(route);
        byte[] seed=fixture.has("base64")?Base64.decode(fixture.getString("base64"),Base64.DEFAULT):new byte[0];
        return user.respond(route,args,seed,responses.getJSONObject("_catalog"),null,stages);
    }
    private static void rejected(LocalSave user,long id,JSONObject responses,StageCatalog stages)throws Exception{
        try{
            call(user,"/level/startBattle",form("instanceid",Long.toString(id),"idempotency","bad-"+id),
                responses,stages);
            throw new AssertionError("Unavailable stage was admitted: "+id);
        }catch(java.io.IOException expected){}
    }
    private static byte[] victory(LocalSave user,long id,String key,JSONObject responses,
                                  StageCatalog stages)throws Exception{
        call(user,"/level/startBattle",form("instanceid",Long.toString(id),"idempotency",key),responses,stages);
        return call(user,"/level/pushMainLineProgress",form("instanceid",Long.toString(id),
            "pass","1","stars","3"),responses,stages);
    }
    private static int progressCount(byte[] bytes,long chapterId)throws Exception{
        ProtoWire result=ProtoWire.parse(bytes);
        for(ProtoWire.Field field:result.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire chapter=ProtoWire.parse(field.data);
            if(chapter.number(1,0)!=chapterId)continue;
            int count=0;
            for(ProtoWire.Field level:chapter.fields)if(level.number==2 && level.type==2)count++;
            return count;
        }
        throw new AssertionError("Chapter absent: "+chapterId);
    }
    private static long progressField(byte[] bytes,long stageId,int fieldNumber)throws Exception{
        ProtoWire result=ProtoWire.parse(bytes);
        for(ProtoWire.Field chapterField:result.fields){
            if(chapterField.number!=1 || chapterField.type!=2)continue;
            ProtoWire chapter=ProtoWire.parse(chapterField.data);
            for(ProtoWire.Field levelField:chapter.fields){
                if(levelField.number!=2 || levelField.type!=2)continue;
                ProtoWire level=ProtoWire.parse(levelField.data);
                if(level.number(1,0)==stageId)return level.number(fieldNumber,-1);
            }
        }
        throw new AssertionError("Stage absent: "+stageId);
    }
    private static boolean eventContains(byte[] battle,String name,long value)throws Exception{
        ProtoWire result=ProtoWire.parse(battle),extra=ProtoWire.parse(result.data(4));
        for(ProtoWire.Field field:extra.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire event=ProtoWire.parse(field.data);
            if(!name.equals(new String(event.data(1),StandardCharsets.UTF_8)))continue;
            for(ProtoWire.Field item:event.fields)if(item.number==2 && item.type==2 &&
                Long.toString(value).equals(new String(item.data,StandardCharsets.UTF_8)))return true;
        }
        return false;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("Arguments: fresh-test-dir responses.json stage_catalog.json");
        File root=new File(args[0]),player=new File(root,"player"),migrated=new File(root,"migrated");
        check(root.isDirectory() && player.mkdir() && migrated.mkdir(),"Fresh test directories required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),StandardCharsets.UTF_8));
        StageCatalog stages=new StageCatalog(new JSONObject(new String(Files.readAllBytes(new File(args[2]).toPath()),StandardCharsets.UTF_8)));
        stages.install(responses);
        check(stages.supported(3110001003L),"True mainline 1-3 missing");
        boolean simpleCampaign="simple-campaign-v1".equals(stages.profile());
        check(stages.supported(3110016001L)==simpleCampaign,
              "Chapter 16 availability does not match the catalog profile");
        JSONObject trueThird=new JSONObject(responses.getJSONObject("/combat/mob/json#3110001003").getString("body"));
        JSONObject oldMaze=new JSONObject(responses.getJSONObject("/combat/mob/json#3130001026@1").getString("body"));
        check("3110001003".equals(trueThird.getJSONObject("EnemyLayer").getString("levelID")),"Real 1-3 battle not installed");
        check("3130001026".equals(oldMaze.getJSONObject("EnemyLayer").getString("levelID")),"Maze fixture not relocated");
        JSONObject sweepQuest=new JSONObject(responses.getJSONObject("/combat/mob/json#3110001002")
            .getString("body")).getJSONObject("QuestInfo");
        check(sweepQuest.getInt("BonusType")==2 && sweepQuest.getDouble("BonusParam")==0.5,
              "1-2 sweep condition was cleared by the simplified battle template");

        LocalSave user=new LocalSave(player);
        byte[] progress=call(user,"/level/getAllProgress",form(),responses,stages);
        check(progressCount(progress,3010001L)==10 && progressCount(progress,3010002L)==15 &&
            progressCount(progress,3010016L)==15,"Ordinary and elite progress entries incomplete");
        if(simpleCampaign){
            check(progressField(progress,3110001003L,4)==1 &&
                  progressField(progress,3110016001L,4)==1 &&
                  progressField(progress,3110016001L,2)==0 &&
                  progressField(progress,3110016001L,3)==0,
                  "Open-all profile fabricated a clear or left a stage locked");
            call(user,"/level/startBattle",form("instanceid","3110016015",
                "idempotency","final-chapter-immediate"),responses,stages);
            call(user,"/level/pushMainLineProgress",form("instanceid","3110016015",
                "pass","0","stars","0"),responses,stages);
            check(progressField(call(user,"/level/getAllProgress",form(),responses,stages),
                3110016015L,2)==0,"Direct final-chapter loss fabricated a clear");
        }else{
            rejected(user,3110001003L,responses,stages);
            rejected(user,3110016001L,responses,stages);
        }
        rejected(user,3119999999L,responses,stages);

        // A failed first stage records an attempt, yet gives no progression or reward.
        call(user,"/level/startBattle",form("instanceid","3110001001","idempotency","first-fail"),responses,stages);
        JSONObject before=save(player);
        byte[] failed=call(user,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","0","stars","0"),responses,stages);
        JSONObject after=save(player);
        check(after.getLong("gold")==before.getLong("gold") &&
              after.optLong("storyCurrency",0)==before.optLong("storyCurrency",0) &&
               after.optInt("mainlineWins",0)==0 &&
               !eventContains(failed,"OpenLevel",3110001001L),
               "Failure awarded resources or opened its own stage");
        byte[] first=victory(user,3110001001L,"first-win",responses,stages);
        check(eventContains(first,"OpenLevel",3110001002L)==!simpleCampaign,
              "First win unlock event does not match the catalog profile");
        check(eventContains(first,"OpenLevel",3110001001L)==simpleCampaign,
              "The first odd-stage win did not reaffirm its open status");
        JSONObject cleared=save(player);
        check(cleared.getJSONObject("mainlineStages").getJSONObject("3110001001").getInt("attempts")==2 &&
              cleared.getJSONObject("mainlineStages").getJSONObject("3110001001").getInt("wins")==1 &&
              cleared.getJSONObject("mainlineStages").getJSONObject("3110001001").getBoolean("firstRewardClaimed"),
              "First stage progress was not persisted per stage");
        long gold=cleared.getLong("gold"),story=cleared.optLong("storyCurrency",0);
        check(gold==after.getLong("gold")+1000 && story>after.optLong("storyCurrency",0),
              "Local catch-up or original story reward missing");
        byte[] duplicate=call(user,"/level/pushMainLineProgress",form("instanceid","3110001001", "pass","1","stars","3"),responses,stages);
        check(Arrays.equals(first,duplicate) && save(player).getLong("gold")==gold,
              "Duplicate settlement changed reward");
        byte[] repeated=victory(user,3110001001L,"first-repeat",responses,stages);
        JSONObject repeatedSave=save(player);
        check(eventContains(repeated,"OpenLevel",3110001001L)==simpleCampaign &&
              repeatedSave.optLong("storyCurrency",0)==story &&
              repeatedSave.getJSONObject("mainlineStages")
                  .getJSONObject("3110001001").getInt("wins")==2,
              "Repeat odd-stage victory lost its open event or repeated first-clear reward");
        long repeatRevision=repeatedSave.getLong("saveRevision");
        byte[] repeatedRetry=call(user,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","1","stars","3"),responses,stages);
        check(Arrays.equals(repeated,repeatedRetry) &&
              save(player).getLong("saveRevision")==repeatRevision,
              "Repeat odd-stage settlement replay changed the save or response");
        check(save(player).optInt("wins",0)==0,"Other stage polluted legacy 1-2 wins");

        victory(user,3110001002L,"second-win",responses,stages);
        byte[] afterSecond=call(user,"/level/getAllProgress",form(),responses,stages);
        check(progressField(afterSecond,3110001002L,7)==1 &&
              StageSweep.eligible(save(player),stages,stages.stage(3110001002L)),
              "First 1-2 victory did not open its original sweep state");
        byte[] third=victory(user,3110001003L,"third-win",responses,stages);
        check(eventContains(third,"OpenLevel",3110001003L)==simpleCampaign,
              "The 1-3 victory did not reaffirm its open status");
        check(save(player).getJSONObject("mainlineStages").getJSONObject("3110001003").getInt("wins")==1,
              "Real 1-3 was misrouted to the maze");
        byte[] chapterEnd=null;
        for(long id=3110001004L;id<=3110001010L;id++)chapterEnd=victory(user,id,"normal-"+id,responses,stages);
        check(eventContains(chapterEnd,"OpenLevel",3110002001L)==!simpleCampaign &&
              eventContains(chapterEnd,"NextChapter",3010002L)==!simpleCampaign,
              "Chapter completion unlock event does not match the catalog profile");
        victory(user,3110002001L,"chapter2-first",responses,stages);
        byte[] branch=victory(user,3110002002L,"chapter2-second",responses,stages);
        check(eventContains(branch,"OpenLevel",3110002011L)==!simpleCampaign,
              "Elite MapPoint unlock event does not match the catalog profile");
        byte[] elite=victory(user,3110002011L,"elite2-first",responses,stages);
        check(ProtoWire.parse(elite).number(5,0)>0 &&
              save(player).getJSONObject("mainlineStages").getJSONObject("3110002011").getInt("wins")==1,
              "Elite stage lacks isolated settlement or local experience");
        check(save(player).getLong("gold")>=gold+12_000,
              "Ordinary and elite local catch-up Gold missing");
        LocalSave reloaded=new LocalSave(player);
        check(reloaded.respond("/level/getAllProgress",form(),fixture(responses,"/level/getAllProgress"),
              responses.getJSONObject("_catalog"),null,stages).length>0 &&
              save(player).getJSONObject("mainlineStages").getJSONObject("3110002011").getInt("wins")==1,
              "Per-stage progress did not survive reload");

        // A pre-migration author save carries the old maze at 1-3. Once
        // migrated, retained mazeRound/battleMazeRound must not steal real 1-3.
        LocalSave legacy=new LocalSave(migrated);
        legacy.roleSummary();
        JSONObject former=save(migrated);
        former.put("active",true).put("activeStage",StageCatalog.FORMER_MAZE_ENTRY)
            .put("mazeRound",2).put("battleMazeRound",2).put("wins",1).put("startKey","old-maze");
        Files.write(new File(migrated,"offline_save_v1.json").toPath(),
            (former.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave upgraded=new LocalSave(migrated);
        String mazeFixture=upgraded.fixtureKey("/combat/mob/json",form("instanceid",Long.toString(StageCatalog.MAZE_TRIAL)));
        check(mazeFixture.endsWith("#"+BarrierLabyrinth.stageForRound(2)) &&
              save(migrated).getLong("activeStage")==StageCatalog.MAZE_TRIAL,
              "Former maze active battle was not migrated");
        byte[] roleTemplate=fixture(responses,"/combat/role/info");
        ProtoWire csc=ProtoWire.parse(upgraded.respond("/csc/info",form(),roleTemplate,
            responses.getJSONObject("_catalog"),null,stages));
        check(csc.integers(3).size()==16 &&
              new java.util.HashSet<Long>(csc.integers(3)).size()==13 &&
              csc.integers(4).size()==16 &&
              csc.number(24,0)==2 && csc.number(27,0)==1 && csc.number(17,0)>0,
              "Expedition entrance did not receive the sixteen-node original map");
        for(int reward=1;reward<=4;reward++)
            check(csc.integers(3).get(reward*4-1)==0 &&
                  csc.integers(4).get(reward*4-1)==0,
                  "Expedition reward node was not preserved");
        ProtoWire role=ProtoWire.parse(upgraded.respond("/csc/role",form(),roleTemplate,
            responses.getJSONObject("_catalog"),null,stages));
        check(role.data(18).length>0 && role.number(16,0)>0,
              "CSC combat role was not wrapped in CscCombatInfo");
        Map<String,String> cscResult=form("levelid",Long.toString(BarrierLabyrinth.stageForRound(2)),
            "state","1","hp",Long.toString(role.number(16,1)),
            "servantcardids","","energys","","data","");
        byte[] cscSettlement=upgraded.respond("/csc/normal/commit",cscResult,roleTemplate,
            responses.getJSONObject("_catalog"),null,stages);
        ProtoWire committed=ProtoWire.parse(cscSettlement);
        check(ProtoWire.parse(committed.data(1)).number(24,0)==3 &&
              ProtoWire.parse(committed.data(2)).data(1).length>0,
              "Native CSC settlement did not advance the round or grant local loot");
        long settledGold=save(migrated).getLong("gold");
        check(Arrays.equals(cscSettlement,upgraded.respond("/csc/normal/commit",cscResult,roleTemplate,
                responses.getJSONObject("_catalog"),null,stages)) &&
              save(migrated).getLong("gold")==settledGold,
              "Repeated native CSC settlement awarded twice");
        upgraded.respond("/csc/role",form(),roleTemplate,responses.getJSONObject("_catalog"),null,stages);
        Map<String,String> lost=form("levelid",Long.toString(BarrierLabyrinth.stageForRound(3)),
            "state","0","hp",Long.toString(role.number(16,1)),
            "servantcardids","","energys","","data","");
        byte[] failedCsc=upgraded.respond("/csc/normal/commit",lost,roleTemplate,
            responses.getJSONObject("_catalog"),null,stages);
        check(ProtoWire.parse(ProtoWire.parse(failedCsc).data(1)).number(24,0)==3 &&
              save(migrated).getLong("gold")==settledGold && save(migrated).getInt("mazeWins")==1,
              "Failed CSC battle advanced or awarded the run");
        victory(upgraded,3110001003L,"real-third-after-maze",responses,stages);
        LocalSave again=new LocalSave(migrated);
        check(again.fixtureKey("/combat/mob/json",form("instanceid","3110001003")).endsWith("#3110001003") &&
              save(migrated).getLong("activeStage")==3110001003L &&
              save(migrated).getJSONObject("mainlineStages").getJSONObject("3110001003").getInt("wins")==1 &&
              save(migrated).getInt("mazeWins")==1,
              "Once-only maze migration overwrote the real 1-3 after reload");
        System.out.println("MAINLINE_STAGE_SELF_TEST_OK");
    }
}
