package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/** Original costume coupon/board ownership without touching a live account. */
public final class CosmeticUnlocksSelfTest {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static Map<String,String> form(String key,String value){
        Map<String,String> result=new HashMap<String,String>();result.put(key,value);return result;
    }
    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }
    private static long fashionOwn(ProtoWire response,long fashionId)throws Exception{
        for(ProtoWire.Field field:response.fields)if(field.number==3&&field.type==2){
            ProtoWire fashion=ProtoWire.parse(field.data);
            if(fashion.number(1,0)==fashionId)return fashion.number(5,0);
        }
        throw new AssertionError("Fashion missing from original role fixture: "+fashionId);
    }
    private static ProtoWire role(JSONObject save,JSONObject catalog,byte[] seed)throws Exception{
        ProtoWire response=ProtoWire.parse(seed),instance=ProtoWire.parse(response.data(1));
        // LocalSave publishes the selected board before applying ownership.
        instance.set(127,save.optLong("curBoard",1));
        CosmeticUnlocks.applyStarterRole(save,catalog,instance,response);
        check(fashionOwn(response,70000001L)==1,"Default costume must be owned");
        return instance;
    }
    private static void rejected(JSONObject save,JSONObject catalog,String path,
                                 Map<String,String> args)throws Exception{
        String before=save.toString();
        JSONObject attempted=new JSONObject(before);
        try{
            LocalEconomy.respond(attempted,catalog,path,args,new byte[0]);
            throw new AssertionError("Expected locked cosmetic request to fail: "+path);
        }catch(java.io.IOException expected){
            check(before.equals(save.toString()),"Rejected cosmetic request changed the save");
        }
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Arguments: offline_responses.json");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),
            StandardCharsets.UTF_8)),catalog=responses.getJSONObject("_catalog");
        byte[] seed=fixture(responses,"/role/role");
        JSONObject starter=new JSONObject().put("starterProfile",1).put("cosmeticProfile",1)
            .put("roleCreated",true)
            .put("items",new JSONObject().put("40350013",99));
        ProtoWire fresh=role(starter,catalog,seed);
        check(fresh.integers(5).size()==15,"Preserve all 15 original Kanban slots");
        for(int i=0;i<15;i++)check(fresh.integers(5).get(i)==(i==0?1:0),
            "New account must start with only Kanban 1: "+i);
        ProtoWire initialResponse=ProtoWire.parse(seed);
        CosmeticUnlocks.applyStarterRole(starter,catalog,
            ProtoWire.parse(initialResponse.data(1)),initialResponse);
        check(fashionOwn(initialResponse,70000002L)==0,"Second costume starts locked");
        check(CosmeticUnlocks.couponCost(70000002L)==100 &&
            CosmeticUnlocks.couponCost(70000004L)==120 &&
            CosmeticUnlocks.couponCost(70000010L)==9999,
            "Original Fashion.asset coupon costs changed");
        rejected(starter,catalog,"/fashion/compose",form("fashionid","70000002"));
        rejected(starter,catalog,"/role/board/change",form("board","2"));
        starter.getJSONObject("items").put("40350013",100);
        LocalEconomy.respond(starter,catalog,"/fashion/compose",
            form("fashionid","70000002"),new byte[0]);
        check(starter.getJSONObject("items").getLong("40350013")==0,
            "Exchange did not consume exactly 100 coupons");
        check(CosmeticUnlocks.ownsFashion(starter,70000002L),
            "Exchanged costume did not become owned");
        check(fashionOwn(ProtoWire.parse(seed),70000002L)==1,
            "Original fixture must expose owned status before patch");
        rejected(starter,catalog,"/fashion/compose",form("fashionid","70000002"));
        JSONObject unlocked=new JSONObject().put("2",true);
        starter.put("roleUnlocks",new JSONObject().put("5",unlocked));
        LocalEconomy.respond(starter,catalog,"/role/board/change",form("board","2"),new byte[0]);
        check(starter.getLong("curBoard")==2,"Earned Kanban selection was not saved");
        ProtoWire after=role(starter,catalog,seed);
        check(after.integers(5).get(1)==1 && after.number(127,1)==2,
            "Earned Kanban did not appear in role response");
        ProtoWire afterResponse=ProtoWire.parse(seed);
        CosmeticUnlocks.applyStarterRole(starter,catalog,
            ProtoWire.parse(afterResponse.data(1)),afterResponse);
        check(fashionOwn(afterResponse,70000002L)==1,
            "Exchanged fashion did not appear in role response");
        JSONObject legacy=new JSONObject().put("starterProfile",0);
        ProtoWire old=ProtoWire.parse(seed),oldRole=ProtoWire.parse(old.data(1));
        CosmeticUnlocks.applyStarterRole(legacy,catalog,oldRole,old);
        check(oldRole.integers(5).size()==15 && oldRole.integers(5).get(14)==1,
            "Existing preservation account lost Kanban ownership");
        JSONObject earlierOnline=new JSONObject().put("starterProfile",1);
        ProtoWire prior=ProtoWire.parse(seed),priorRole=ProtoWire.parse(prior.data(1));
        CosmeticUnlocks.applyStarterRole(earlierOnline,catalog,priorRole,prior);
        check(priorRole.integers(5).get(14)==1 &&
            fashionOwn(prior,70000002L)==1,
            "Existing online account lost Kanban or fashion access");
        System.out.println("COSMETIC_UNLOCKS_SELF_TEST_OK");
    }
}
