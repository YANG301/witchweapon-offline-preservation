package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Admin edits must share the live save lock and leave recoverable evidence. */
public final class AdminSelfTest {
    private static void require(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    private static Map<String,String> map(String... pairs){
        Map<String,String> out=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)out.put(pairs[i],pairs[i+1]);
        return out;
    }
    private static String sha(byte[] data)throws Exception{
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(data);
        StringBuilder out=new StringBuilder();
        for(byte b:digest)out.append(String.format("%02x",b&255));
        return out.toString();
    }
    private static JSONObject summary(LocalSave save)throws Exception{return new JSONObject(save.adminSummary());}
    private static void invalid(LocalSave save,Map<String,String> args)throws Exception{
        try{save.adminPatch(args);throw new AssertionError("Invalid patch was accepted");}
        catch(LocalSave.AdminValidation expected){}
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Test directory required");
        Path data=Paths.get(args[0]);
        Path a=data.resolve("users/AAAAAAAAAAAAAAAAAAAAAA");
        Path b=data.resolve("users/BBBBBBBBBBBBBBBBBBBBBB");
        LocalSave alice=new LocalSave(a.toFile()),bob=new LocalSave(b.toFile());
        try{summary(alice);throw new AssertionError("Admin view created a missing save");}
        catch(LocalSave.AdminMissing expected){}
        try{alice.adminPatch(map("expectedRevision","0","reason","test","gold","2"));
            throw new AssertionError("Admin patch created a missing save");}
        catch(LocalSave.AdminMissing expected){}
        require(!Files.exists(a),"Missing account directory was created by admin");
        Files.createDirectories(a);Files.createDirectories(b);
        alice.roleSummary();bob.roleSummary(); // Ordinary game paths create first saves.
        JSONObject first=summary(alice);
        require(first.getLong("revision")==1 && first.getLong("gold")==1000,"New save state");
        require(!first.getBoolean("roleCreated"),"Default save has role");
        invalid(alice,map("expectedRevision","1","reason","test","name","Nina"));
        require(summary(alice).getLong("revision")==1,"Rejected name edit changed revision");
        alice.respond("/role/create",map("name","Alice"),new byte[0],null);
        long previous=summary(alice).getLong("revision");
        byte[] before=Files.readAllBytes(a.resolve("offline_save_v1.json"));
        String result=alice.adminPatch(map("expectedRevision",Long.toString(previous),
            "reason","人工修正测试","name","Nina","gold","1200000"));
        JSONObject changed=new JSONObject(result);
        require(changed.getLong("revision")==previous+1 &&
            changed.getString("name").equals("Nina") && changed.getLong("gold")==1200000,
            "Admin update did not persist both fields");
        Path backups=data.resolve("admin-backups/AAAAAAAAAAAAAAAAAAAAAA");
        Path audits=data.resolve("admin-audit/AAAAAAAAAAAAAAAAAAAAAA");
        require(Files.isDirectory(backups)&&Files.isDirectory(audits),"Missing backup or audit directory");
        List<Path> snapshots=new ArrayList<Path>(),records=new ArrayList<Path>();
        try(DirectoryStream<Path> entries=Files.newDirectoryStream(backups)){for(Path p:entries)snapshots.add(p);}
        try(DirectoryStream<Path> entries=Files.newDirectoryStream(audits)){for(Path p:entries)records.add(p);}
        require(snapshots.size()==1 && records.size()==2,"Expected one snapshot and prepare/commit audit pair");
        require(Arrays.equals(before,Files.readAllBytes(snapshots.get(0))),"Snapshot is not byte-exact");
        JSONObject prepare=null,commit=null;
        for(Path p:records){
            JSONObject record=new JSONObject(new String(Files.readAllBytes(p),StandardCharsets.UTF_8));
            if(record.getString("status").equals("prepared"))prepare=record;
            else if(record.getString("status").equals("committed"))commit=record;
        }
        require(prepare!=null&&commit!=null&&prepare.getString("id").equals(commit.getString("id")),"Audit pair mismatch");
        require(prepare.getString("snapshotSha256").equals(sha(before)) &&
            prepare.getString("reason").equals("人工修正测试") &&
            prepare.getLong("oldGold")==1000 && prepare.getLong("newGold")==1200000 &&
            commit.getLong("revisionAfter")==previous+1,"Audit content mismatch");
        byte[] after=Files.readAllBytes(a.resolve("offline_save_v1.json"));
        try{alice.adminPatch(map("expectedRevision",Long.toString(previous),"reason","stale","gold","2"));
            throw new AssertionError("Stale revision accepted");}
        catch(LocalSave.AdminConflict expected){}
        invalid(alice,map("expectedRevision",Long.toString(previous+1),"reason","bad","gold","-1"));
        invalid(alice,map("expectedRevision",Long.toString(previous+1),"reason","bad","gold","1000000000001"));
        invalid(alice,map("expectedRevision",Long.toString(previous+1),"reason","bad","name","\nBad"));
        invalid(alice,map("expectedRevision",Long.toString(previous+1),"reason","bad","roleCreated","false"));
        require(Arrays.equals(after,Files.readAllBytes(a.resolve("offline_save_v1.json"))),"Rejected edit changed save");
        require(new JSONObject(alice.adminPatch(map("expectedRevision",Long.toString(previous+1),
            "reason","no change","gold","1200000"))).getLong("revision")==previous+1,
            "No-op bumped revision");
        // Use an ordinary stage: the maze's first request also commits its one-time ID migration.
        Map<String,String> battle=map("instanceid",Long.toString(LocalSave.STAGE),"idempotency","admin-test-battle");
        alice.respond("/level/startBattle",battle,new byte[0],null);
        require(summary(alice).getLong("revision")==previous+2,"Gameplay did not bump revision");
        try{alice.adminPatch(map("expectedRevision",Long.toString(previous+1),"reason","stale battle","gold","3"));
            throw new AssertionError("Concurrent gameplay revision was ignored");}
        catch(LocalSave.AdminConflict expected){}
        require(summary(new LocalSave(a.toFile())).getString("name").equals("Nina"),"Admin edit lost on reload");
        require(summary(bob).getLong("gold")==1000,"Admin edit affected another account");
        Path legacy=data.resolve("users/CCCCCCCCCCCCCCCCCCCCCC");
        Files.createDirectories(legacy);
        String oldSave="{\"version\":1,\"name\":\"Legacy\",\"roleCreated\":true,"
            +"\"legacyRoleId\":123,\"gold\":1000000,\"exp\":0}";
        Files.write(legacy.resolve("offline_save_v1.json"),oldSave.getBytes(StandardCharsets.UTF_8));
        LocalSave migrated=new LocalSave(legacy.toFile());
        require(summary(migrated).getLong("revision")==0,"Existing save without revision was not readable");
        require(new JSONObject(migrated.adminPatch(map("expectedRevision","0","reason","migration-test",
            "gold","1000001"))).getLong("revision")==1,"Old save did not acquire a revision");
        Path unsafe=data.resolve("users/DDDDDDDDDDDDDDDDDDDDDD");
        Files.createDirectories(unsafe);
        Files.write(unsafe.resolve("offline_save_v1.json"),
            "{\"version\":1,\"name\":\"Unknown\",\"gold\":1000000}"
            .getBytes(StandardCharsets.UTF_8));
        try{summary(new LocalSave(unsafe.toFile()));
            throw new AssertionError("Pre-metadata save was misreported");}
        catch(java.io.IOException expected){}
        System.out.println("ADMIN_SELF_TEST_PASS");
    }
}
