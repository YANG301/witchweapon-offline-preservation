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

/** Entry loss, victory charge, response clock and retry after save reload. */
public final class MainlineStaminaSelfTest {
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Map<String,String> form(String... parts){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<parts.length;i+=2)result.put(parts[i],parts[i+1]);
        return result;
    }
    private static byte[] call(LocalSave save,String route,Map<String,String> args,
                               JSONObject responses,StageCatalog stages)throws Exception{
        byte[] seed=Base64.decode(responses.getJSONObject(route).getString("base64"),Base64.DEFAULT);
        return save.respond(route,args,seed,responses.getJSONObject("_catalog"),null,stages);
    }
    private static JSONObject saved(File dir)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8));
    }
    private static LocalSave prepare(File dir,long stamina,long anchor)throws Exception{
        check(dir.mkdir(),"Use a fresh test directory");
        LocalSave initial=new LocalSave(dir);
        initial.roleSummary();
        JSONObject state=saved(dir);
        state.put("roleCreated",true).put("legacyRoleId",1).put("namePending",false)
            .put("stamina",stamina).put("staminaRegenCap",60).put("staminaRegenAt",anchor);
        Files.write(new File(dir,"offline_save_v1.json").toPath(),
            (state.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        return new LocalSave(dir);
    }
    private static void invalidStart(LocalSave save,JSONObject responses,StageCatalog stages,
                                     String key)throws Exception{
        try{call(save,"/level/startBattle",form("instanceid","3110001002",
            "idempotency",key),responses,stages);
            throw new AssertionError("Insufficient AP admitted a battle");
        }catch(IOException expected){}
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("fresh-dir responses.json stage_catalog.json");
        File root=new File(args[0]);
        check(root.isDirectory()&&root.list().length==0,"Empty test root required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8));
        StageCatalog stages=new StageCatalog(new JSONObject(new String(Files.readAllBytes(
            new File(args[2]).toPath()),StandardCharsets.UTF_8)));
        long anchor=System.currentTimeMillis()/1000-60;
        LocalSave save=prepare(new File(root,"main"),10,anchor);
        Map<String,String> first=form("instanceid","3110001002","idempotency","loss-1");
        call(save,"/level/startBattle",first,responses,stages);
        check(saved(new File(root,"main")).getLong("stamina")==9,
            "Mainline did not charge one entry AP");
        call(save,"/level/startBattle",first,responses,stages);
        check(saved(new File(root,"main")).getLong("stamina")==9,
            "Repeated start charged entry AP twice");
        byte[] loss=call(save,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","0","stars","0"),responses,stages);
        ProtoWire lose=ProtoWire.parse(loss);
        check(lose.number(1,-1)==9 && lose.number(2,-1)==anchor &&
              saved(new File(root,"main")).getLong("stamina")==9,
            "Failure charged victory AP or returned the wrong stamina clock");
        LocalSave resumed=new LocalSave(new File(root,"main"));
        check(Arrays.equals(loss,call(resumed,"/level/pushMainLineProgress",
                form("instanceid","3110001002","pass","0","stars","0"),responses,stages)) &&
              saved(new File(root,"main")).getLong("stamina")==9,
            "Failure settlement retried with a second charge");
        call(resumed,"/level/startBattle",
            form("instanceid","3110001002","idempotency","win-2"),responses,stages);
        check(saved(new File(root,"main")).getLong("stamina")==8,
            "Second run did not charge entry AP");
        byte[] victory=call(resumed,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","1"),responses,stages);
        ProtoWire win=ProtoWire.parse(victory);
        check(win.number(1,-1)==4 && win.number(2,-1)==anchor &&
            saved(new File(root,"main")).getLong("stamina")==4 &&
            saved(new File(root,"main")).getJSONObject("mainlineStages")
                .getJSONObject("3110001002").getInt("stars")==3,
            "Simple-campaign victory failed to charge AP, award stars or return live AP");
        check(Arrays.equals(victory,call(resumed,"/level/pushMainLineProgress",
                form("instanceid","3110001002","pass","1"),responses,stages)) &&
              saved(new File(root,"main")).getLong("stamina")==4,
            "Victory retry double-charged AP");
        invalidStart(resumed,responses,stages,"not-enough");
        check(saved(new File(root,"main")).getLong("stamina")==4,
            "Rejected start changed AP");

        // A battle already running during the upgrade has no entry marker.
        // It must still pay the full five AP exactly once on victory.
        File oldDir=new File(root,"old-active");
        prepare(oldDir,10,anchor);
        JSONObject old=saved(oldDir);
        old.put("active",true).put("activeStage",3110001002L).put("startKey","old-key");
        Files.write(new File(oldDir,"offline_save_v1.json").toPath(),
            (old.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave migrated=new LocalSave(oldDir);
        byte[] oldWin=call(migrated,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","1","stars","3"),responses,stages);
        check(ProtoWire.parse(oldWin).number(1,-1)==5 &&
            saved(oldDir).getLong("stamina")==5 &&
            Arrays.equals(oldWin,call(migrated,"/level/pushMainLineProgress",
                form("instanceid","3110001002","pass","1","stars","3"),responses,stages)),
            "Pre-upgrade active battle charged incorrectly or repeated charge");
        System.out.println("MAINLINE_STAMINA_SELF_TEST_OK");
    }
}
