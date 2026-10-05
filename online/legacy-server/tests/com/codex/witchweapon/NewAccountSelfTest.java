package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Verifies the beginner profile without changing pre-existing preservation saves. */
public final class NewAccountSelfTest {
    private static void require(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    private static JSONObject read(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }
    private static int guideState(byte[] bytes,int recId)throws Exception{
        ProtoWire points=ProtoWire.parse(bytes);
        for(ProtoWire.Field field:points.fields){
            if(field.number!=1||field.type!=2)continue;
            ProtoWire point=ProtoWire.parse(field.data);
            if(point.number(1,0)==recId)return (int)point.number(2,Integer.MIN_VALUE);
        }
        return Integer.MIN_VALUE;
    }
    private static byte[] settle(LocalSave save,String request)throws Exception{
        save.respond("/level/startBattle",form("instanceid",Long.toString(LocalSave.STAGE),
            "idempotency",request),new byte[0],null);
        return save.respond("/level/pushMainLineProgress",form("instanceid",Long.toString(LocalSave.STAGE),
            "pass","1","stars","3"),new byte[0],null);
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: test-dir responses.json");
        File root=new File(args[0]),freshDir=new File(root,"fresh"),oldDir=new File(root,"old"),
            alternateDir=new File(root,"alternate"),legacyWinDir=new File(root,"legacy-win"),
            legacyPartialDir=new File(root,"legacy-partial"),baseWinDir=new File(root,"base-win"),
            noStarterDir=new File(root,"no-starter"),noRoleDir=new File(root,"no-role");
        require(root.isDirectory()&&freshDir.mkdir()&&oldDir.mkdir()&&alternateDir.mkdir()&&
            legacyWinDir.mkdir()&&legacyPartialDir.mkdir()&&baseWinDir.mkdir()&&
            noStarterDir.mkdir()&&noRoleDir.mkdir(),
            "Fresh test directories required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8)),catalog=responses.getJSONObject("_catalog");
        LocalSave fresh=new LocalSave(freshDir);
        require(!new JSONObject(fresh.roleSummary()).getBoolean("exists"),"New account already has a role");
        JSONObject initial=read(freshDir);
        require(initial.getInt("starterProfile")==1&&initial.getBoolean("namePending"),
            "Beginner marker or naming state missing");
        require(initial.getLong("gold")==1000&&initial.getLong("rmb")==0&&
            initial.getLong("stamina")==200&&initial.getLong("activityStamina")==0&&
            initial.getLong("exp")==0,"New account has preservation-mode resources");
        require(!initial.has("items")&&!initial.has("ownedServants"),
            "Unplayed account acquired a full inventory");
        byte[] uncreatedBytes=Files.readAllBytes(new File(freshDir,"offline_save_v1.json").toPath());
        try{
            fresh.respond("/role/rename",form("rolename","早到名字"),new byte[0],catalog);
            throw new AssertionError("Uncreated role was named");
        }catch(java.io.IOException expected){}
        require(Arrays.equals(uncreatedBytes,Files.readAllBytes(new File(freshDir,"offline_save_v1.json").toPath())),
            "Premature guide name changed an uncreated account");

        fresh.respond("/role/create",Collections.<String,String>emptyMap(),fixture(responses,"/role/create"),catalog);
        require(read(freshDir).getBoolean("namePending"),"Unnamed creation skipped guide naming");
        require(fresh.respond("/guide/get",Collections.<String,String>emptyMap(),
            new byte[0],catalog).length==0,"Fresh tutorial had completed points");
        byte[] guideUpdate=fresh.respond("/guide/update",
            form("pointtype","1|2|4","pointval","-2|1|0"),new byte[0],catalog);
        require("ok".equals(new String(ProtoWire.parse(guideUpdate).data(1),StandardCharsets.UTF_8)),
            "Original guide update was not acknowledged");
        byte[] guideBefore=fresh.respond("/guide/get",Collections.<String,String>emptyMap(),
            new byte[0],catalog);
        ProtoWire guidePoints=ProtoWire.parse(guideBefore);
        require(guidePoints.fields.size()==3&&
            ProtoWire.parse(guidePoints.fields.get(0).data).number(2,0)==-2L&&
            ProtoWire.parse(guidePoints.fields.get(1).data).number(2,0)==1L,
            "Tutorial points did not use the original GuidesProto wire shape");
        fresh.respond("/guide/update",form("pointtype","1|2","pointval","0|0"),
            new byte[0],catalog);
        require(Arrays.equals(guideBefore,fresh.respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog)),
            "A replayed guide update moved a completed point backwards");
        byte[] beforeInvalidGuide=Files.readAllBytes(new File(freshDir,"offline_save_v1.json").toPath());
        try{
            fresh.respond("/guide/update",form("pointtype","1|2","pointval","1"),
                new byte[0],catalog);
            throw new AssertionError("Mismatched guide arrays were accepted");
        }catch(java.io.IOException expected){}
        require(Arrays.equals(beforeInvalidGuide,Files.readAllBytes(
            new File(freshDir,"offline_save_v1.json").toPath())),
            "Rejected guide update changed the save");
        ProtoWire role=ProtoWire.parse(fresh.respond("/role/role",Collections.<String,String>emptyMap(),
            fixture(responses,"/role/role"),catalog));
        ProtoWire detail=ProtoWire.parse(role.data(1));
        require(detail.number(104,0)==1&&role.number(4,0)==1&&
            detail.number(105,-1)==1000&&detail.number(103,-1)==0&&
            detail.number(107,-1)==200&&detail.number(121,-1)==0,
            "Beginner role did not start at level 1 with small resources");
        fresh.respond("/backpack/item",Collections.<String,String>emptyMap(),
            fixture(responses,"/backpack/item"),catalog);
        JSONObject starter=read(freshDir);
        JSONObject items=starter.getJSONObject("items");
        require(items.length()==2&&items.getLong("40310001")==10&&items.getLong("40330099")==2,
            "Starter items differ from the small catalog-backed supply");
        require(starter.getJSONObject("equips").length()==0&&
            starter.getJSONObject("ownedServants").length()==4,
            "Starter combat party or empty equipment bag differs");
        File starterFile=new File(freshDir,"offline_save_v1.json");
        byte[] beforeRejected=Files.readAllBytes(starterFile.toPath());
        for(String blocked:new String[]{"/shop/buy","/draw/activity"}){
            try{
                fresh.respond(blocked,form("count","-1","times","10","idempotency","repeat"),
                    new byte[0],catalog);
                throw new AssertionError("Unpriced online transaction accepted: "+blocked);
            }catch(java.io.IOException expected){}
            require(Arrays.equals(beforeRejected,Files.readAllBytes(starterFile.toPath())),
                "Rejected online transaction changed the save: "+blocked);
        }
        for(String unaffordable:new String[]{"/draw/gold/ten","/draw/rmb/ten"}){
            try{
                fresh.respond(unaffordable,form("times","10","idempotency","unaffordable"),
                    new byte[0],catalog);
                throw new AssertionError("Unfunded online draw accepted: "+unaffordable);
            }catch(java.io.IOException expected){}
            require(Arrays.equals(beforeRejected,Files.readAllBytes(starterFile.toPath())),
                "Unfunded online draw changed the save: "+unaffordable);
        }
        JSONObject supplyGift=new JSONObject(starter.toString());
        supplyGift.getJSONObject("items").put("40350004",1);
        String beforeSupply=supplyGift.toString();
        try{
            LocalEconomy.respond(supplyGift,catalog,"/backpack/item/use",
                form("itemids","40350004","itemnums","1"),new byte[0]);
            throw new AssertionError("Offline unlimited supply gift was usable online");
        }catch(java.io.IOException expected){}
        require(beforeSupply.equals(supplyGift.toString()),
            "Rejected unlimited supply gift changed a beginner save");
        byte[] guideDraw=fresh.respond("/guide/draw",form("times","10","idempotency","first"),
            new byte[0],catalog);
        int guideLoots=0;
        for(ProtoWire.Field field:ProtoWire.parse(guideDraw).fields)
            if(field.number==1&&field.type==2)guideLoots++;
        require(guideLoots==2&&read(freshDir).getLong("drawCount")==1,
            "One-time guide draw granted more than one servant/weapon pair");
        byte[] afterGuideDraw=Files.readAllBytes(starterFile.toPath());
        byte[] replay=fresh.respond("/guide/draw",form("times","10","idempotency","different"),
            new byte[0],catalog);
        require(Arrays.equals(guideDraw,replay)&&Arrays.equals(afterGuideDraw,Files.readAllBytes(starterFile.toPath())),
            "Changing the guide draw key granted another reward");
        try{
            fresh.respond("/role/rename",Collections.<String,String>emptyMap(),new byte[0],catalog);
            throw new AssertionError("Guide naming accepted an empty name");
        }catch(java.io.IOException expected){}
        byte[] namingReply=fresh.respond("/role/rename",form("rolename","新手玩家"),
            new byte[0],catalog);
        ProtoWire naming=ProtoWire.parse(namingReply);
        require("ok".equals(new String(naming.data(1),StandardCharsets.UTF_8)),
            "Naming result did not report success");
        ProtoWire namingExtra=ProtoWire.parse(naming.data(2));
        ProtoWire namingAchievement=ProtoWire.parse(namingExtra.data(2));
        ProtoWire namingJob=ProtoWire.parse(namingAchievement.data(1));
        require(namingJob.number(1,0)==509005003L&&namingJob.number(2,-1)==0&&
            namingJob.number(3,0)==1&&namingJob.number(5,0)==1&&
            "008".equals(new String(namingJob.data(4),StandardCharsets.UTF_8)),
            "Naming reply did not update the original tutorial job before guide re-entry");
        require(!read(freshDir).getBoolean("namePending")&&
            "新手玩家".equals(new JSONObject(fresh.roleSummary()).getString("name")),
            "Guide name was not saved");
        ProtoWire afterNamingPoints=ProtoWire.parse(fresh.respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog));
        require(afterNamingPoints.fields.size()==4&&
            ProtoWire.parse(afterNamingPoints.fields.get(3).data).number(2,0)==-2L,
            "Named beginner did not resume past the original naming scene");
        ProtoWire retriedNaming=ProtoWire.parse(fresh.respond("/role/rename",
            form("rolename","新手玩家"),new byte[0],catalog));
        require(ProtoWire.parse(ProtoWire.parse(retriedNaming.data(2)).data(2))
            .data(1).length>0,"Renaming a previously stuck beginner omitted guide completion");
        byte[] result=settle(fresh,"starter-battle");
        require(ProtoWire.parse(result).number(5,0)==5&&read(freshDir).getLong("exp")==5,
            "Tutorial battle skipped early guide levels");
        byte[] repeat=fresh.respond("/level/pushMainLineProgress",form("instanceid",
            Long.toString(LocalSave.STAGE),"pass","1","stars","3"),new byte[0],null);
        require(Arrays.equals(result,repeat)&&read(freshDir).getLong("exp")==5,
            "Repeated settlement duplicated beginner experience");
        // The three tutorial settlements write these milestones. Seed them in
        // this focused test; TutorialBattleSelfTest exercises the real routes.
        JSONObject completedSave=read(freshDir)
            .put("tutorialWins_3150001004",1)
            .put("tutorialWins_3150001005",1)
            .put("tutorialWins_3150001006",1);
        Files.write(starterFile.toPath(),completedSave.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave afterGuide=new LocalSave(freshDir);
        byte[] fast=settle(afterGuide,"starter-fast-battle");
        require(ProtoWire.parse(fast).number(5,0)==5&&read(freshDir).getLong("exp")==10,
            "Post-guide battle XP differs between response and save");
        byte[] fastRepeat=afterGuide.respond("/level/pushMainLineProgress",form("instanceid",
            Long.toString(LocalSave.STAGE),"pass","1","stars","3"),new byte[0],null);
        require(Arrays.equals(fast,fastRepeat)&&read(freshDir).getLong("exp")==10,
            "Repeated post-guide settlement duplicated experience");
        LocalSave reloaded=new LocalSave(freshDir);
        reloaded.respond("/backpack/item",Collections.<String,String>emptyMap(),
            fixture(responses,"/backpack/item"),catalog);
        require(read(freshDir).getJSONObject("items").length()==2&&
            !read(freshDir).getBoolean("namePending"),"Beginner inventory or name was reset on login");
        byte[] beforeReloadReplay=Files.readAllBytes(starterFile.toPath());
        require(Arrays.equals(guideDraw,reloaded.respond("/guide/draw",form("times","10"),
            new byte[0],catalog))&&Arrays.equals(beforeReloadReplay,Files.readAllBytes(starterFile.toPath())),
            "Guide draw repeated after server reload");

        LocalSave alternate=new LocalSave(alternateDir);
        alternate.respond("/role/userlogin",form("userid","1","zoneid","1"),
            fixture(responses,"/role/userlogin"),catalog);
        require(new JSONObject(alternate.roleSummary()).getBoolean("exists")&&
            read(alternateDir).getBoolean("namePending")&&
            read(alternateDir).getInt("starterProfile")==1,
            "Alternative original role creation skipped the naming guide");

        // Accounts that won the former 1004 opening before naming must resume
        // at recID 3. The newly selected 1001 opening is for fresh accounts.
        JSONObject unNamed=read(alternateDir);
        JSONObject legacyWin=new JSONObject(unNamed.toString())
            .put("tutorialWins_3150001004",1);
        File legacyWinFile=new File(legacyWinDir,"offline_save_v1.json");
        Files.write(legacyWinFile.toPath(),legacyWin.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave legacyOpening=new LocalSave(legacyWinDir);
        byte[] migrated=legacyOpening.respond("/guide/get",Collections.<String,String>emptyMap(),
            new byte[0],catalog);
        require(ProtoWire.parse(migrated).fields.size()==2&&
            guideState(migrated,1)==-2&&guideState(migrated,2)==-2&&
            guideState(migrated,3)==Integer.MIN_VALUE&&
            guideState(migrated,4)==Integer.MIN_VALUE,
            "Former opening winner did not resume immediately before naming");
        JSONObject migratedSave=read(legacyWinDir);
        require(migratedSave.getBoolean("namePending")&&
            migratedSave.getInt("tutorialWins_3150001004")==1&&
            migratedSave.getJSONObject("guidePoints").length()==2,
            "Former opening migration changed the name or battle result");
        byte[] afterMigration=Files.readAllBytes(legacyWinFile.toPath());
        require(Arrays.equals(migrated,legacyOpening.respond("/guide/get",
                Collections.<String,String>emptyMap(),new byte[0],catalog))&&
            Arrays.equals(afterMigration,Files.readAllBytes(legacyWinFile.toPath())),
            "Former opening migration was not idempotent");
        legacyOpening.respond("/guide/update",form("pointtype","1|2","pointval","0|1"),
            new byte[0],catalog);
        require(Arrays.equals(afterMigration,Files.readAllBytes(legacyWinFile.toPath())),
            "A stale guide update reopened the former opening");

        JSONObject partial=new JSONObject(legacyWin.toString()).put("guidePoints",
            new JSONObject().put("1",1).put("2",0).put("3",0).put("4",1));
        Files.write(new File(legacyPartialDir,"offline_save_v1.json").toPath(),
            partial.toString().getBytes(StandardCharsets.UTF_8));
        byte[] partialPoints=new LocalSave(legacyPartialDir).respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog);
        require(guideState(partialPoints,1)==-2&&guideState(partialPoints,2)==-2&&
            guideState(partialPoints,3)==0&&guideState(partialPoints,4)==1,
            "Former opening migration overwrote in-progress naming records");

        JSONObject baseWin=new JSONObject(legacyWin.toString())
            .put("tutorialWins_3150001001",1);
        File baseWinFile=new File(baseWinDir,"offline_save_v1.json");
        Files.write(baseWinFile.toPath(),baseWin.toString().getBytes(StandardCharsets.UTF_8));
        byte[] baseBefore=Files.readAllBytes(baseWinFile.toPath());
        require(new LocalSave(baseWinDir).respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog).length==0&&
            Arrays.equals(baseBefore,Files.readAllBytes(baseWinFile.toPath())),
            "1001 winner was mistaken for a former-route-only account");

        JSONObject noStarter=new JSONObject(legacyWin.toString()).put("starterProfile",0);
        File noStarterFile=new File(noStarterDir,"offline_save_v1.json");
        Files.write(noStarterFile.toPath(),noStarter.toString().getBytes(StandardCharsets.UTF_8));
        byte[] noStarterBefore=Files.readAllBytes(noStarterFile.toPath());
        require(new LocalSave(noStarterDir).respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog).length==0&&
            Arrays.equals(noStarterBefore,Files.readAllBytes(noStarterFile.toPath())),
            "Preservation profile received a new-account migration");

