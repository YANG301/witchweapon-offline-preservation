package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Native wire shape, repeat safety and account-local sweep balance. */
public final class StageSweepSelfTest {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Map<String,String> form(String... data){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<data.length;i+=2)result.put(data[i],data[i+1]);
        return result;
    }
    private static byte[] call(LocalSave save,String path,Map<String,String> args,
                               JSONObject responses,StageCatalog stages)throws Exception{
        JSONObject fixture=responses.getJSONObject(path);
        byte[] seed=Base64.decode(fixture.getString("base64"),Base64.DEFAULT);
        return save.respond(path,args,seed,responses.getJSONObject("_catalog"),null,stages);
    }
    private static JSONObject disk(File dir)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8));
    }
    private static void rejected(LocalSave save,Map<String,String> args,JSONObject responses,
                                 StageCatalog stages)throws Exception{
        try{call(save,"/level/sweep",args,responses,stages);
            throw new AssertionError("Invalid sweep was accepted: "+args.get("instanceid"));
        }catch(IOException expected){}
    }
    private static long flag(byte[] progress,long stageId,int field)throws Exception{
        for(ProtoWire.Field chapter:ProtoWire.parse(progress).fields){
            if(chapter.number!=1 || chapter.type!=2)continue;
            for(ProtoWire.Field entry:ProtoWire.parse(chapter.data).fields){
                if(entry.number!=2 || entry.type!=2)continue;
                ProtoWire level=ProtoWire.parse(entry.data);
                if(level.number(1,0)==stageId)return level.number(field,-1);
            }
        }
        throw new AssertionError("Missing stage "+stageId);
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("fresh-dir responses.json stage_catalog.json");
        File root=new File(args[0]),alice=new File(root,"alice"),bob=new File(root,"bob");
        check(root.isDirectory()&&alice.mkdir()&&bob.mkdir(),"Use a fresh test directory");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),StandardCharsets.UTF_8));
        StageCatalog stages=new StageCatalog(new JSONObject(new String(Files.readAllBytes(
            new File(args[2]).toPath()),StandardCharsets.UTF_8)));
        LocalSave bootstrap=new LocalSave(alice);
        bootstrap.roleSummary();
        JSONObject state=disk(alice);
        state.put("roleCreated",true).put("legacyRoleId",1).put("namePending",false)
            .put("stamina",40).put("gold",100).put("exp",0);
        JSONObject stageProgress=new JSONObject().put("wins",1).put("stars",3)
            .put("attempts",2).put("firstRewardClaimed",true);
        JSONObject noRepeat=new JSONObject().put("wins",1).put("stars",3)
            .put("attempts",1).put("firstRewardClaimed",true);
        JSONObject elite=new JSONObject().put("wins",1).put("stars",3)
            .put("attempts",1).put("firstRewardClaimed",true);
        state.put("mainlineStages",new JSONObject()
            .put("3110001002",stageProgress).put("3110001001",noRepeat)
            .put("3110002011",elite));
        Files.write(new File(alice,"offline_save_v1.json").toPath(),
            (state.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave user=new LocalSave(alice);
        byte[] progress=call(user,"/level/getAllProgress",form(),responses,stages);
        check(flag(progress,3110001002L,7)==1 && flag(progress,3110001001L,7)==0 &&
            flag(progress,3110002011L,7)==1,"Original UI sweep flag is inconsistent");
        Map<String,String> first=form("chapid","3010001","instanceid","3110001002",
            "count","2","idempotency","sweep-first");
        byte[] result=call(user,"/level/sweep",first,responses,stages);
        ProtoWire wire=ProtoWire.parse(result);
        int batches=0;
        for(ProtoWire.Field f:wire.fields)if(f.number==1 && f.type==2){
            ProtoWire lootResult=ProtoWire.parse(f.data);
            ProtoWire loot=ProtoWire.parse(lootResult.data(1));
            check(loot.number(1,0)==13 && loot.number(3,0)==1000,
                "One sweep did not return the original LootResult nesting");
            long expectedEquip=batches==0?1411004L:1411005L;
            boolean listed=false;
            for(ProtoWire.Field item:lootResult.fields)if(item.number==1&&item.type==2){
                ProtoWire detail=ProtoWire.parse(item.data);
                if(detail.number(1,0)==2&&detail.number(2,0)==expectedEquip&&
                   detail.number(4,0)==1)listed=true;
            }
            check(listed,"Sweep omitted its deterministic original-listed stage equipment");
            batches++;
        }
        check(batches==2 && wire.number(3,-1)==30 && wire.number(4,-1)==10,
            "Original SweepResult fields/count/stamina/EXP incorrect");
        JSONObject after=disk(alice);
        check(after.getLong("stamina")==30 && after.getLong("gold")==2100 &&
            after.getLong("exp")==10 && after.getJSONObject("mainlineStages")
                .getJSONObject("3110001002").getInt("sweeps")==2 &&
            after.getJSONObject("mainlineStages").getJSONObject("3110001002")
                .getInt("attempts")==4 && after.optLong("storyCurrency",0)==0 &&
            after.getJSONObject("equips").optLong("1411004",0)==1 &&
            after.getJSONObject("equips").optLong("1411005",0)==1,
            "Sweep did not atomically apply only repeatable rewards/progress");
        LocalSave reloaded=new LocalSave(alice);
        byte[] retry=call(reloaded,"/level/sweep",first,responses,stages);
        check(Arrays.equals(result,retry) && disk(alice).getLong("gold")==2100,
            "Retry after reload awarded twice");
        rejected(reloaded,form("chapid","3010001","instanceid","3110001002",
            "count","3","idempotency","sweep-first"),responses,stages);
        rejected(reloaded,form("chapid","3010001","instanceid","3110001002",
            "count","10","idempotency","not-enough-energy"),responses,stages);
        rejected(reloaded,form("chapid","3010001","instanceid","3110001001",
            "count","1","idempotency","one-time"),responses,stages);
        rejected(reloaded,form("chapid","3010002","instanceid","3110001002",
            "count","1","idempotency","wrong-chapter"),responses,stages);
        rejected(reloaded,form("chapid","3010001","instanceid","3110001002",
            "count","0","idempotency","zero"),responses,stages);
        Map<String,String> nativeRequest=form("chapid","3010002","instanceid","3110002011",
            "count","1","time","1700000000","sign","A123456789BCDEF0");
        byte[] eliteResponse=call(reloaded,"/level/sweep",nativeRequest,responses,stages);
        check(ProtoWire.parse(eliteResponse).number(3,-1)==18 &&
            disk(alice).getLong("gold")==3100,
            "First native elite sweep was not settled");
        // Native time/sign are shared authentication fields, not a unique
        // action ID. A second deliberate tap with the same fields must run.
        byte[] secondElite=call(reloaded,"/level/sweep",nativeRequest,responses,stages);
        JSONObject afterSecond=disk(alice);
        check(ProtoWire.parse(secondElite).number(3,-1)==6 &&
            !Arrays.equals(eliteResponse,secondElite) &&
            afterSecond.getLong("gold")==4100 &&
            afterSecond.getJSONObject("mainlineStages").getJSONObject("3110002011")
                .getInt("sweeps")==2 &&
            afterSecond.getJSONObject("sweepReplay").length()==1,
            "Same native time/sign incorrectly suppressed a deliberate sweep");
        LocalSave other=new LocalSave(bob);
        other.roleSummary();
        rejected(other,first,responses,stages);
        check(disk(bob).getLong("gold")==1000 && disk(bob).getLong("stamina")==200,
            "Another account was affected by a sweep");

        // A preserved-client victory in the temporary simple campaign may
        // have arrived with no stars field. Old saves must regain the native
        // sweep button without relaxing the reconstructed profile's rules.
        File zeroDir=new File(root,"simple-zero");
        check(zeroDir.mkdir(),"Use a fresh zero-star test account");
        LocalSave zeroBoot=new LocalSave(zeroDir);
        zeroBoot.roleSummary();
        JSONObject zero=disk(zeroDir);
        zero.put("roleCreated",true).put("legacyRoleId",1).put("namePending",false)
            .put("stamina",20).put("mainlineStages",new JSONObject().put("3110001002",
                new JSONObject().put("wins",1).put("stars",0).put("attempts",1)
                    .put("firstRewardClaimed",true)));
        Files.write(new File(zeroDir,"offline_save_v1.json").toPath(),
            (zero.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave zeroSave=new LocalSave(zeroDir);
        StageCatalog reconstructed=new StageCatalog(new JSONObject(new String(Files.readAllBytes(
            new File(new File(args[2]).getParentFile(),"stage_catalog_reconstruction.json").toPath()),
            StandardCharsets.UTF_8)));
        byte[] originalProgress=call(zeroSave,"/level/getAllProgress",form(),responses,reconstructed);
        check(flag(originalProgress,3110001002L,3)==0 &&
              flag(originalProgress,3110001002L,7)==0,
            "Reconstructed campaign incorrectly grants free three-star sweep");
        rejected(zeroSave,form("chapid","3010001","instanceid","3110001002",
            "count","1","idempotency","reconstructed-zero"),responses,reconstructed);
        byte[] simpleProgress=call(zeroSave,"/level/getAllProgress",form(),responses,stages);
        check(flag(simpleProgress,3110001002L,3)==1 &&
              flag(simpleProgress,3110001002L,7)==1,
            "Old simple-campaign victory did not display three stars and sweep");
        byte[] zeroSweep=call(zeroSave,"/level/sweep",form("chapid","3010001",
            "instanceid","3110001002","count","1","idempotency","simple-zero"),
            responses,stages);
        check(ProtoWire.parse(zeroSweep).number(3,-1)==15 &&
              disk(zeroDir).getLong("stamina")==15,
            "Old simple-campaign victory could not sweep at the manual cost");
        System.out.println("STAGE_SWEEP_SELF_TEST_OK");
    }
}
