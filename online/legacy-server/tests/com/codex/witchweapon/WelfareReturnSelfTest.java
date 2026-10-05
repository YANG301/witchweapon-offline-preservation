package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONObject;

/** Exercises original-tier rewards, replay safety and the real save route. */
public final class WelfareReturnSelfTest {
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Map<String,String> form(String... entries){
        Map<String,String> result=new LinkedHashMap<String,String>();
        for(int i=0;i<entries.length;i+=2)result.put(entries[i],entries[i+1]);
        return result;
    }
    private static JSONObject snapshot(Path directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(directory.resolve("offline_save_v1.json")),
            StandardCharsets.UTF_8));
    }
    private static long[] tags(byte[] list)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(list).fields){
            ProtoWire row=ProtoWire.parse(field.data);
            if(row.number(2,0)==11){ProtoWire progress=ProtoWire.parse(row.data(101));
                return new long[]{progress.number(1,-1),progress.number(2,-1),progress.number(3,-1)};}
        }
        throw new AssertionError("Welfare activity absent");
    }
    private static void rejected(LocalSave save,Map<String,String> args,JSONObject catalog)throws Exception{
        try{save.respond("/activity/recharge/gain",args,new byte[0],catalog);
            throw new AssertionError("Invalid welfare claim accepted");}
        catch(AssertionError error){throw error;}
        catch(Exception expected){ }
    }
    public static void main(String[] args)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            Paths.get("resources/offline_responses.json")),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        Path alice=Files.createTempDirectory(Paths.get("build"),"welfare-alice-");
        Path bob=Files.createTempDirectory(Paths.get("build"),"welfare-bob-");
        try{
            LocalSave a=new LocalSave(alice.toFile()),b=new LocalSave(bob.toFile());
            a.respond("/role/create",form("name","Alice"),new byte[0],catalog);
            b.respond("/role/create",form("name","Bob"),new byte[0],catalog);
            JSONObject aState=snapshot(alice),bState=snapshot(bob);
            String role=Long.toString(aState.getLong("legacyRoleId"));
            check(!role.equals(Long.toString(bState.getLong("legacyRoleId"))),"Account IDs collided");
            Map<String,String> first=form("roleid",role,"baseid","11","serial","1");
            rejected(a,first,catalog);
            check(snapshot(alice).optLong("welfareReturnClaimedMask")==0,
                "Unreached claim changed the save");
            aState.put("virtualPurchaseCents",52000L);
            Files.write(alice.resolve("offline_save_v1.json"),
                (aState.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            a=new LocalSave(alice.toFile());
            long[] start=tags(a.respond("/activity/list/get",form("roleid",role),new byte[0],catalog));
            check(start[0]==520&&start[1]==3&&start[2]==0,"First two original tiers not eligible");
            rejected(a,form("roleid",role,"baseid","11","serial","2"),catalog);
            byte[] receipt=a.respond("/activity/recharge/gain",first,new byte[0],catalog);
            check(ProtoWire.parse(receipt).fields.size()==2,"First tier loot receipt incomplete");
            JSONObject after=snapshot(alice);
            check(after.optLong("welfareReturnClaimedMask")==1 && after.optLong("gold")==21000 &&
                after.getJSONObject("items").optLong("40240039")==8,
                "First tier rewards not committed atomically");
            byte[] replay=a.respond("/activity/recharge/gain",first,new byte[0],catalog);
            check(java.util.Arrays.equals(receipt,replay)&&
                snapshot(alice).getJSONObject("items").optLong("40240039")==8,
                "Retry granted first tier twice");
            a=new LocalSave(alice.toFile());
            byte[] second=a.respond("/activity/recharge/gain",
                form("roleid",role,"baseid","11","serial","2"),new byte[0],catalog);
            check(ProtoWire.parse(second).fields.size()==2,"Second tier receipt incomplete");
            after=snapshot(alice);
            check(after.optLong("welfareReturnClaimedMask")==3 && after.optLong("rmb")==20 &&
                after.getJSONObject("items").optLong("40350003")==3,
                "Second tier rewards not persisted");
            long[] current=tags(a.respond("/activity/list/get",form("roleid",role),new byte[0],catalog));
            check(current[0]==520&&current[1]==3&&current[2]==3,
                "Claim state did not refresh immediately");
            check(snapshot(bob).optLong("welfareReturnClaimedMask")==0,
                "Another account's welfare state changed");
            rejected(a,form("roleid",Long.toString(bState.getLong("legacyRoleId")),
                "baseid","11","serial","3"),catalog);
            check(WelfareReturn.eligibleMask(888800L)==511,
                "Nine original thresholds changed");
            after.put("virtualPurchaseCents",888800L);
            Files.write(alice.resolve("offline_save_v1.json"),
                (after.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            a=new LocalSave(alice.toFile());
            for(int tier=3;tier<=9;tier++){
                byte[] reward=a.respond("/activity/recharge/gain",
                    form("roleid",role,"baseid","11","serial",Integer.toString(tier)),
                    new byte[0],catalog);
                check(ProtoWire.parse(reward).fields.size()>=2,
                    "Missing original reward at tier "+tier);
            }
            after=snapshot(alice);
            check(after.optLong("welfareReturnClaimedMask")==511 &&
                after.getJSONObject("roleUnlocks").getJSONObject("5").optBoolean("2") &&
                after.getJSONObject("roleUnlocks").getJSONObject("2").optBoolean("3") &&
                after.getJSONObject("roleUnlocks").getJSONObject("3").optBoolean("4") &&
                after.getJSONObject("roleUnlocks").getJSONObject("1").optBoolean("6"),
                "All nine tiers or original cosmetic rewards failed");
            System.out.println("WELFARE_RETURN_CLAIM_SAVE_OK");
        }finally{
            Files.deleteIfExists(alice.resolve("offline_save_v1.json"));
            Files.deleteIfExists(alice.resolve("offline_save_v1.json.bak"));
            Files.deleteIfExists(bob.resolve("offline_save_v1.json"));
            Files.deleteIfExists(bob.resolve("offline_save_v1.json.bak"));
            Files.deleteIfExists(alice);Files.deleteIfExists(bob);
        }
    }
}
