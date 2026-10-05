package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** Local-only regression for account role identity and pre-metadata saves. */
public final class RoleSummarySelfTest {
    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    private static Map<String,String> name(String value) {
        Map<String,String> args=new HashMap<String,String>();
        args.put("name",value);
        return args;
    }
    private static long roleId(JSONObject summary) throws Exception {
        return Long.parseLong(summary.getString("roleId"));
    }
    private static Map<String,String> cosmetic(long roleId,String key,int value) {
        Map<String,String> args=new HashMap<String,String>();
        args.put("roleid",Long.toString(roleId));args.put(key,Integer.toString(value));
        return args;
    }
    public static void main(String[] args) throws Exception {
        if (args.length!=1) throw new IllegalArgumentException("Test directory required");
        File root=new File(args[0]);
        if (!root.isDirectory()) throw new IllegalArgumentException("Test directory missing");
        File aliceDir=new File(root,"alice"), bobDir=new File(root,"bob"), oldDir=new File(root,"old");
        require(aliceDir.mkdir() && bobDir.mkdir() && oldDir.mkdir(),"Fresh test directories required");
        LocalSave alice=new LocalSave(aliceDir);
        JSONObject before=new JSONObject(alice.roleSummary());
        require(!before.getBoolean("exists") && before.getString("roleId").isEmpty(),"Default save falsely created role");
        require(before.getInt("head")==0 && before.getInt("headBox")==0,
            "Uncreated role exposed cosmetics");
        byte[] loginSeed=new ProtoWire().set(1,1).set(2,new byte[0]).bytes();
        byte[] created=alice.respond("/role/create",name("Alice"),loginSeed,null);
        JSONObject aliceSummary=new JSONObject(alice.roleSummary());
        long aliceID=roleId(aliceSummary);
        require(aliceSummary.getBoolean("exists") && aliceID>0 && "Alice".equals(aliceSummary.getString("name")),
            "Created role summary missing");
        require(aliceSummary.getInt("head")==1 && aliceSummary.getInt("headBox")==1,
            "Default role cosmetics differ from preserved game seed");
        require(ProtoWire.parse(created).number(1,0)==aliceID,"Create response RoleID differs");
        LocalSave reloaded=new LocalSave(aliceDir);
        require(roleId(new JSONObject(reloaded.roleSummary()))==aliceID,"RoleID not persisted");
        Map<String,String> loginArgs=new HashMap<String,String>();
        loginArgs.put("userid","1");loginArgs.put("zoneid","1");
        loginArgs.put("roleid",Long.toString(aliceID));
        require(ProtoWire.parse(reloaded.respond("/role/userlogin",loginArgs,loginSeed,null))
            .number(1,0)==aliceID,"Second login RoleID differs");
        byte[] roleSeed=new ProtoWire().set(1,new ProtoWire()
            .set(1,new byte[]{1}).set(2,new byte[]{1}).set(101,1).bytes()).bytes();
        ProtoWire role=ProtoWire.parse(reloaded.respond("/role/role",Collections.<String,String>emptyMap(),roleSeed,null));
        require(ProtoWire.parse(role.data(1)).number(101,0)==aliceID,"ComplexRole RoleID differs");
        require(ProtoWire.parse(role.data(1)).number(118,0)==1 &&
            ProtoWire.parse(role.data(1)).number(119,0)==1,"ComplexRole cosmetic defaults differ");

        // Old saves may omit selections or hold an invalid zero placeholder.
        // Neither case may blank the avatar after a role lookup or re-login.
        File aliceFile=new File(aliceDir,"offline_save_v1.json");
        JSONObject selectedSave=new JSONObject(new String(Files.readAllBytes(aliceFile.toPath()),StandardCharsets.UTF_8));
        selectedSave.put("curHead",0);selectedSave.put("curHeadBox",0);
        Files.write(aliceFile.toPath(),selectedSave.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave zeroSelection=new LocalSave(aliceDir);
        JSONObject zeroSummary=new JSONObject(zeroSelection.roleSummary());
        require(zeroSummary.getInt("head")==1 && zeroSummary.getInt("headBox")==1,
            "Zero cosmetic placeholder was not backfilled");
        ProtoWire zeroRole=ProtoWire.parse(zeroSelection.respond("/role/role",Collections.<String,String>emptyMap(),roleSeed,null));
        require(ProtoWire.parse(zeroRole.data(1)).number(118,0)==1 &&
            ProtoWire.parse(zeroRole.data(1)).number(119,0)==1,"Zero cosmetic leaked to role response");
        selectedSave.put("curHead",42);selectedSave.put("curHeadBox",7);
        Files.write(aliceFile.toPath(),selectedSave.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave selected=new LocalSave(aliceDir);
        JSONObject selectedSummary=new JSONObject(selected.roleSummary());
        require(selectedSummary.getInt("head")==42 && selectedSummary.getInt("headBox")==7,
            "Selected cosmetics missing from authoritative summary");
        ProtoWire selectedRole=ProtoWire.parse(selected.respond("/role/role",Collections.<String,String>emptyMap(),roleSeed,null));
        require(ProtoWire.parse(selectedRole.data(1)).number(118,0)==42 &&
            ProtoWire.parse(selectedRole.data(1)).number(119,0)==7,"Selected cosmetics differ in game role response");

        // The default icon is owned, while another configured ID is locked.
        selected.changeCosmetic(false,cosmetic(aliceID,"head",1),roleSeed);
        try { selected.changeCosmetic(false,cosmetic(aliceID,"head",2),roleSeed);
            throw new AssertionError("Unowned icon accepted"); }
        catch (IOException expected) { }
        try { selected.changeCosmetic(true,cosmetic(aliceID,"headbox",20),roleSeed);
            throw new AssertionError("Unconfigured frame accepted"); }
        catch (IOException expected) { }

        LocalSave bob=new LocalSave(bobDir);
        require(!new JSONObject(bob.roleSummary()).getBoolean("exists"),"Other account inherited role");
        // Original clients may call /role/create without a name. The old host
        // accepted it, so creation must still mark the role as present.
        bob.respond("/role/create",Collections.<String,String>emptyMap(),loginSeed,null);
        JSONObject bobSummary=new JSONObject(bob.roleSummary());
        require(bobSummary.getBoolean("exists") && roleId(bobSummary)>0
            && roleId(bobSummary)!=aliceID && "本地玩家".equals(bobSummary.getString("name")),
            "No-name create or account isolation failed");

        try { selected.changeCosmetic(false,cosmetic(roleId(bobSummary),"head",1),roleSeed);
            throw new AssertionError("Another account's role ID accepted"); }
        catch (IOException expected) { }
        JSONObject unlockedSave=new JSONObject(new String(Files.readAllBytes(aliceFile.toPath()),StandardCharsets.UTF_8));
        unlockedSave.put("roleUnlocks",new JSONObject()
            .put("1",new JSONObject().put("2",true).put("3",false))
            .put("2",new JSONObject().put("2",1).put("3",0)));
        Files.write(aliceFile.toPath(),unlockedSave.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave unlocked=new LocalSave(aliceDir);
        // Original UI changes frame first and icon second.
        unlocked.changeCosmetic(true,cosmetic(aliceID,"headbox",2),roleSeed);
        unlocked.changeCosmetic(false,cosmetic(aliceID,"head",2),roleSeed);
        JSONObject changed=new JSONObject(new LocalSave(aliceDir).roleSummary());
        require(changed.getInt("head")==2 && changed.getInt("headBox")==2,
            "Unlocked cosmetic selection not durable across reload");
        ProtoWire changedRole=ProtoWire.parse(new LocalSave(aliceDir).respond(
            "/role/role",Collections.<String,String>emptyMap(),roleSeed,null));
        ProtoWire changedFields=ProtoWire.parse(changedRole.data(1));
        require(changedFields.number(118,0)==2 && changedFields.number(119,0)==2,
            "Relogin role cosmetics differ from saved selection");
        require(changedFields.integers(1).get(1)==1 && changedFields.integers(2).get(1)==1,
            "Boolean and numeric legacy unlock values differ in role response");
        try { unlocked.changeCosmetic(false,cosmetic(aliceID,"head",3),roleSeed);
            throw new AssertionError("False unlock flag accepted"); }
        catch (IOException expected) { }
        try { unlocked.changeCosmetic(true,cosmetic(aliceID,"headbox",3),roleSeed);
            throw new AssertionError("Zero unlock flag accepted"); }
        catch (IOException expected) { }
        require(new JSONObject(new LocalSave(bobDir).roleSummary()).getInt("head")==1,
            "Other account inherited selected icon");

        String preMetadata="{\"version\":1,\"name\":\"本地玩家\",\"gold\":1000000,\"exp\":0}";
        Files.write(new File(oldDir,"offline_save_v1.json").toPath(),preMetadata.getBytes(StandardCharsets.UTF_8));
        try {
            new LocalSave(oldDir).roleSummary();
            throw new AssertionError("Pre-metadata role falsely reported absent");
        } catch (IOException expected) { }
        System.out.println("ROLE_SUMMARY_PASS");
    }
}
