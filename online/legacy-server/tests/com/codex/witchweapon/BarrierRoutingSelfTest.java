package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Verifies native CSC group, floor, victory and reset routes on a disposable save. */
public final class BarrierRoutingSelfTest {
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Map<String,String> form(String... values){
        Map<String,String> result=new LinkedHashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static byte[] call(LocalSave save,String path,Map<String,String> args,
                               byte[] role,JSONObject catalog,StageCatalog stages)throws Exception{
        return save.respond(path,args,role,catalog,null,stages);
    }
    private static JSONObject saved(Path folder)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(folder.resolve("offline_save_v1.json")),
            StandardCharsets.UTF_8));
    }
    private static void rejected(LocalSave save,String path,Map<String,String> args,
                                 byte[] role,JSONObject catalog,StageCatalog stages)throws Exception{
        try{call(save,path,args,role,catalog,stages);throw new AssertionError(path+" accepted invalid request");}
        catch(IOException expected){}
    }
    private static boolean containsReward(ProtoWire loot,long type,long amount)throws Exception{
        for(ProtoWire.Field field:loot.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire reward=ProtoWire.parse(field.data);
            if(reward.number(1,-1)==type && reward.number(3,-1)==amount)return true;
        }
        return false;
    }
    public static void main(String[] args)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            Paths.get("resources/offline_responses.json")),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        StageCatalog stages=StageCatalog.bundled();
        stages.install(responses);
        BarrierLabyrinth.install(responses);
        byte[] role=Base64.decode(responses.getJSONObject("/combat/role/info")
            .getString("base64"),Base64.DEFAULT);
        Path folder=Files.createTempDirectory(Paths.get("build"),"barrier-routing-");
        try{
            LocalSave save=new LocalSave(folder.toFile());
            call(save,"/role/create",form("name","MazeCheck"),new byte[0],catalog,stages);
            ProtoWire start=ProtoWire.parse(call(save,"/csc/info",form(),role,catalog,stages));
            List<Long> floorIds=start.integers(3);
            check(floorIds.size()==16 && start.integers(4).size()==16 &&
                floorIds.get(3)==0 && floorIds.get(7)==0 &&
                floorIds.get(11)==0 && floorIds.get(15)==0 &&
                start.number(22,0)==5 && start.number(24,0)==1 &&
                start.number(25,-1)==1,
                "Fresh maze did not expose twelve fights, four rewards and one reset");
            String servant="10010001";
            ProtoWire grouped=ProtoWire.parse(call(save,"/csc/group",
                form("svcardids",servant,"mercenaryownerids",""),role,catalog,stages));
            check(grouped.integers(7).size()==1 && grouped.integers(7).get(0)==Long.parseLong(servant) &&
                saved(folder).getJSONArray("mazeParty").getLong(0)==Long.parseLong(servant),
                "Maze party was not returned or persisted");
            long previewRevision=saved(folder).getLong("saveRevision");
            check(containsReward(ProtoWire.parse(call(save,"/csc/loot",form(),role,catalog,stages)),
                13,1000),"Native maze loot preview omitted the current battle reward");
            check(saved(folder).getLong("saveRevision")==previewRevision,
                "Maze reward preview changed the account save");
            rejected(save,"/csc/bonus/commit",form(),role,catalog,stages);
            rejected(save,"/csc/group",form("svcardids","99999999"),role,catalog,stages);
            check(save.fixtureKey("/combat/mob/json",form("instanceid",
                Long.toString(StageCatalog.MAZE_TRIAL))).endsWith("#"+floorIds.get(0)),
                "Maze first floor fixture does not match CSC stage");
            rejected(save,"/csc/role",form("instid",Long.toString(floorIds.get(1))),
                role,catalog,stages);
            ProtoWire battleRole=ProtoWire.parse(call(save,"/csc/role",
                form("instid",Long.toString(floorIds.get(0))),role,catalog,stages));
            check(battleRole.number(16,0)>0 && battleRole.data(18).length>0,
                "Maze role was not prepared");
            ProtoWire defeat=ProtoWire.parse(call(save,"/csc/normal/commit",
                form("levelid",Long.toString(floorIds.get(0)),"state","0",
                    "hp","0","servantcardids",servant,"energys","1000",
                    "data",new String(new char[300]).replace('\0','x')),
                role,catalog,stages));
            check(ProtoWire.parse(defeat.data(1)).number(24,0)==1 &&
                saved(folder).optInt("mazeRound",1)==1 &&
                saved(folder).getDouble("mazeEnergy_"+servant)==1000 &&
                !saved(folder).optBoolean("active",false),
                "Maze defeat did not settle or preserved a false victory");
            battleRole=ProtoWire.parse(call(save,"/csc/role",
                form("instid",Long.toString(floorIds.get(0))),role,catalog,stages));
            check(battleRole.number(16,0)>0,
                "Maze defeat left the same floor impossible to retry");
            Map<String,String> win=form("levelid",Long.toString(floorIds.get(0)),"state","1",
                "hp",Long.toString(battleRole.number(16,1)),"servantcardids",servant,
                "energys","997.5","data","");
            byte[] won=call(save,"/csc/normal/commit",win,role,catalog,stages);
            ProtoWire settlement=ProtoWire.parse(won);
            ProtoWire afterWin=ProtoWire.parse(settlement.data(1));
            check(afterWin.number(24,0)==2 && saved(folder).getInt("mazeBestCleared")==1 &&
                saved(folder).getDouble("mazeEnergy_"+servant)==997.5,
                "Maze win did not advance the real floor or best record");
            check(containsReward(ProtoWire.parse(settlement.data(2)),13,1000),
                "First-floor gold was not returned in the claimable settlement loot");
            long revision=saved(folder).getLong("saveRevision");
            check(Arrays.equals(won,call(save,"/csc/normal/commit",win,role,catalog,stages)) &&
                saved(folder).getLong("saveRevision")==revision,
                "Maze settlement replay changed the save");
            check(save.fixtureKey("/combat/mob/json",form("instanceid",
                Long.toString(StageCatalog.MAZE_TRIAL))).endsWith("#"+floorIds.get(1)),
                "Maze second floor selected the previous encounter");
            rejected(save,"/csc/role",form("instid",Long.toString(floorIds.get(0))),
                role,catalog,stages);
            rejected(save,"/csc/normal/commit",form("levelid",Long.toString(floorIds.get(0)),
                "state","1","hp","1"),role,catalog,stages);
            ProtoWire reset=ProtoWire.parse(call(save,"/csc/reset",form(),role,catalog,stages));
            check(reset.number(24,0)==1 && reset.number(25,-1)==0 &&
                saved(folder).getInt("mazeRound")==1 && saved(folder).getInt("mazeWins")==1,
                "Maze reset did not retain wins or spend the daily allowance");
            rejected(save,"/csc/reset",form(),role,catalog,stages);
            long goldBeforeRun=saved(folder).getLong("gold");
            for(int floor=1;floor<=12;floor++){
                long stage=floorIds.get(floor-1+(floor-1)/3);
                ProtoWire prepared=ProtoWire.parse(call(save,"/csc/role",
                    form("instid",Long.toString(stage)),role,catalog,stages));
                ProtoWire award=ProtoWire.parse(call(save,"/csc/normal/commit",
                    form("levelid",Long.toString(stage),"state","1",
                        "hp",Long.toString(prepared.number(16,1)),
                        "servantcardids","","energys","","data",""),
                    role,catalog,stages));
                ProtoWire floorState=ProtoWire.parse(award.data(1));
                ProtoWire loot=ProtoWire.parse(award.data(2));
                check(floorState.number(24,0)==floor+1+(floor-1)/3 &&
                    containsReward(loot,13,1000),
                    "Floor "+floor+" did not advance or return its ordinary reward");
                check(!containsReward(loot,13,10000),
                    "Floor "+floor+" credited an unclaimed checkpoint reward");
                if(floor%3==0){
                    JSONObject pending=saved(folder);
                    if(floor==3){
                        LocalSave reloaded=new LocalSave(folder.toFile());
                        check(ProtoWire.parse(call(reloaded,"/csc/info",form(),role,catalog,stages))
                            .number(24,0)==4,
                            "Unclaimed maze chest did not survive a new session");
                    }
                    check(pending.getInt("mazePendingBonus")==floor &&
                        pending.getLong("gold")==goldBeforeRun+floor*1000L+(floor/3-1)*10000L &&
                        containsReward(ProtoWire.parse(call(save,"/csc/loot",form(),role,catalog,stages)),
                            13,10000),
                        "Checkpoint "+floor+" was not available for the original chest action");
                    check(saved(folder).getLong("saveRevision")==pending.getLong("saveRevision"),
                        "Checkpoint preview claimed a reward before clicking the chest");
                    if(floor<12)rejected(save,"/csc/role",
                        form("instid",Long.toString(floorIds.get(floor+floor/3))),
                        role,catalog,stages);
                    byte[] claimed=call(save,"/csc/bonus/commit",form(),role,catalog,stages);
                    ProtoWire chest=ProtoWire.parse(claimed);
                    ProtoWire afterChest=ProtoWire.parse(chest.data(1));
                    check(afterChest.number(22,0)==5 &&
                        afterChest.number(24,0)==floor+1+floor/3 &&
                        containsReward(ProtoWire.parse(chest.data(2)),13,10000) &&
                        saved(folder).getLong("gold")==pending.getLong("gold")+10000 &&
                        saved(folder).optInt("mazePendingBonus",0)==0,
                        "Checkpoint "+floor+" did not settle the original bonus node");
                    if(floor==6){
                        // Stage 3130001009 is the first sub-type-2 encounter.
                        // Its detail panel calls GetMobLevel(field 22, index).
                        check(floorIds.get(8)==3130001009L &&
                            ProtoWire.parse(call(save,"/csc/info",form(),role,catalog,stages))
                                .number(22,0)==5,
                            "Seventh-floor detail lacks a CharacterLevelInfo lookup key");
                    }
                    long claimRevision=saved(folder).getLong("saveRevision");
                    check(Arrays.equals(claimed,call(save,"/csc/bonus/commit",form(),role,catalog,stages)) &&
                        saved(folder).getLong("saveRevision")==claimRevision,
                        "Checkpoint "+floor+" retry duplicated a reward");
                }
            }
            JSONObject completed=saved(folder);
            check(completed.getInt("mazeRound")==13 && completed.getInt("mazeBestCleared")==12 &&
                completed.getInt("mazeCompletedRuns")==1 &&
                completed.getInt("mazeSupplyBoxes")==4 &&
                completed.getLong("gold")==goldBeforeRun+12*1000+4*10000,
                "Twelve-floor completion did not retain the four checkpoint rewards");
            rejected(save,"/csc/role",form("instid",Long.toString(floorIds.get(14))),
                role,catalog,stages);
            System.out.println("BARRIER_ROUTING_SELF_TEST_OK");
        }finally{
            Files.walkFileTree(folder,new SimpleFileVisitor<Path>(){
                public FileVisitResult visitFile(Path file,BasicFileAttributes attributes)throws IOException{
                    Files.delete(file);return FileVisitResult.CONTINUE;
                }
                public FileVisitResult postVisitDirectory(Path directory,IOException error)throws IOException{
                    if(error!=null)throw error;
                    Files.delete(directory);return FileVisitResult.CONTINUE;
                }
            });
        }
    }
}
