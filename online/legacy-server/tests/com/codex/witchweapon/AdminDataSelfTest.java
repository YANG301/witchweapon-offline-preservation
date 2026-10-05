package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

/** Disposable saves only: broad edits, immutable evidence and selective online recovery. */
public final class AdminDataSelfTest {
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static Map<String,String> map(String... pairs){Map<String,String> out=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)out.put(pairs[i],pairs[i+1]);return out;}
    private static JSONObject json(String value)throws Exception{return new JSONObject(value);}
    private static JSONObject disk(Path account)throws Exception{
        return AdminJournal.parseSave(Files.readAllBytes(account.resolve("offline_save_v1.json")));}
    private static String revision(LocalSave save,JSONObject catalog,StageCatalog stages)throws Exception{
        return json(save.adminSave(catalog,stages)).getString("revision");}
    private static long count(Path root)throws Exception{
        if(!Files.exists(root))return 0;try(java.util.stream.Stream<Path> entries=Files.walk(root)){return entries.filter(Files::isRegularFile).count();}}
    private static void invalid(LocalSave save,JSONObject catalog,StageCatalog stages,String revision,String changes)throws Exception{
        try{save.adminDataPatch(map("expectedRevision",revision,"reason","边界校验","changes",changes),catalog,stages,false);
            throw new AssertionError("Invalid edit was accepted: "+changes);}
        catch(LocalSave.AdminValidation expected){}
    }
    private static FieldView field(JSONObject view,String key)throws Exception{
        JSONArray fields=view.getJSONArray("fields");
        for(int i=0;i<fields.length();i++){JSONObject candidate=fields.getJSONObject(i);
            if(candidate.getString("key").equals(key))return new FieldView(candidate);}
        throw new AssertionError("Field not present: "+key);
    }
    private static final class FieldView {final JSONObject data;FieldView(JSONObject data){this.data=data;}}
    private static void legacyFirstClaim(Path data,JSONObject seed,JSONObject catalog,StageCatalog stages,boolean stageObject)throws Exception{
        String id=stageObject?"DDDDDDDDDDDDDDDDDDDDDD":"EEEEEEEEEEEEEEEEEEEEEE";
        Path account=data.resolve("users").resolve(id);Files.createDirectories(account);
        JSONObject legacy=new JSONObject(seed.toString());
        if(stageObject)legacy.getJSONObject("mainlineStages").getJSONObject(Long.toString(LocalSave.STAGE)).remove("firstRewardClaimed");
        else legacy.remove("mainlineStages");
        Files.write(account.resolve("offline_save_v1.json"),(legacy.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        JSONObject changes=new JSONObject().put("mainline."+LocalSave.STAGE+".wins","0")
            .put("mainline."+LocalSave.STAGE+".attempts","0").put("mainline."+LocalSave.STAGE+".stars","0");
        new LocalSave(account.toFile()).adminDataPatch(map("expectedRevision","5","reason","旧存档首通回滚测试","changes",changes.toString()),catalog,stages,false);
        require(disk(account).getJSONObject("mainlineStages").getJSONObject(Long.toString(LocalSave.STAGE)).getBoolean("firstRewardClaimed"),
            "Rollback re-opened a legacy first-clear reward");
    }
    private static void broadRecovery(Path data,JSONObject seed,JSONObject catalog,StageCatalog stages)throws Exception{
        Path account=data.resolve("users/FFFFFFFFFFFFFFFFFFFFFF");Files.createDirectories(account);
        JSONObject before=new JSONObject(seed.toString());before.put("saveRevision",20);
        for(String kind:new String[]{"items","equips"}){
            JSONObject bag=new JSONObject(),definitions=catalog.getJSONObject(kind);
            for(Iterator<String> it=definitions.keys();it.hasNext();){String id=it.next();
                long cap=kind.equals("items")?LocalEconomy.stackCap(catalog,id):9999;
                if("40330006".equals(id))cap=Math.max(0,cap-500);bag.put(id,cap>0?1:0);}
            before.put(kind,bag);
        }
        JSONObject owned=new JSONObject(),templates=catalog.getJSONObject("servants");
        for(Iterator<String> it=templates.keys();it.hasNext();){String id=it.next();ProtoWire servant=LocalEconomy.decode(templates.getString(id));
            servant.set(2,10).set(3,0).set(4,1).set(5,1).set(7,0).set(12,5).set(16,0).set(9,1).set(10,0);
            servant.clear(8);for(int i=0;i<5;i++)servant.add(8,1);owned.put(id,LocalEconomy.encode(servant));}
        before.put("ownedServants",owned);
        JSONObject progress=new JSONObject();
        for(long chapter=3010001;chapter<=3010016;chapter++)for(long id:stages.stagesForChapter(chapter))
            progress.put(Long.toString(id),new JSONObject().put("wins",1).put("attempts",1).put("stars",1).put("firstRewardClaimed",true));
        before.put("mainlineStages",progress).put("wins",1).put("attempts",1).put("stars",1)
            .put("mazeWins",1).put("mazeAttempts",1).put("mazeStars",1);
        Files.write(account.resolve("offline_save_v1.json"),(before.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave baseline=new LocalSave(account.toFile());
        String backup=json(baseline.adminBackupCreate(map("expectedRevision","20","reason","完整恢复容量测试"))).getJSONObject("backup").getString("id");
        JSONObject after=new JSONObject(before.toString());
        JSONArray schema=json(baseline.adminSave(catalog,stages)).getJSONArray("fields");
        for(int i=0;i<schema.length();i++){JSONObject field=schema.getJSONObject(i);String key=field.getString("key");
            if(key.startsWith("servants.") || key.startsWith("mainline.") || field.getString("type").equals("map"))continue;
            if(key.equals("name"))after.put(key,"容量测试修改");else after.put(key,Long.parseLong(field.getString("value"))+1);}
        for(String kind:new String[]{"items","equips"}){JSONObject bag=after.getJSONObject(kind);
            for(Iterator<String> it=bag.keys();it.hasNext();)bag.put(it.next(),0);}
        JSONObject servants=after.getJSONObject("ownedServants");
        for(Iterator<String> it=servants.keys();it.hasNext();){String id=it.next();ProtoWire servant=LocalEconomy.decode(servants.getString(id));
            servant.set(2,11).set(3,1).set(4,2).set(5,2).set(7,1).set(12,6).set(16,1).set(9,2).set(10,1);
            servant.clear(8);for(int i=0;i<5;i++)servant.add(8,2);servants.put(id,LocalEconomy.encode(servant));}
        JSONObject stagesAfter=after.getJSONObject("mainlineStages");
        for(Iterator<String> it=stagesAfter.keys();it.hasNext();)stagesAfter.getJSONObject(it.next()).put("wins",2).put("attempts",2).put("stars",2);
        after.put("wins",2).put("attempts",2).put("stars",2).put("saveRevision",21);
        Files.write(account.resolve("offline_save_v1.json"),(after.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave current=new LocalSave(account.toFile());
        Map<String,String> restore=map("expectedRevision","21","reason","恢复超过两千字段","backupId",backup);
        int changes=json(current.adminBackupRestore(restore,catalog,stages,true)).getInt("changeCount");
        require(changes>2000 && changes<=4096,"The complete recovery boundary was not exercised: "+changes);
        JSONObject result=json(current.adminBackupRestore(restore,catalog,stages,false));
        require(result.getString("revision").equals("22") && result.getJSONArray("restoredFields").length()==changes,
            "A complete legitimate account cannot be recovered");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Disposable test directory and response catalog are required");
        Path data=Paths.get(args[0]).toAbsolutePath().normalize();
        if(Files.exists(data))throw new IllegalArgumentException("Test directory must not already exist");
        if(!data.toString().contains("witch-admin-data-check"))throw new IllegalArgumentException("Use the dedicated disposable test location");
        JSONObject catalog=AdminJournal.parseSave(Files.readAllBytes(Paths.get(args[1]))).getJSONObject("_catalog");
        StageCatalog stages=StageCatalog.bundled();
        String accountId="AAAAAAAAAAAAAAAAAAAAAA",otherId="BBBBBBBBBBBBBBBBBBBBBB";
        Path account=data.resolve("users").resolve(accountId),other=data.resolve("users").resolve(otherId);
        LocalSave missing=new LocalSave(data.resolve("users/CCCCCCCCCCCCCCCCCCCCCC").toFile());
        try{missing.adminSave(catalog,stages);throw new AssertionError("View created a missing save");}
        catch(LocalSave.AdminMissing expected){}
        require(!Files.exists(data),"Missing account view created directories");
        Files.createDirectories(account);Files.createDirectories(other);
        String equipId=catalog.getJSONObject("equips").keys().next();
        ProtoWire servant=LocalEconomy.decode(catalog.getJSONObject("servants").getString("10010001"));
        servant.set(2,10).set(3,0).set(4,1).set(5,1).set(7,0).set(12,5).set(16,0).set(9,1).set(10,0);
        servant.clear(8);for(int i=0;i<5;i++)servant.add(8,1);
        JSONObject seed=new JSONObject().put("version",1).put("saveRevision",5).put("name","管理测试")
            .put("roleCreated",true).put("legacyRoleId",9007199254741999L).put("starterProfile",1)
            .put("gold",1000).put("rmb",100).put("exp",0).put("stamina",200).put("activityStamina",0)
            .put("wins",2).put("attempts",3).put("stars",3).put("stage",LocalSave.STAGE).put("guildCurrency",200)
            .put("inventoryRevision",9).put("collectionRevision",7).put("active",false)
            .put("items",new JSONObject().put("40310001",10).put("40330099",2))
            .put("equips",new JSONObject().put(equipId,1))
            .put("ownedServants",new JSONObject().put("10010001",LocalEconomy.encode(servant)))
            .put("mainlineStages",new JSONObject().put(Long.toString(LocalSave.STAGE),new JSONObject()
                .put("wins",2).put("attempts",3).put("stars",3).put("firstRewardClaimed",true)))
            .put("guildCredits",new JSONObject().put("transaction",new JSONObject().put("gold",3)))
            .put("mailSendRequests",new JSONObject().put("request","retained"))
            .put("drawRequests",new JSONObject().put("request","retained"))
            .put("favorClaims",new JSONObject().put("1",true));
        byte[] original=(seed.toString(2)+"\n").getBytes(StandardCharsets.UTF_8);
        Files.write(account.resolve("offline_save_v1.json"),original);
        Files.write(other.resolve("offline_save_v1.json"),original);
        LocalSave save=new LocalSave(account.toFile());
        JSONObject view=json(save.adminSave(catalog,stages));
        require(view.getString("revision").equals("5"),"Revision must be a string");
        require(view.getJSONObject("readOnly").getString("legacyRoleId").equals("9007199254741999"),"Long role ID lost precision");
        require(field(view,"items").data.getString("type").equals("map"),"Missing map editor");
        require(field(view,"items").data.getJSONArray("catalog").length()>0,"Resource catalog is absent");
        long beforeFiles=count(data);
        JSONObject changes=new JSONObject().put("name","管理修改").put("gold","123456789012").put("rmb","9000")
            .put("stamina","30").put("items",new JSONObject().put("40310001","15"))
            .put("equips",new JSONObject().put(equipId,"12"))
            .put("servants.10010001.level","11").put("servants.10010001.skill1","2")
            .put("mainline."+LocalSave.STAGE+".wins","3").put("mainline."+LocalSave.STAGE+".attempts","4");
        Map<String,String> edit=map("expectedRevision","5","reason","管理修改测试","changes",changes.toString());
        JSONObject preview=json(save.adminDataPatch(edit,catalog,stages,true));
        require(preview.getInt("changeCount")==10,"Preview differences are incomplete");
        require(Arrays.equals(original,Files.readAllBytes(account.resolve("offline_save_v1.json"))) && count(data)==beforeFiles,
            "Preview changed a save or created evidence");
        JSONObject manual=json(save.adminBackupCreate(map("expectedRevision","5","reason","手动备份测试")));
        String manualId=manual.getJSONObject("backup").getString("id");
        require(revision(save,catalog,stages).equals("5"),"Manual backup incremented save revision");
        require(Arrays.equals(original,Files.readAllBytes(data.resolve("admin-backups").resolve(accountId).resolve(manualId+".json"))),
            "Manual snapshot is not byte exact");
        JSONObject patch=json(save.adminDataPatch(edit,catalog,stages,false));
        require(patch.getString("revision").equals("6") && patch.getInt("changeCount")==10,"Patch response is incorrect");
        String automaticId=patch.getString("backupId");
        JSONObject saved=disk(account);
        require(saved.getLong("gold")==123456789012L && saved.getLong("rmb")==9000 && saved.getLong("stamina")==30,"Scalars did not persist");
        require(saved.getLong("staminaRegenAt")>0 && saved.getInt("staminaRegenCap")==60,"Stamina recovery was not reconciled");
        require(saved.getLong("inventoryRevision")==10 && saved.getLong("collectionRevision")==8,"Client sync revisions did not increase");
        require(saved.getJSONObject("equips").getLong(equipId)==12 && saved.getJSONObject("items").getLong("40310001")==15,"Resource maps did not persist");
        require(LocalEconomy.decode(saved.getJSONObject("ownedServants").getString("10010001")).number(2,0)==11,"Servant changes did not persist");
        require(json(save.adminBackups()).getJSONArray("items").length()==2,"Backup list is incomplete");
        require(Arrays.equals(original,save.adminBackupRead(map("backupId",automaticId))),"Backup export is not byte-exact");
        try{new LocalSave(other.toFile()).adminBackupRead(map("backupId",automaticId));throw new AssertionError("Cross-account snapshot disclosure");}
        catch(LocalSave.AdminMissing expected){}
        require(Arrays.equals(original,Files.readAllBytes(other.resolve("offline_save_v1.json"))),"Edit changed a different account");
        byte[] after=Files.readAllBytes(account.resolve("offline_save_v1.json"));long filesAfter=count(data);
        invalid(save,catalog,stages,"6","{\"roleCreated\":\"false\"}");
        invalid(save,catalog,stages,"6","{\"gold\":\"-1\"}");
        invalid(save,catalog,stages,"6","{\"gold\":1}");
        invalid(save,catalog,stages,"6","{\"gold\":\"1\",\"gold\":\"2\"}");
        invalid(save,catalog,stages,"6","{\"items\":{\"999999999\":\"1\"}}");
        invalid(save,catalog,stages,"6","{\"servants.10010001.level\":\"1\"}");
        invalid(save,catalog,stages,"6","{\"servants.10010001.rank\":\"10\"}");
        invalid(save,catalog,stages,"6","{\"servants.10010001.exp\":\"999999\"}");
        invalid(save,catalog,stages,"6","{\"mainline."+LocalSave.STAGE+".wins\":\"50\"}");
        require(Arrays.equals(after,Files.readAllBytes(account.resolve("offline_save_v1.json"))) && count(data)==filesAfter,
            "Rejected edits changed files or produced snapshots");
        try{save.adminDataPatch(edit,catalog,stages,false);throw new AssertionError("Stale revision accepted");}
        catch(LocalSave.AdminConflict expected){}
        JSONObject noChange=json(save.adminDataPatch(map("expectedRevision","6","reason","不变测试","changes","{\"gold\":\"123456789012\"}"),catalog,stages,false));
        require(noChange.getString("revision").equals("6") && noChange.getString("backupId").isEmpty() && count(data)==filesAfter,
            "No-op created a snapshot or bumped revision");
        Map<String,String> restore=map("expectedRevision","6","reason","恢复测试","backupId",manualId);
        JSONObject recoveryPreview=json(save.adminBackupRestore(restore,catalog,stages,true));
        require(recoveryPreview.getInt("changeCount")==10 && recoveryPreview.getJSONArray("retainedFields").length()>0,"Restore preview did not report its scope");
        require(Arrays.equals(after,Files.readAllBytes(account.resolve("offline_save_v1.json"))) && count(data)==filesAfter,"Restore preview wrote files");
        JSONObject restored=json(save.adminBackupRestore(restore,catalog,stages,false));
        require(restored.getString("revision").equals("7") && restored.getString("restoredFrom").equals(manualId),"Restore response is incorrect");
        require(Arrays.equals(after,Files.readAllBytes(data.resolve("admin-backups").resolve(accountId).resolve(restored.getString("backupId")+".json"))),
            "Restore did not preserve the exact pre-restore save");
        JSONObject recovered=disk(account);
        require(recovered.getLong("gold")==1000 && recovered.getLong("inventoryRevision")==11 && recovered.getLong("collectionRevision")==9,
            "Selective recovery failed or rolled back sync revisions");
        for(String key:new String[]{"legacyRoleId","guildCredits","mailSendRequests","drawRequests","favorClaims"})
            require(AdminJournal.sameJson(saved.get(key),recovered.get(key)),"Recovery changed retained field: "+key);
        require(recovered.getJSONObject("mainlineStages").getJSONObject(Long.toString(LocalSave.STAGE)).getBoolean("firstRewardClaimed"),"First-clear claim was rolled back");
        legacyFirstClaim(data,seed,catalog,stages,false);legacyFirstClaim(data,seed,catalog,stages,true);
        broadRecovery(data,seed,catalog,stages);
        Path concurrentAccount=data.resolve("users/GGGGGGGGGGGGGGGGGGGGGG");Files.createDirectories(concurrentAccount);
        Files.write(concurrentAccount.resolve("offline_save_v1.json"),original);
        LocalSave concurrent=new LocalSave(concurrentAccount.toFile());
        concurrent.adminDataPatch(edit,catalog,stages,true);
        concurrent.respond("/role/create",map("name","管理测试"),new byte[0],catalog);
        try{concurrent.adminDataPatch(edit,catalog,stages,false);throw new AssertionError("Gameplay between preview and apply was overwritten");}
        catch(LocalSave.AdminConflict expected){}
        require(!Files.exists(data.resolve("admin-backups/GGGGGGGGGGGGGGGGGGGGGG")),"A gameplay conflict created an admin snapshot");
        // An in-flight game save cannot be edited or restored, but can be backed up.
        recovered.put("active",true).put("saveRevision",8);
        Files.write(account.resolve("offline_save_v1.json"),(recovered.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave active=new LocalSave(account.toFile());
        try{active.adminDataPatch(map("expectedRevision","8","reason","战斗测试","changes","{\"gold\":\"2\"}"),catalog,stages,false);
            throw new AssertionError("Active battle edit accepted");}catch(AdminDataService.ActiveBattle expected){}
        try{active.adminBackupRestore(map("expectedRevision","8","reason","战斗恢复","backupId",manualId),catalog,stages,false);
            throw new AssertionError("Active battle restore accepted");}catch(AdminDataService.ActiveBattle expected){}
        active.adminBackupCreate(map("expectedRevision","8","reason","战斗状态备份"));
        recovered.put("active",false).put("mazeRound",1).put("mazePreparedRound",1).put("mazeRoundSettled",false);
        Files.write(account.resolve("offline_save_v1.json"),(recovered.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        LocalSave maze=new LocalSave(account.toFile());
        require(json(maze.adminSave(catalog,stages)).getBoolean("active"),"Prepared CSC battle was not shown as active");
        try{maze.adminDataPatch(map("expectedRevision","8","reason","迷宫战斗测试","changes","{\"gold\":\"2\"}"),catalog,stages,false);
            throw new AssertionError("Prepared CSC battle edit accepted");}catch(AdminDataService.ActiveBattle expected){}
        try{maze.adminBackupRestore(map("expectedRevision","8","reason","迷宫恢复测试","backupId",manualId),catalog,stages,false);
            throw new AssertionError("Prepared CSC battle restore accepted");}catch(AdminDataService.ActiveBattle expected){}
        // Corrupted evidence must never be offered for restoration.
        Path snapshot=data.resolve("admin-backups").resolve(accountId).resolve(manualId+".json");
        Files.write(snapshot,"{}".getBytes(StandardCharsets.UTF_8));
        try{active.adminBackupRead(map("backupId",manualId));throw new AssertionError("Corrupted snapshot was exported");}
        catch(IOException expected){}
        System.out.println("ADMIN_DATA_SELF_TEST_PASS");
    }
}
