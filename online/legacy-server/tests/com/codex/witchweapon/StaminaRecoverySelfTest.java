package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import org.json.JSONObject;

/** Deterministic lazy-regeneration edges plus a real LocalSave login round-trip. */
public final class StaminaRecoverySelfTest {
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static JSONObject state(long stamina,long anchor,int cap)throws Exception{
        return new JSONObject().put("starterProfile",1).put("stamina",stamina)
            .put("staminaRegenAt",anchor).put("staminaRegenCap",cap);
    }
    private static JSONObject copy(JSONObject value)throws Exception{return new JSONObject(value.toString());}
    private static JSONObject saved(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(new File(directory,"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8));
    }
    public static void main(String[] args)throws Exception{
        check(StaminaRecovery.PERIOD_SECONDS==300,"Original AP period changed");
        check(StaminaRecovery.capAtLevel(1)==60&&StaminaRecovery.capAtLevel(20)==98&&
            StaminaRecovery.capAtLevel(21)==100&&StaminaRecovery.capAtLevel(22)==101&&
            StaminaRecovery.capAtLevel(50)==129&&StaminaRecovery.capAtLevel(100)==179,
            "Original level AP cap changed");
        JSONObject partial=state(50,1000,60);
        check(!StaminaRecovery.advance(partial,1,1299)&&partial.getLong("stamina")==50,
            "Partial period minted AP");
        check(StaminaRecovery.advance(partial,1,1300)&&partial.getLong("stamina")==51&&
            partial.getLong("staminaRegenAt")==1300,"First interval was lost");
        check(StaminaRecovery.advance(partial,1,1600)&&partial.getLong("stamina")==52&&
            partial.getLong("staminaRegenAt")==1600,"Second interval was lost");
        check(!StaminaRecovery.advance(partial,1,1500)&&partial.getLong("stamina")==52&&
            partial.getLong("staminaRegenAt")==1600,"Clock rollback minted AP");
        JSONObject spent=copy(partial);spent.put("stamina",45);
        StaminaRecovery.beforeCommit(partial,spent,1650);
        check(spent.getLong("staminaRegenAt")==1600,"Spending below cap reset partial time");
        check(StaminaRecovery.advance(spent,1,1900)&&spent.getLong("stamina")==46,
            "Spending disabled the next recovery");

        JSONObject exhausted=state(0,1000,60);
        check(StaminaRecovery.advance(exhausted,1,Long.MAX_VALUE/4)&&
            exhausted.getLong("stamina")==60&&exhausted.getLong("staminaRegenAt")==0,
            "Long offline interval overflowed or exceeded cap");
        JSONObject banked=state(200,0,60);
        check(!StaminaRecovery.advance(banked,1,1000)&&banked.getLong("stamina")==200,
            "Over-cap starter AP should not regenerate");
        JSONObject afterSpend=copy(banked);afterSpend.put("stamina",59);
        StaminaRecovery.beforeCommit(banked,afterSpend,2000);
        check(afterSpend.getLong("staminaRegenAt")==2000,"Crossing below cap did not start clock");
        check(StaminaRecovery.advance(afterSpend,1,2300)&&afterSpend.getLong("stamina")==60&&
            afterSpend.getLong("staminaRegenAt")==0,"Full AP did not stop clock");
        JSONObject legacy=new JSONObject().put("starterProfile",1).put("stamina",50);
        check(StaminaRecovery.advance(legacy,1,1000)&&legacy.getLong("stamina")==50&&
            legacy.getLong("staminaRegenAt")==1000,"Legacy save received unearned AP");
        JSONObject levelUp=state(60,0,60);
        check(StaminaRecovery.advance(levelUp,2,3000)&&levelUp.getInt("staminaRegenCap")==62&&
            levelUp.getLong("staminaRegenAt")==3000,"Raised cap did not start AP clock");

        if(args.length!=2)throw new IllegalArgumentException("Arguments: empty-test-dir responses.json");
        File directory=new File(args[0]);
        check(directory.isDirectory()&&directory.list().length==0,"Empty test directory required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        byte[] roleSeed=Base64.decode(responses.getJSONObject("/role/login").getString("base64"),Base64.DEFAULT);
        LocalSave live=new LocalSave(directory);
        live.respond("/role/login",Collections.<String,String>emptyMap(),roleSeed,catalog);
        JSONObject initial=saved(directory);
        long firstRevision=initial.getLong("saveRevision");
        check(initial.getLong("stamina")==200&&!initial.has("staminaRegenAt"),
            "Initial login changed over-cap AP");
        live.respond("/role/login",Collections.<String,String>emptyMap(),roleSeed,catalog);
        check(saved(directory).getLong("saveRevision")==firstRevision,
            "Full AP caused a needless write on each request");

        initial.put("stamina",50).put("staminaRegenAt",System.currentTimeMillis()/1000-620);
        Files.write(new File(directory,"offline_save_v1.json").toPath(),
            (initial.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        live=new LocalSave(directory);
        byte[] returned=live.respond("/role/login",Collections.<String,String>emptyMap(),roleSeed,catalog);
        JSONObject restored=saved(directory);
        check(restored.getLong("stamina")==52,"Offline AP not persisted on login");
        ProtoWire sync=ProtoWire.parse(returned);
        check(sync.number(4,-1)==52,"Login protobuf did not return recovered AP");
        long restoredRevision=restored.getLong("saveRevision");
        live.respond("/role/login",Collections.<String,String>emptyMap(),roleSeed,catalog);
        check(saved(directory).getLong("saveRevision")==restoredRevision,
            "Repeated login duplicated AP or rewrote unchanged save");
        System.out.println("StaminaRecoverySelfTest passed");
    }
}
