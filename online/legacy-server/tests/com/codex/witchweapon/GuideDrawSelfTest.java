package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Random;
import java.util.Set;

/** The original guide makes one gold and then one diamond draw. */
public final class GuideDrawSelfTest {
    private static void require(boolean value,String message){
        if(!value)throw new AssertionError(message);
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
    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }
    private static ProtoWire resultJob(byte[] response,long id)throws Exception{
        ProtoWire result=ProtoWire.parse(response);
        ProtoWire extra=ProtoWire.parse(result.data(2));
        ProtoWire achievement=ProtoWire.parse(extra.data(2));
        for(ProtoWire.Field field:achievement.fields)if(field.number==1&&field.type==2){
            ProtoWire job=ProtoWire.parse(field.data);
            if(job.number(1,0)==id)return job;
        }
        return null;
    }
    private static int lootCount(byte[] response)throws Exception{
        int count=0;
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2)count++;
        return count;
    }
    private static long lootId(byte[] response,int type)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2){
                ProtoWire loot=ProtoWire.parse(field.data);
                if(loot.number(1,0)==type)return loot.number(2,0);
            }
        return 0;
    }
    private static int ownedWeaponCount(JSONObject save,long servant,long weapon)throws Exception{
        String stored=save.getJSONObject("ownedServants").getString(String.valueOf(servant));
        ProtoWire data=ProtoWire.parse(Base64.decode(stored,Base64.DEFAULT));
        int count=0;
        for(ProtoWire.Field field:data.fields)if(field.number==13&&field.type==2&&
            ProtoWire.parse(field.data).number(1,0)==weapon)count++;
        return count;
    }
    private static Set<Long> publishedOwners(LocalSave save,JSONObject catalog)throws Exception{
        byte[] response=save.respond("/servant/servants",Collections.<String,String>emptyMap(),
            new byte[0],catalog);
        Set<Long> owners=new HashSet<Long>();
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2){
                long id=ProtoWire.parse(field.data).number(1,0);
                require(id>0&&owners.add(id),"Owned list has an invalid or repeated character");
            }
        return owners;
    }
    private static void ownershipMatchesSave(LocalSave save,File directory,JSONObject catalog)
            throws Exception{
        Set<Long> expected=new HashSet<Long>();
        JSONObject owned=read(directory).getJSONObject("ownedServants");
        for(java.util.Iterator<String> ids=owned.keys();ids.hasNext();)
            expected.add(Long.parseLong(ids.next()));
        require(publishedOwners(save,catalog).equals(expected),
            "Character list publishes unowned catalog stubs as owned characters");
    }
    private static long taskStatus(byte[] response,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(response).fields)
            if(field.number==1&&field.type==2){
                ProtoWire job=ProtoWire.parse(field.data);
                if(job.number(1,0)==id)return job.number(2,Long.MIN_VALUE);
            }
        return Long.MIN_VALUE;
    }
    private static void rejected(LocalSave save,File dir,JSONObject catalog,
                                 Map<String,String> args)throws Exception{
        byte[] before=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        try{
            save.respond("/guide/draw",args,new byte[0],catalog);
            throw new AssertionError("Invalid guide draw accepted: "+args);
        }catch(java.io.IOException expected){}
        require(Arrays.equals(before,Files.readAllBytes(
            new File(dir,"offline_save_v1.json").toPath())),
            "Rejected guide draw changed the save");
    }
    private static void secondPullCandidates(JSONObject afterFirst,JSONObject catalog,File root)
            throws Exception{
        Set<Long> results=new HashSet<Long>();
        JSONObject previousOwners=afterFirst.getJSONObject("ownedServants");
        // Exercise reproducible random selections, including signed seeds;
        // every possible result must open the first-get description lesson.
        for(int i=0;i<128;i++){
            JSONObject trial=new JSONObject(afterFirst.toString());
            byte[] second=LocalEconomy.draw(trial,catalog,"/guide/draw",form("drawserial","2"),
                new Random(0x9e3779b97f4a7c15L*i));
            long servant=lootId(second,1),weapon=lootId(second,4);
            require(!previousOwners.has(String.valueOf(servant))&&
                trial.getJSONObject("ownedServants").length()==previousOwners.length()+1&&
                ownedWeaponCount(trial,servant,weapon)==1,
                "Second tutorial draw selected an already owned witch");
            require(trial.getLong("gold")==afterFirst.getLong("gold")&&
                trial.getLong("rmb")==afterFirst.getLong("rmb")&&trial.getLong("drawCount")==2,
                "Second tutorial draw charged currency or granted multiple pulls");
            results.add(servant);
        }
        require(results.size()>1,"Seeded second-pull test did not exercise different candidates");

        JSONObject allOwned=new JSONObject(afterFirst.toString());
        allOwned.put("ownedServants",new JSONObject(catalog.getJSONObject("servants").toString()));
        long onlyMissing=results.iterator().next();
        for(int i=0;i<16;i++){
            JSONObject trial=new JSONObject(allOwned.toString());
            trial.getJSONObject("ownedServants").remove(String.valueOf(onlyMissing));
            byte[] second=LocalEconomy.draw(trial,catalog,"/guide/draw",form("drawserial","2"),
                new Random(i));
            require(lootId(second,1)==onlyMissing,
                "Tutorial pull did not use the only remaining unowned witch");
        }
        // Full collection is an inconsistent unfinished-guide save. Reject
        // before altering currency, rewards, guide tasks, caches or revision.
        File allOwnedDir=new File(root,"all-owned-second-pull");
        require(allOwnedDir.mkdir(),"Fresh all-owned rejection directory required");
        Files.write(new File(allOwnedDir,"offline_save_v1.json").toPath(),
            allOwned.toString(2).getBytes(StandardCharsets.UTF_8));
        rejected(new LocalSave(allOwnedDir),allOwnedDir,catalog,form("drawserial","2"));
        JSONObject remaining=read(allOwnedDir);
        require(!remaining.has("starterGuideDrawResponse2")&&
            !remaining.getJSONObject("tutorialTasks").has("509005011"),
            "Rejected second tutorial draw marked its task or response complete");
        JSONObject ordinary=new JSONObject(allOwned.toString());
        ordinary.put("starterProfile",0);
        byte[] duplicate=LocalEconomy.draw(ordinary,catalog,"/draw/rmb/single",form(),new Random(42));
        require(lootCount(duplicate)==2&&lootId(duplicate,1)>0&&lootId(duplicate,4)>0,
            "Tutorial first-get requirement leaked into ordinary preservation draws");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: test-dir responses.json");
        File dir=new File(args[0]);
        require(dir.isDirectory(),"Fresh test directory required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8)),catalog=responses.getJSONObject("_catalog");
        LocalSave save=new LocalSave(dir);
        save.respond("/role/create",Collections.<String,String>emptyMap(),
            fixture(responses,"/role/create"),catalog);
        save.respond("/backpack/item",Collections.<String,String>emptyMap(),
            fixture(responses,"/backpack/item"),catalog);
        ownershipMatchesSave(save,dir,catalog);
        Set<Long> initialOwners=publishedOwners(save,catalog);
        require(initialOwners.size()==4&&!initialOwners.contains(10011501L),
            "First guide character is already marked owned before it is drawn");
        rejected(save,dir,catalog,form("drawserial","2"));
        rejected(save,dir,catalog,form("drawserial","0"));
        rejected(save,dir,catalog,form("drawserial","3"));
        rejected(save,dir,catalog,form("guidedrawserial","2"));
        rejected(save,dir,catalog,form("guidedrawserial","0"));
        rejected(save,dir,catalog,form("guidedrawserial","3"));
        rejected(save,dir,catalog,form("guidedrawserial",""));
        rejected(save,dir,catalog,form("guidedrawserial","01"));
        rejected(save,dir,catalog,form("guidedrawserial","1","drawserial","2"));

        byte[] first=save.respond("/guide/draw",form("guidedrawserial","1","times","10",
            "idempotency","shared"),new byte[0],catalog);
        ProtoWire firstJob=resultJob(first,509005010L);
        require(lootCount(first)==2&&lootId(first,1)==10011501L&&
            lootId(first,4)==1701150101L&&firstJob!=null&&firstJob.number(2,-1)==0&&
            firstJob.number(3,0)==1&&firstJob.number(5,0)==1&&
            "030".equals(new String(firstJob.data(4),StandardCharsets.UTF_8))&&
            resultJob(first,509005011L)==null,"First guide draw did not complete gold job only");
        JSONObject afterFirst=read(dir);
        ownershipMatchesSave(save,dir,catalog);
        Set<Long> firstOwners=publishedOwners(save,catalog);
        require(firstOwners.size()==initialOwners.size()+1&&firstOwners.contains(10011501L)&&
            ownedWeaponCount(afterFirst,10011501L,1701150101L)==1,
            "First guide character and weapon ownership was not published after the draw");
        require(afterFirst.getLong("drawCount")==1&&
            afterFirst.getJSONObject("tutorialTasks").getInt("509005010")==0&&
            !afterFirst.getJSONObject("tutorialTasks").has("509005011"),
            "First guide draw was not persisted independently");
        byte[] beforeReplay=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        require(Arrays.equals(first,save.respond("/guide/draw",form("drawserial","1",
            "idempotency","changed"),new byte[0],catalog))&&
            Arrays.equals(first,save.respond("/guide/draw",form("guidedrawserial","1",
                "drawserial","1"),new byte[0],catalog))&&
            Arrays.equals(first,save.respond("/guide/draw",Collections.<String,String>emptyMap(),
                new byte[0],catalog))&&
            Arrays.equals(beforeReplay,Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath())),
            "Native/alias/missing serial replay changed response or granted another reward");

        secondPullCandidates(afterFirst,catalog,dir);

        byte[] second=save.respond("/guide/draw",form("guidedrawserial","2",
            "idempotency","shared"),new byte[0],catalog);
        ProtoWire secondJob=resultJob(second,509005011L);
        require(lootCount(second)==2&&lootId(second,4)!=0&&
            !firstOwners.contains(lootId(second,1))&&
            lootId(second,4)!=1701150101L&&secondJob!=null&&secondJob.number(2,-1)==0&&
            "033".equals(new String(secondJob.data(4),StandardCharsets.UTF_8))&&
            resultJob(second,509005010L)==null&&!Arrays.equals(first,second),
            "Second guide draw reused the gold result or missed diamond job");
        JSONObject afterSecond=read(dir);
        ownershipMatchesSave(save,dir,catalog);
        require(afterSecond.getLong("drawCount")==2&&
            afterSecond.getJSONObject("tutorialTasks").getInt("509005010")==0&&
            afterSecond.getJSONObject("tutorialTasks").getInt("509005011")==0&&
            ownedWeaponCount(afterSecond,10011501L,1701150101L)==1,
            "Two guide draws did not persist both tutorial jobs");
        byte[] all=save.respond("/task/all",Collections.<String,String>emptyMap(),
            fixture(responses,"/task/all"),catalog);
        require(taskStatus(all,509005010L)==0&&taskStatus(all,509005011L)==0,
            "Task list did not expose both completed guide draws");
        rejected(save,dir,catalog,form("guidedrawserial","2","drawserial","1"));
        rejected(save,dir,catalog,form("guidedrawserial","invalid","drawserial","2"));
        byte[] beforeReload=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        LocalSave reloaded=new LocalSave(dir);
        require(Arrays.equals(first,reloaded.respond("/guide/draw",form("drawserial","1"),
            new byte[0],catalog))&&
            Arrays.equals(second,reloaded.respond("/guide/draw",form("drawserial","2"),
            new byte[0],catalog))&&
            Arrays.equals(second,reloaded.respond("/guide/draw",form("guidedrawserial","2",
                "drawserial","2"),new byte[0],catalog))&&
            Arrays.equals(first,reloaded.respond("/guide/draw",Collections.<String,String>emptyMap(),
                new byte[0],catalog))&&
            Arrays.equals(beforeReload,Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath())),
            "Reloaded guide draw cache was not separately idempotent");
        ownershipMatchesSave(reloaded,dir,catalog);
        System.out.println("GUIDE_DRAW_PASS");
    }
}
