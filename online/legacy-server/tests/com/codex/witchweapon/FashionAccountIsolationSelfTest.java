package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** A worn costume belongs to one account, including after a service restart. */
public final class FashionAccountIsolationSelfTest {
    private static void check(boolean value,String reason){
        if(!value)throw new AssertionError(reason);
    }
    private static byte[] fixture(JSONObject responses,String route)throws Exception{
        return Base64.decode(responses.getJSONObject(route).getString("base64"),Base64.DEFAULT);
    }
    private static Map<String,String> select(long id){
        Map<String,String> args=new HashMap<String,String>();
        args.put("fashioncardid",Long.toString(id));
        return args;
    }
    private static JSONObject read(Path save)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(save),StandardCharsets.UTF_8));
    }
    private static void write(Path save,JSONObject value)throws Exception{
        Files.write(save,(value.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
    }
    private static LocalSave start(Path account,JSONObject responses,JSONObject catalog)
            throws Exception{
        Files.createDirectories(account);
        LocalSave save=new LocalSave(account.toFile());
        save.respond("/servant/servants",Collections.<String,String>emptyMap(),
            fixture(responses,"/servant/servants"),catalog);
        return save;
    }
    private static long battleFashion(LocalSave account,JSONObject responses,
                                      JSONObject catalog,Map<String,String> args)
            throws Exception{
        byte[] result=account.respond("/combat/role/info",args,
            fixture(responses,"/combat/role/info"),catalog);
        return ProtoWire.parse(result).number(103,0);
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException(
            "Arguments: offline_responses.json isolated_test_root");
        JSONObject responses=read(Paths.get(args[0])),catalog=responses.getJSONObject("_catalog");
        Path root=Paths.get(args[1]).toAbsolutePath().normalize();
        if(Files.exists(root))throw new IllegalArgumentException("Test root must not exist");
        Files.createDirectories(root);
        Path aliceDir=root.resolve("users/alice"),bobDir=root.resolve("users/bob");
        start(aliceDir,responses,catalog);
        LocalSave bob=start(bobDir,responses,catalog);
        Path aliceSave=aliceDir.resolve("offline_save_v1.json");
        JSONObject unlocked=read(aliceSave);
        unlocked.put("fashionOwned",new JSONObject().put("70000002",true));
        write(aliceSave,unlocked);
        LocalSave alice=new LocalSave(aliceDir.toFile());

        // This process-wide file was formerly consulted for every account.
        Path prefs=root.resolve("users/shared_prefs/")
            .resolve("com.codex.witchweapon.local.v2.playerprefs.xml");
        Files.createDirectories(prefs.getParent());
        Files.write(prefs,("<map><int name=\"com.shuiqinling.fashion_1\" " +
            "value=\"70000013\" /></map>").getBytes(StandardCharsets.UTF_8));
        check(battleFashion(alice,responses,catalog,select(70000002L))==2,
            "Owned costume did not reach combat FashionSerial");
        check(read(aliceSave).getLong("curFashion")==70000002L,
            "Alice's selection did not persist in her account save");
        check(battleFashion(bob,responses,catalog,Collections.<String,String>emptyMap())==1,
            "Alice's selection or shared PlayerPrefs leaked to Bob");
        check(battleFashion(bob,responses,catalog,select(70000002L))==1,
            "Locked costume was accepted for Bob's combat");
        check(read(bobDir.resolve("offline_save_v1.json")).getLong("curFashion")==70000001L,
            "Locked selection was not normalized to Bob's starter costume");

        LocalSave restarted=new LocalSave(aliceDir.toFile());
        check(battleFashion(restarted,responses,catalog,
            Collections.<String,String>emptyMap())==2,
            "Costume selection was lost after reloading the account save");
        byte[] restricted=restarted.respond("/challenge/combat/role/info",
            select(70000001L),fixture(responses,"/combat/role/info"),catalog);
        check(ProtoWire.parse(restricted).number(103,0)==1 &&
            read(aliceSave).getLong("curFashion")==70000001L,
            "Restricted battle did not save the account's selected costume");
        byte[] maze=restarted.respond("/csc/role",select(70000002L),
            fixture(responses,"/combat/role/info"),catalog);
        check(ProtoWire.parse(ProtoWire.parse(maze).data(18)).number(103,0)==2 &&
            read(aliceSave).getLong("curFashion")==70000002L,
            "Maze battle did not return and persist the selected costume");
        restarted=new LocalSave(aliceDir.toFile());
        check(battleFashion(restarted,responses,catalog,
            Collections.<String,String>emptyMap())==2,
            "Selection made for the maze was lost on the next ordinary battle");

        // Before the cosmetic profile marker, all original costumes remained
        // available. Preserve those accounts and an already saved outfit.
        Path legacyDir=root.resolve("users/legacy");
        start(legacyDir,responses,catalog);
        Path legacySave=legacyDir.resolve("offline_save_v1.json");
        JSONObject old=read(legacySave);
        old.remove("cosmeticProfile");
        old.put("curFashion",70000013L);
        write(legacySave,old);
        LocalSave legacy=new LocalSave(legacyDir.toFile());
        check(battleFashion(legacy,responses,catalog,
            Collections.<String,String>emptyMap())==13,
            "Existing online account lost its equipped costume");
        check(read(legacySave).getLong("curFashion")==70000013L,
            "Existing costume was overwritten by a default or PlayerPrefs");

        Path earlierDir=root.resolve("users/earlier");
        start(earlierDir,responses,catalog);
        Path earlierSave=earlierDir.resolve("offline_save_v1.json");
        JSONObject earlierData=read(earlierSave);
        earlierData.remove("cosmeticProfile");
        write(earlierSave,earlierData);
        LocalSave earlier=new LocalSave(earlierDir.toFile());
        check(battleFashion(earlier,responses,catalog,
            Collections.<String,String>emptyMap())==1,
            "Old account without a selection should keep the original default");
        check(!read(earlierSave).has("curFashion"),
            "Read-only battle setup unexpectedly rewrote an old account");
        System.out.println("FASHION_ACCOUNT_ISOLATION_SELF_TEST_OK");
    }
}
