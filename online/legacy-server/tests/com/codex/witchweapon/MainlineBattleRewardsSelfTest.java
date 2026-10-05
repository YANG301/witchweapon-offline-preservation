package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

public final class MainlineBattleRewardsSelfTest {
    private static void check(boolean yes,String description){
        if(!yes)throw new AssertionError(description);
    }
    private static Map<String,String> form(String... pairs){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)result.put(pairs[i],pairs[i+1]);
        return result;
    }
    private static byte[] call(LocalSave save,JSONObject responses,StageCatalog stages,
                               String route,Map<String,String> args)throws Exception{
        JSONObject fixture=responses.getJSONObject(route);
        byte[] seed=fixture.has("base64")?
            Base64.decode(fixture.getString("base64"),Base64.DEFAULT):new byte[0];
        return save.respond(route,args,seed,responses.getJSONObject("_catalog"),null,stages);
    }
    private static JSONObject disk(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(new File(directory,
            "offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }
    private static int lootCount(byte[] response,int type,long id)throws Exception{
        int count=0;
        for(ProtoWire.Field field:ProtoWire.parse(response).fields){
            if(field.number!=3 || field.type!=2)continue;
            ProtoWire loot=ProtoWire.parse(field.data);
            if(loot.number(1,-1)==type && (id<0 || loot.number(2,0)==id))count++;
        }
        return count;
    }
    private static String owned(JSONObject state,String id)throws Exception{
        return state.getJSONObject("ownedServants").getString(id);
    }
    private static long exp(JSONObject state,String id)throws Exception{
        return LocalEconomy.decode(owned(state,id)).number(3,0);
    }
    private static long level(JSONObject state,String id)throws Exception{
        return LocalEconomy.decode(owned(state,id)).number(2,1);
    }

    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("fresh-dir responses.json stage_catalog.json");
        File root=new File(args[0]),aDir=new File(root,"a"),bDir=new File(root,"b"),
            cDir=new File(root,"c");
        check(root.isDirectory() && aDir.mkdir() && bDir.mkdir() && cDir.mkdir(),
            "Fresh account directories required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8));
        StageCatalog stages=new StageCatalog(new JSONObject(new String(
            Files.readAllBytes(new File(args[2]).toPath()),StandardCharsets.UTF_8)));
        stages.install(responses);
        JSONObject catalog=responses.getJSONObject("_catalog");
        LocalSave a=new LocalSave(aDir),b=new LocalSave(bDir),c=new LocalSave(cDir);
        call(a,responses,stages,"/servant/servants",form());
        call(b,responses,stages,"/servant/servants",form());
        call(c,responses,stages,"/servant/servants",form());
        JSONObject a0=disk(aDir),b0=disk(bDir);

        JSONObject noPartyBefore=disk(cDir);
        call(c,responses,stages,"/level/startBattle",
            form("instanceid","3110001001","idempotency","no-party"));
        byte[] noPartyWin=call(c,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","1","stars","3"));
        JSONObject noPartyAfter=disk(cDir);
        check(lootCount(noPartyWin,2,1411005)==1 && lootCount(noPartyWin,11,-1)==0 &&
              owned(noPartyAfter,"10010001").equals(owned(noPartyBefore,"10010001")),
              "Unknown combat party received servant EXP or lost its item drop");

        try{
            call(a,responses,stages,"/level/startBattle",form("instanceid","3110001001",
                "idempotency","invalid-party","servantcardids","99999999"));
            throw new AssertionError("Unowned combat participant admitted");
        }catch(java.io.IOException expected){}
        check(!disk(aDir).optBoolean("active",false),"Rejected party opened a battle");

        call(a,responses,stages,"/level/startBattle",form("instanceid","3110001001",
            "idempotency","first","servantcardids","10010001|10010101"));
        byte[] victory=call(a,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","1","stars","3"));
        JSONObject a1=disk(aDir);
        check(lootCount(victory,2,1411005)==1 && lootCount(victory,11,-1)==1,
            "Manual battle omitted original-listed equipment or servant EXP display");
        check(a1.getJSONObject("equips").optLong("1411005",0)==
              a0.getJSONObject("equips").optLong("1411005",0)+1,
              "Manual battle equipment was not committed to the inventory");
        check(level(a1,"10010001")>level(a0,"10010001") ||
              exp(a1,"10010001")>exp(a0,"10010001"),
              "First participating servant gained no EXP");
        check(level(a1,"10010101")>level(a0,"10010101") ||
              exp(a1,"10010101")>exp(a0,"10010101"),
              "Second participating servant gained no EXP");
        check(owned(a1,"10010201").equals(owned(a0,"10010201")),
            "Non-participating servant received battle EXP");
        byte[] replay=call(a,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","1","stars","3"));
        check(Arrays.equals(victory,replay) &&
              disk(aDir).getJSONObject("equips").optLong("1411005",0)==
              a1.getJSONObject("equips").optLong("1411005",0) &&
              owned(disk(aDir),"10010001").equals(owned(a1,"10010001")),
              "Manual settlement replay duplicated equipment or servant EXP");

        call(a,responses,stages,"/level/startBattle",form("instanceid","3110001002",
            "idempotency","failed","servantcardids","10010001"));
        JSONObject beforeLoss=disk(aDir);
        byte[] lost=call(a,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","0","stars","0"));
        JSONObject afterLoss=disk(aDir);
        check(lootCount(lost,2,-1)==0 && lootCount(lost,11,-1)==0 &&
              beforeLoss.getJSONObject("equips").toString().equals(afterLoss.getJSONObject("equips").toString()) &&
              owned(beforeLoss,"10010001").equals(owned(afterLoss,"10010001")),
              "Failed mainline battle awarded a drop or servant EXP");
        check(disk(bDir).getJSONObject("equips").toString().equals(b0.getJSONObject("equips").toString()) &&
              owned(disk(bDir),"10010001").equals(owned(b0,"10010001")),
              "Battle rewards leaked to another account");

        // The original client selects servants in combat role info, which can
        // occur before or after the stage start request. No Android patch is
        // required for either order if the original party argument is present.
        call(b,responses,stages,"/combat/role/info",
            form("servantcardids","10010001|10010101"));
        call(b,responses,stages,"/level/startBattle",
            form("instanceid","3110001001","idempotency","prepared-party"));
        call(b,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001001","pass","1","stars","3"));
        check(level(disk(bDir),"10010001")>level(b0,"10010001") ||
              exp(disk(bDir),"10010001")>exp(b0,"10010001"),
              "Pre-battle original combat selection was not credited");
        JSONObject beforeLateSelection=disk(bDir);
        call(b,responses,stages,"/level/startBattle",
            form("instanceid","3110001002","idempotency","late-party"));
        call(b,responses,stages,"/combat/role/info",
            form("instanceid","3110001002","servantcardids","10010201"));
        call(b,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","1","stars","3"));
        JSONObject afterLateSelection=disk(bDir);
        check((level(afterLateSelection,"10010201")>level(beforeLateSelection,"10010201") ||
               exp(afterLateSelection,"10010201")>exp(beforeLateSelection,"10010201")) &&
              owned(afterLateSelection,"10010001").equals(owned(beforeLateSelection,"10010001")),
              "In-battle original combat selection did not replace the prior party");

        JSONObject atCap=new JSONObject(afterLoss.toString());
        ProtoWire servant=LocalEconomy.decode(atCap.getJSONObject("ownedServants").getString("10010001"));
        servant.set(2,65).set(3,0);
        atCap.getJSONObject("ownedServants").put("10010001",LocalEconomy.encode(servant));
        Files.write(new File(aDir,"offline_save_v1.json").toPath(),
            (atCap.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        a=new LocalSave(aDir);
        call(a,responses,stages,"/level/startBattle",form("instanceid","3110001002",
            "idempotency","cap","servantcardids","10010001"));
        byte[] capVictory=call(a,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110001002","pass","1","stars","3"));
        check(level(disk(aDir),"10010001")==65 && exp(disk(aDir),"10010001")==0 &&
              lootCount(capVictory,11,-1)==0,
              "Servant EXP grew past the restored level cap");
        check(lootCount(capVictory,2,1411003)==1,
              "Second mainline stage did not choose its own original-listed drop");
        long itemBefore=disk(aDir).getJSONObject("items").optLong("40130007",0);
        call(a,responses,stages,"/level/startBattle",form("instanceid","3110002011",
            "idempotency","item-stage"));
        byte[] itemVictory=call(a,responses,stages,"/level/pushMainLineProgress",
            form("instanceid","3110002011","pass","1","stars","3"));
        check(lootCount(itemVictory,3,40130007L)==1 &&
              disk(aDir).getJSONObject("items").optLong("40130007",0)==itemBefore+1,
              "Original-listed item drop was not both displayed and persisted");
        System.out.println("MAINLINE_BATTLE_REWARDS_SELF_TEST_OK");
    }
}
