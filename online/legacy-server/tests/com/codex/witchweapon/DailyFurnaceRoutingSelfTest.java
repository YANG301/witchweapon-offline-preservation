package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/** Exercises both restored modes through the same save route used by the HTTP host. */
public final class DailyFurnaceRoutingSelfTest {
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Map<String,String> form(String... entries){
        Map<String,String> result=new LinkedHashMap<String,String>();
        for(int i=0;i<entries.length;i+=2)result.put(entries[i],entries[i+1]);
        return result;
    }
    private static byte[] call(LocalSave save,String path,Map<String,String> args,byte[] seed,
                               JSONObject catalog,StageCatalog main,DailyBattle daily,
                               WeaponFurnace furnace)throws Exception{
        return save.respond(path,args,seed,catalog,null,main,daily,furnace);
    }
    private static JSONObject snapshot(Path dir)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(dir.resolve("offline_save_v1.json")),
            StandardCharsets.UTF_8));
    }
    private static int lootResults(byte[] bytes)throws Exception{
        int count=0;
        for(ProtoWire.Field field:ProtoWire.parse(bytes).fields)
            if(field.number==1 && field.type==2)count++;
        return count;
    }
    private static String ownedCoreWeapon(JSONObject saved,JSONObject source)throws Exception{
        JSONObject owned=saved.getJSONObject("ownedServants");
        for(String servantId:owned.keySet()){
            ProtoWire servant=ProtoWire.parse(Base64.decode(owned.getString(servantId),Base64.DEFAULT));
            for(ProtoWire.Field field:servant.fields)if(field.number==13 && field.type==2){
                String weapon=Long.toString(ProtoWire.parse(field.data).number(1,0));
                if(source.getJSONObject("weaponCoreItems").has(weapon))return weapon;
            }
        }
        throw new AssertionError("Starter weapon core missing");
    }
    public static void main(String[] args)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            Paths.get("resources/offline_responses.json")),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        JSONObject furnaceSource=new JSONObject(new String(Files.readAllBytes(
            Paths.get("resources/weapon_furnace_catalog.json")),StandardCharsets.UTF_8));
        StageCatalog main=StageCatalog.bundled();
        DailyBattle daily=DailyBattle.bundled();
        WeaponFurnace furnace=WeaponFurnace.bundled();
        Path base=args.length==0?Paths.get("E:/Desktop/魔女兵器熔炉/隔离回归"):Paths.get(args[0]);
        Files.createDirectories(base);
        Path dir=Files.createTempDirectory(base,"daily-furnace-routing-");
        try{
            LocalSave save=new LocalSave(dir.toFile());
            call(save,"/role/create",form("name","Integration"),new byte[0],
                catalog,main,daily,furnace);
            call(save,"/role/rename",form("rolename","Integration"),new byte[0],
                catalog,main,daily,furnace);
            byte[] progressSeed=Base64.decode(responses.getJSONObject("/level/getAllProgress")
                .getString("base64"),Base64.DEFAULT);
            byte[] progress=call(save,"/level/getAllProgress",form(),progressSeed,
                catalog,main,daily,furnace);
            int dailyChapters=0,furnaceStages=0;
            long openDaily=0;
            for(ProtoWire.Field entry:ProtoWire.parse(progress).fields){
                if(entry.number!=1 || entry.type!=2)continue;
                ProtoWire chapter=ProtoWire.parse(entry.data);
                long chapterId=chapter.number(1,0);
                if(chapterId>=3020001L && chapterId<=3020006L)dailyChapters++;
                for(ProtoWire.Field levelEntry:chapter.fields){
                    if(levelEntry.number!=2 || levelEntry.type!=2)continue;
                    ProtoWire level=ProtoWire.parse(levelEntry.data);
                    if(chapterId>=3020001L && chapterId<=3020006L && openDaily==0 &&
                            level.number(4,0)==1)openDaily=level.number(1,0);
                    if(chapterId==3020007L){
                        furnaceStages++;
                        check(level.number(4,0)==1,"Furnace depth locked for new account");
                    }
                }
            }
            check(dailyChapters==6 && openDaily!=0 && furnaceStages==5,
                "Daily or furnace chapter absent from first login");
            byte[] startSeed=Base64.decode(responses.getJSONObject("/level/startBattle")
                .getString("base64"),Base64.DEFAULT);
            call(save,"/level/startBattle",form("instanceid",Long.toString(openDaily),
                "idempotency","daily-1"),startSeed,catalog,main,daily,furnace);
            JSONObject started=snapshot(dir);
            check(started.getLong("activeStage")==openDaily &&
                started.getJSONObject("dailyBattleAttempts")
                    .getInt(Long.toString(openDaily/1000-100000L))==1,
                "Daily battle did not persist start");
            Map<String,String> dailyResult=form("instanceid",Long.toString(openDaily),
                "pass","1","stars","3");
            byte[] dailyWin=call(save,"/level/pushDailyProgress",dailyResult,new byte[0],
                catalog,main,daily,furnace);
            JSONObject afterDaily=snapshot(dir);
            check(!afterDaily.getBoolean("active") && afterDaily.getLong("stamina")==190,
                "Daily battle did not settle once");
            long dailyRevision=afterDaily.getLong("saveRevision");
            check(Arrays.equals(dailyWin,call(save,"/level/pushDailyProgress",dailyResult,
                new byte[0],catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==dailyRevision,
                "Daily settlement replay changed save");
            long depth=3120007005L;
            String weapon=ownedCoreWeapon(afterDaily,furnaceSource);
            long beforeMissing=snapshot(dir).getLong("saveRevision");
            boolean missingRejected=false;
            try{call(save,"/level/startBattle",form("instanceid",Long.toString(depth),
                "idempotency","missing-furnace-weapon"),
                startSeed,catalog,main,daily,furnace);}
            catch(java.io.IOException expected){missingRejected=true;}
            check(missingRejected && snapshot(dir).getLong("saveRevision")==beforeMissing,
                "Omitted furnace weapon started a battle or changed the save");
            for(String invalid:new String[]{"","0","999999999"}){
                long beforeRevision=snapshot(dir).getLong("saveRevision");
                boolean rejected=false;
                try{call(save,"/level/startBattle",form("instanceid",Long.toString(depth),
                    "idempotency","invalid-furnace-"+invalid,"wantweapon",invalid),
                    startSeed,catalog,main,daily,furnace);}
                catch(java.io.IOException expected){rejected=true;}
                check(rejected && snapshot(dir).getLong("saveRevision")==beforeRevision,
                    "Missing or invalid furnace weapon started a battle or changed the save");
            }
            call(save,"/level/startBattle",form("instanceid",Long.toString(depth),
                "idempotency","furnace-1","wantweapon",weapon),
                startSeed,catalog,main,daily,furnace);
            JSONObject active=snapshot(dir);
            check(active.getLong("activeStage")==depth && active.getBoolean("active") &&
                weapon.equals(active.getString("furnaceBattleWeapon")),
                "Furnace depth five could not start at level one");
            long activeRevision=active.getLong("saveRevision");
            check(Arrays.equals(startSeed,call(save,"/level/rebattle",
                form("instanceid",Long.toString(depth),"idempotency","furnace-resume"),
                startSeed,catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==activeRevision,
                "Native rebattle replaced the already active weapon selection");
            long core=furnaceSource.getJSONObject("weaponCoreItems").getLong(weapon);
            Map<String,String> furnaceResult=form("instanceid",Long.toString(depth),
                "pass","1","stars","3","wantweapon","0");
            byte[] furnaceWin=call(save,"/level/pushMaterialProgress",furnaceResult,
                new byte[0],catalog,main,daily,furnace);
            JSONObject afterFurnace=snapshot(dir);
            check(afterFurnace.getLong("stamina")==180 &&
                afterFurnace.getInt("furnaceCoreClaims")==1 &&
                afterFurnace.getJSONObject("items").getLong(Long.toString(core))==2,
                "Furnace stamina or core reward was not persisted");
            long furnaceRevision=afterFurnace.getLong("saveRevision");
            check(Arrays.equals(furnaceWin,call(save,"/level/pushMaterialProgress",
                furnaceResult,new byte[0],catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==furnaceRevision,
                "Furnace settlement replay changed save");
            // Exercise the new client's four independent identities through
            // the actual persisted HTTP route, using a separate synthetic
            // copy so the original rid-only compatibility check stays intact.
            Path modernDir=dir.resolve("new-client");Files.createDirectory(modernDir);
            JSONObject modernInitial=new JSONObject(afterFurnace.toString()).put("rmb",100);
            Files.write(modernDir.resolve("offline_save_v1.json"),
                (modernInitial.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
            java.util.ArrayList<Long> pool=new java.util.ArrayList<Long>();
            org.json.JSONArray pending=modernInitial.getJSONArray("furnacePendingChoiceItems");
            for(int i=0;i<pending.length();i++)pool.add(pending.getLong(i));
            java.util.Collections.sort(pool);StringBuilder signature=new StringBuilder();
            for(long item:pool){if(signature.length()>0)signature.append(',');signature.append(item);}
            java.util.Set<Long> obtained=new java.util.HashSet<Long>();
            obtained.add(pending.getLong(0));
            LocalSave modern=new LocalSave(modernDir.toFile());
            long modernBalance=100;int[] prices={5,10,10,15};
            for(int purchase=0;purchase<prices.length;purchase++){
                Map<String,String> request=form("rid","1","idempotency","furnace-route-"+purchase,
                    "choicePool",signature.toString());
                JSONObject before=snapshot(modernDir);
                byte[] paid=call(modern,"/level/chooseMaterials",request,new byte[0],
                    catalog,main,daily,furnace);
                long paidItem=ProtoWire.parse(ProtoWire.parse(paid).data(8)).number(2,0);
                JSONObject after=snapshot(modernDir);modernBalance-=prices[purchase];
                check(pool.contains(paidItem) && obtained.add(paidItem) &&
                    after.getJSONObject("items").getLong(Long.toString(paidItem))==
                        before.getJSONObject("items").optLong(Long.toString(paidItem),0)+1 &&
                    after.getLong("rmb")==modernBalance &&
                    after.getInt("furnaceChoicePurchases")==purchase+1,
                    "New client route reused a reward or charged the wrong price");
                ProtoWire inventory=ProtoWire.parse(call(modern,"/backpack/item",form("rid","1"),
                    new byte[0],catalog,main,daily,furnace));
                java.util.ArrayList<Long> itemIds=new java.util.ArrayList<Long>();
                java.util.ArrayList<Long> itemCounts=new java.util.ArrayList<Long>();
                for(ProtoWire.Field field:inventory.fields){
                    if(field.number==1&&field.type==0)itemIds.add(field.value);
                    if(field.number==2&&field.type==0)itemCounts.add(field.value);
                }
                check(itemIds.size()==itemCounts.size() && itemIds.contains(paidItem) &&
                    itemCounts.get(itemIds.indexOf(paidItem))==
                        after.getJSONObject("items").getLong(Long.toString(paidItem)),
                    "Original full backpack protocol did not return the authoritative core quantity");
                modern=new LocalSave(modernDir.toFile());
                check(Arrays.equals(paid,call(modern,"/level/chooseMaterials",request,new byte[0],
                        catalog,main,daily,furnace)) &&
                    snapshot(modernDir).getLong("saveRevision")==after.getLong("saveRevision") &&
                    snapshot(modernDir).getLong("rmb")==modernBalance,
                    "New client retry after reload changed inventory or charged twice");
            }
            JSONObject finished=snapshot(modernDir);boolean fifthRejected=false;
            try{call(modern,"/level/chooseMaterials",form("rid","1",
                "idempotency","furnace-route-fifth","choicePool",signature.toString()),
                new byte[0],catalog,main,daily,furnace);}
            catch(java.io.IOException expected){fifthRejected=true;}
            check(obtained.size()==5 && modernBalance==60 &&
                !finished.has("furnacePendingChoiceItems") && fifthRejected &&
                snapshot(modernDir).getLong("saveRevision")==finished.getLong("saveRevision"),
                "Last offered slot was not awarded once or fifth purchase changed the save");
            // This isolated account starts with zero diamonds. Give it the
            // exact original first-purchase price before exercising the
            // native rid-only route, then reload the save from disk.
            JSONObject funded=snapshot(dir).put("rmb",5);
            Files.write(dir.resolve("offline_save_v1.json"),
                (funded.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
            save=new LocalSave(dir.toFile());
            byte[] choice=call(save,"/level/chooseMaterials",
                form("rid","1"),new byte[0],
                catalog,main,daily,furnace);
            long material=ProtoWire.parse(ProtoWire.parse(choice).data(8)).number(2,0);
            boolean coreCandidate=false;
            for(String originalWeapon:furnaceSource.getJSONObject("weaponCoreItems").keySet())
                if(furnaceSource.getJSONObject("weaponCoreItems").getLong(originalWeapon)==material)
                    coreCandidate=true;
            check(coreCandidate && material!=core,
                "Material choice response is not an original extra weapon core");
            JSONObject afterChoice=snapshot(dir);
            check(afterChoice.getLong("rmb")==0 &&
                afterChoice.getInt("furnaceChoicePurchases")==1,
                "Native material choice did not persist its five-diamond cost");
            long choiceRevision=afterChoice.getLong("saveRevision");
            check(Arrays.equals(choice,call(save,"/level/chooseMaterials",
                form("rid","1"),new byte[0],
                catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==choiceRevision,
                "Material choice replay changed save");
            LocalSave reloaded=new LocalSave(dir.toFile());
            byte[] persisted=call(reloaded,"/level/getAllProgress",form(),progressSeed,
                catalog,main,daily,furnace);
            boolean depthPassed=false;
            for(ProtoWire.Field chapterEntry:ProtoWire.parse(persisted).fields){
                if(chapterEntry.number!=1 || chapterEntry.type!=2)continue;
                ProtoWire chapter=ProtoWire.parse(chapterEntry.data);
                if(chapter.number(1,0)!=3020007L)continue;
                for(ProtoWire.Field levelEntry:chapter.fields)if(levelEntry.number==2 &&
                    ProtoWire.parse(levelEntry.data).number(1,0)==depth)
                    depthPassed=ProtoWire.parse(levelEntry.data).number(2,0)==1;
            }
            check(depthPassed,"Furnace victory did not survive save reload");
            Map<String,String> dailySweep=form("chapid",Long.toString(openDaily/1000-100000L),
                "instanceid",Long.toString(openDaily),"count","1",
                "idempotency","route-daily-sweep");
            byte[] dailySweepResult=call(reloaded,"/level/sweep",dailySweep,new byte[0],
                catalog,main,daily,furnace);
            JSONObject afterDailySweep=snapshot(dir);
            check(lootResults(dailySweepResult)==1 &&
                ProtoWire.parse(dailySweepResult).number(3,-1)==170 &&
                afterDailySweep.getJSONObject("dailyBattleStages")
                    .getJSONObject(Long.toString(openDaily)).getInt("sweeps")==1,
                "Daily sweep did not settle through the shared route");
            long dailySweepRevision=afterDailySweep.getLong("saveRevision");
            check(Arrays.equals(dailySweepResult,call(reloaded,"/level/sweep",dailySweep,
                new byte[0],catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==dailySweepRevision,
                "Daily sweep retry paid twice");
            boolean limitRejected=false;
            try{call(reloaded,"/level/sweep",form("chapid",dailySweep.get("chapid"),
                "instanceid",Long.toString(openDaily),"count","10"),new byte[0],
                catalog,main,daily,furnace);}catch(java.io.IOException expected){limitRejected=true;}
            check(limitRejected && snapshot(dir).getLong("saveRevision")==dailySweepRevision,
                "Rejected daily batch changed the account");
            Map<String,String> furnaceSweep=form("chapid","3020007",
                "instanceid",Long.toString(depth),"count","1",
                "idempotency","route-furnace-sweep");
            byte[] furnaceSweepResult=call(reloaded,"/level/sweep",furnaceSweep,
                new byte[0],catalog,main,daily,furnace);
            JSONObject afterFurnaceSweep=snapshot(dir);
            check(lootResults(furnaceSweepResult)==1 &&
                ProtoWire.parse(furnaceSweepResult).number(3,-1)==160 &&
                afterFurnaceSweep.getInt("furnaceCoreClaims")==2 &&
                afterFurnaceSweep.getJSONObject("furnaceStages")
                    .getJSONObject(Long.toString(depth)).getInt("sweeps")==1,
                "Furnace sweep did not consume the final daily core selection");
            long furnaceSweepRevision=afterFurnaceSweep.getLong("saveRevision");
            check(Arrays.equals(furnaceSweepResult,call(reloaded,"/level/sweep",furnaceSweep,
                new byte[0],catalog,main,daily,furnace)) &&
                snapshot(dir).getLong("saveRevision")==furnaceSweepRevision,
                "Furnace sweep retry paid twice");
            boolean exhaustedStartRejected=false;
            try{call(reloaded,"/level/startBattle",form("instanceid",Long.toString(depth),
                "idempotency","after-quota","wantweapon",weapon),
                startSeed,catalog,main,daily,furnace);}
            catch(java.io.IOException expected){exhaustedStartRejected=true;}
            boolean exhaustedSweepRejected=false;
            try{call(reloaded,"/level/sweep",form("chapid","3020007",
                "instanceid",Long.toString(depth),"count","1",
                "idempotency","after-quota-sweep"),new byte[0],
                catalog,main,daily,furnace);}
            catch(java.io.IOException expected){exhaustedSweepRejected=true;}
            check(exhaustedStartRejected && exhaustedSweepRejected &&
                snapshot(dir).getLong("saveRevision")==furnaceSweepRevision &&
                snapshot(dir).getLong("stamina")==160,
                "Exhausted furnace entry changed the account or stamina");
            boolean chapterRejected=false;
            try{call(reloaded,"/level/sweep",form("chapid","3020006",
                "instanceid",Long.toString(depth),"count","1"),new byte[0],
                catalog,main,daily,furnace);}catch(java.io.IOException expected){chapterRejected=true;}
            check(chapterRejected && snapshot(dir).getLong("saveRevision")==furnaceSweepRevision,
                "Wrong furnace chapter changed the account");
            System.out.println("DAILY_FURNACE_ROUTING_SELF_TEST_OK");
        }finally{
            Files.walkFileTree(dir,new SimpleFileVisitor<Path>(){
                public FileVisitResult visitFile(Path file,BasicFileAttributes attributes)throws java.io.IOException{
                    Files.delete(file);return FileVisitResult.CONTINUE;
                }
                public FileVisitResult postVisitDirectory(Path folder,java.io.IOException error)throws java.io.IOException{
                    if(error!=null)throw error;
                    Files.delete(folder);return FileVisitResult.CONTINUE;
                }
            });
        }
    }
}