        JSONObject noRole=new JSONObject(legacyWin.toString()).put("roleCreated",false);
        File noRoleFile=new File(noRoleDir,"offline_save_v1.json");
        Files.write(noRoleFile.toPath(),noRole.toString().getBytes(StandardCharsets.UTF_8));
        byte[] noRoleBefore=Files.readAllBytes(noRoleFile.toPath());
        require(new LocalSave(noRoleDir).respond("/guide/get",
            Collections.<String,String>emptyMap(),new byte[0],catalog).length==0&&
            Arrays.equals(noRoleBefore,Files.readAllBytes(noRoleFile.toPath())),
            "Uncreated role received a former-opening migration");

        JSONObject preserved=new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",12345).put("name","Preserved").put("gold",777).put("exp",0)
            .put("wins",0).put("attempts",0).put("stage",LocalSave.STAGE).put("stars",0);
        Files.write(new File(oldDir,"offline_save_v1.json").toPath(),
            preserved.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave old=new LocalSave(oldDir);
        ProtoWire oldRole=ProtoWire.parse(old.respond("/role/role",Collections.<String,String>emptyMap(),
            fixture(responses,"/role/role"),catalog));
        ProtoWire oldDetail=ProtoWire.parse(oldRole.data(1));
        require(oldDetail.number(104,0)==5&&oldDetail.number(103,0)==100000&&
            oldDetail.number(105,0)==777,"Existing save level or currencies migrated");
        old.respond("/backpack/item",Collections.<String,String>emptyMap(),
            fixture(responses,"/backpack/item"),catalog);
        require(read(oldDir).getJSONObject("items").length()>500&&
            !read(oldDir).has("starterProfile"),"Existing inventory was replaced by beginner items");
        byte[] oldResult=settle(old,"old-battle");
        require(ProtoWire.parse(oldResult).number(5,0)==5&&read(oldDir).getLong("exp")==5,
            "Existing save experience multiplier changed");
        System.out.println("NEW_ACCOUNT_PASS");
    }
}
