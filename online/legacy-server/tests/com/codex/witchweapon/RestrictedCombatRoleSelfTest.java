package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONObject;

/** The original restricted battle expects the same complete combat-role proto. */
public final class RestrictedCombatRoleSelfTest {
    private static void check(boolean yes,String message){
        if(!yes)throw new AssertionError(message);
    }
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static void checkGuideRole(ProtoWire role,long level,long[] servants,long[] weapons)
            throws Exception {
        check(role.number(100,0)==level,"Guide role level differs from Challenge.asset");
        int index=0;
        for(ProtoWire.Field field:role.fields)if(field.number==2&&field.type==2){
            check(index<servants.length,"Guide role contains an extra servant");
            ProtoWire servant=ProtoWire.parse(field.data);
            check(servant.number(1,0)==servants[index] &&
                    servant.number(14,0)==weapons[index] &&
                    servant.number(10,0)>0,
                "Guide servant/weapon/spell differs from Challenge.asset");
            index++;
        }
        check(index==servants.length,"Guide role omitted a configured servant");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: empty-dir responses.json");
        File directory=new File(args[0]);
        check(directory.isDirectory()&&directory.list().length==0,
            "An empty isolated save directory is required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[1]).toPath()),StandardCharsets.UTF_8));
        check(responses.getJSONObject("/challenge/combat/role/info")
            .getString("base64").isEmpty(),"Preserved challenge fixture unexpectedly changed");
        JSONObject selected=StandaloneServer.responseFixture(responses,
            "/challenge/combat/role/info");
        check(selected==responses.getJSONObject("/combat/role/info") ||
            selected.getString("base64").equals(responses.getJSONObject(
                "/combat/role/info").getString("base64")),
            "Challenge route did not select the complete combat-role seed");
        check(StandaloneServer.responseFixture(responses,"/challenge/combat/victory")
            .getString("base64").isEmpty(),"Other challenge fixtures were aliased");
        byte[] seed=Base64.decode(selected.getString("base64"),Base64.DEFAULT);
        check(seed.length>1000,"Combat-role seed is empty or truncated");

        LocalSave save=new LocalSave(directory);
        // New account inventory initialization gives the test its four
        // preserved tutorial servants before it requests battle attributes.
        save.respond("/backpack/item",form(),new byte[0],responses.getJSONObject("_catalog"));
        Map<String,String> restricted=form("rid","1","challengeid","3150001004",
            "svcardids","10010001|10010101",
            "wpids","1701000101|1701010101","fashioncardid","70000001");
        byte[] challenge=save.respond("/challenge/combat/role/info",restricted,seed,
            responses.getJSONObject("_catalog"));
        ProtoWire role=ProtoWire.parse(challenge);
        check(challenge.length>1000&&role.data(1).length>0&&role.data(102).length>0,
            "Restricted route lost common attributes or combat units");
        long[] expectedServants={10010001L,10010101L};
        long[] expectedWeapons={1701000101L,1701010101L};
        int count=0;
        for(ProtoWire.Field field:role.fields)if(field.number==2&&field.type==2){
            check(count<expectedServants.length,"Restricted party includes an extra servant");
            ProtoWire servant=ProtoWire.parse(field.data);
            check(servant.number(1,0)==expectedServants[count]
                    && servant.number(14,0)==expectedWeapons[count],
                "Original svcardids/wpids were not mapped in order");
            count++;
        }
        check(count==expectedServants.length,"Restricted party selection was ignored");

        File saveFile=new File(directory,"offline_save_v1.json");
        Map<String,String> firstShow=form("rid","1","challengeid","400",
            "svcardids","10010001|10010101","wpids","1701000101|1701010101",
            "fashioncardid","70000001");
        ProtoWire beforeStart=ProtoWire.parse(save.respond("/challenge/combat/role/info",
            firstShow,seed,responses.getJSONObject("_catalog")));
        int beforeCount=0;
        for(ProtoWire.Field field:beforeStart.fields)
            if(field.number==2&&field.type==2)beforeCount++;
        check(beforeCount==2&&beforeStart.number(100,0)!=30,
            "Challenge 400 bypassed the active first-show encounter check");
        save.respond("/level/startBattle",
            form("instanceid","3150001004","idempotency","first-show-stage"),
            new byte[0],responses.getJSONObject("_catalog"));
        byte[] savedBefore=Files.readAllBytes(saveFile.toPath());
        ProtoWire scripted=ProtoWire.parse(save.respond("/challenge/combat/role/info",
            firstShow,seed,responses.getJSONObject("_catalog")));
        check(scripted.number(100,0)==30,"Challenge 400 did not supply its level-30 role");
        count=0;
        for(ProtoWire.Field field:scripted.fields)if(field.number==2&&field.type==2){
            check(count<TutorialBattleFixtures.FIRST_SHOW_SERVANTS.length,
                "Challenge 400 added an unexpected servant");
            ProtoWire servant=ProtoWire.parse(field.data);
            check(servant.number(1,0)==TutorialBattleFixtures.FIRST_SHOW_SERVANTS[count] &&
                servant.number(14,0)==TutorialBattleFixtures.FIRST_SHOW_WEAPONS[count],
                "Challenge 400 did not use the original scripted party in order");
            count++;
        }
        check(count==4,"Challenge 400 did not include all four temporary servants");
        check(Arrays.equals(savedBefore,Files.readAllBytes(saveFile.toPath())),
            "Temporary challenge party changed the player's save");

        // The same tutorial instance without the original challenge ID keeps
        // the request-selected party and must not gain the scripted roster.
        Map<String,String> otherChallenge=form("rid","1","challengeid","401",
            "svcardids","10010001|10010101","wpids","1701000101|1701010101",
            "fashioncardid","70000001");
        ProtoWire other=ProtoWire.parse(save.respond("/challenge/combat/role/info",
            otherChallenge,seed,responses.getJSONObject("_catalog")));
        count=0;
        for(ProtoWire.Field field:other.fields)if(field.number==2&&field.type==2)count++;
        check(count==2&&other.number(100,0)!=30,
            "Unrelated restricted challenge received the first-show party");
        save.respond("/level/startBattle",
            form("instanceid","3150001005","idempotency","later-stage"),
            new byte[0],responses.getJSONObject("_catalog"));
        Map<String,String> otherStage=form("rid","1","challengeid","400",
            "svcardids","10010001|10010101","wpids","1701000101|1701010101",
            "fashioncardid","70000001");
        ProtoWire later=ProtoWire.parse(save.respond("/challenge/combat/role/info",
            otherStage,seed,responses.getJSONObject("_catalog")));
        count=0;
        for(ProtoWire.Field field:later.fields)if(field.number==2&&field.type==2)count++;
        check(count==2&&later.number(100,0)!=30,
            "Challenge 400 leaked the first-show party into another stage");

        Map<String,String> ordinary=form("rid","1","challengeid","3150001004",
            "servantcardids","10010001|10010101",
            "weaponids","1701000101|1701010101","fashioncardid","70000001");
        byte[] normal=save.respond("/combat/role/info",ordinary,seed,
            responses.getJSONObject("_catalog"));
        check(Arrays.equals(challenge,normal),
            "Existing combat-role route differs from the mapped restricted route");

        // Original 3150001001 has no challenge ID. Its scripted lesson party
        // is provided by the ordinary combat route during the active stage.
        save.respond("/level/startBattle",
            form("instanceid","3150001001","idempotency","basestation-stage"),
            new byte[0],responses.getJSONObject("_catalog"));
        byte[] beforeBasestation=Files.readAllBytes(saveFile.toPath());
        ProtoWire basestation=ProtoWire.parse(save.respond("/combat/role/info",
            ordinary,seed,responses.getJSONObject("_catalog")));
        long[] baseServants={10012701L,10011701L,10010101L,10011901L};
        long[] baseWeapons={1701270101L,1701170101L,1701010101L,1701190101L};
        checkGuideRole(basestation,30,baseServants,baseWeapons);
        ProtoWire restrictedBase=ProtoWire.parse(save.respond(
            "/challenge/combat/role/info",
            form("rid","1","challengeid","100","svcardids","10010001",
                "wpids","1701000101","fashioncardid","70000001"),
            seed,responses.getJSONObject("_catalog")));
        check(Arrays.equals(basestation.bytes(),restrictedBase.bytes()),
            "Real basestation restricted route did not use Challenge 100");
        check(Arrays.equals(beforeBasestation,Files.readAllBytes(saveFile.toPath())),
            "Basestation's temporary roster changed the persistent save");

        save.respond("/level/startBattle",
            form("instanceid","3150001005","idempotency","overbridge-party"),
            new byte[0],responses.getJSONObject("_catalog"));
        byte[] beforeOverbridge=Files.readAllBytes(saveFile.toPath());
        ProtoWire overbridge=ProtoWire.parse(save.respond(
            "/challenge/combat/role/info",
            form("rid","1","challengeid","401","svcardids","10010001",
                "wpids","1701000101","fashioncardid","70000001"),
            seed,responses.getJSONObject("_catalog")));
        checkGuideRole(overbridge,1,
            new long[]{10010601L,10010301L},
            new long[]{1701060102L,1701030101L});
        check(Arrays.equals(beforeOverbridge,Files.readAllBytes(saveFile.toPath())),
            "Overbridge's temporary roster changed the persistent save");

        save.respond("/level/startBattle",
            form("instanceid","3150001006","idempotency","roof-party"),
            new byte[0],responses.getJSONObject("_catalog"));
        byte[] beforeRoof=Files.readAllBytes(saveFile.toPath());
        ProtoWire roof=ProtoWire.parse(save.respond(
            "/challenge/combat/role/info",
            form("rid","1","challengeid","402","svcardids","10010001",
                "wpids","1701000101","fashioncardid","70000001"),
            seed,responses.getJSONObject("_catalog")));
        checkGuideRole(roof,1,
            new long[]{10010601L,10010301L,10011801L},
            new long[]{1701060102L,1701030101L,1701180101L});
        check(Arrays.equals(beforeRoof,Files.readAllBytes(saveFile.toPath())),
            "Roof's temporary roster changed the persistent save");
        System.out.println("RESTRICTED_COMBAT_ROLE_PASS");
    }
}
