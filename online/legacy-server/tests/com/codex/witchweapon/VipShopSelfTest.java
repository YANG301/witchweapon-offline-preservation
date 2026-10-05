package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;
import java.util.Arrays;

/** Original CAPH point-only store and account-save integration. */
public final class VipShopSelfTest {
    private static void check(boolean condition,String label){
        if(!condition)throw new AssertionError(label);
    }
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static JSONObject account(long role)throws Exception{
        return new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",role).put("starterProfile",1)
            .put("name","CAPH Test").put("gold",1000).put("rmb",0)
            .put("vipPoint",6500).put("vipExp",0).put("exp",0)
            .put("stamina",60).put("activityStamina",0)
            .put("items",new JSONObject()).put("equips",new JSONObject())
            .put("ownedServants",new JSONObject());
    }
    private static byte[] buy(VipShop shop,JSONObject state,JSONObject catalog,
                              String good,String request)throws Exception{
        return shop.respond(state,catalog,"/shop/buy",
            form("setid","44000017","shopid",good.equals("45130012")?
                "4502080003":"4502080001","goodsid",good,"count","1",
            "idempotency",request),new byte[0],1700000000L).response;
    }
    private static String status(byte[] response)throws Exception{
        return new String(ProtoWire.parse(response).data(1),StandardCharsets.UTF_8);
    }
    private static long stock(byte[] result,long setId,long shopId,long goodId)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(result).fields)if(field.number==1&&field.type==2){
            ProtoWire set=ProtoWire.parse(field.data);
            if(set.number(1,0)!=setId)continue;
            for(ProtoWire.Field entry:set.fields)if(entry.number==5&&entry.type==2){
                ProtoWire shelf=ProtoWire.parse(entry.data);
                if(shelf.number(1,0)!=shopId)continue;
                check(shelf.number(4,0)==-1,
                    "CAPH shelf must hide the native shared daily counter");
                for(ProtoWire.Field item:shelf.fields)if(item.number==2&&item.type==2){
                    ProtoWire good=ProtoWire.parse(item.data);
                    if(good.number(1,0)==goodId)return good.number(3,-1);
                }
            }
        }
        throw new AssertionError("CAPH set/shop/good missing from original shop envelope");
    }
    private static boolean hasSet(byte[] bytes,long setId)throws Exception {
        for(ProtoWire.Field f:ProtoWire.parse(bytes).fields)
            if(f.number==1&&f.type==2&&ProtoWire.parse(f.data).number(1,0)==setId)return true;
        return false;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Pass responses.json and isolated directory");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[0]).toPath()),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        VipShop shop=VipShop.bundled();
        JSONObject first=account(101),second=account(202);
        if(!CaphActivityAccess.shopOpen(1700000000L)) {
            byte[] other=new ProtoWire().set(1,44000001L).set(10,19).bytes();
            byte[] seed=new ProtoWire().add(1,new ProtoWire().set(1,44000017L).bytes())
                .add(1,other).set(100,77).bytes();
            String before=first.toString();
            for(String route:new String[]{"/shop/allShopSet","/shop/getSetData"}) {
                VipShop.Action response=shop.respond(first,catalog,route,form(),seed,1700000000L);
                check(!response.changed&&!hasSet(response.response,44000017L),
                    "Closed CAPH shelf must be removed even from a cached response");
                check(hasSet(response.response,44000001L)&&
                    ProtoWire.parse(response.response).number(100,0)==77,
                    "Other shop sets and envelope metadata are preserved");
            }
            check(status(buy(shop,first,catalog,"45030183","closed-item"))
                .contains("活动尚未开启")&&before.equals(first.toString()),
                "Closed activity cannot spend points, grant loot or change claims");
            byte[] success=new ProtoWire().text(1,"Buy Success").bytes();
            first.put("vipShopReplay",new JSONObject().put("cached",new JSONObject()
                .put("response",com.codex.witchweapon.host.Base64.encodeToString(
                    success,com.codex.witchweapon.host.Base64.NO_WRAP))));
            before=first.toString();
            check(status(buy(shop,first,catalog,"45030183","cached"))
                .contains("活动尚未开启")&&before.equals(first.toString()),
                "Old successful replay cannot bypass a closed activity");
            check(second.getLong("vipPoint")==6500&&second.getJSONObject("items").length()==0,
                "Other account remains unchanged");
            File directory=new File(args[1]);
            check(directory.mkdir(),"Fresh CAPH integration directory required");
            File saveFile=new File(directory,"offline_save_v1.json");
            Files.write(saveFile.toPath(),(account(303).toString()+"\n").getBytes(StandardCharsets.UTF_8));
            LocalSave save=new LocalSave(directory);
            check(!hasSet(save.respond("/shop/allShopSet",form(),seed,catalog),44000017L),
                "Shared shop route also filters the closed shelf");
            byte[] savedBefore=Files.readAllBytes(saveFile.toPath());
            check(status(save.respond("/shop/buy",form("setid","44000017",
                "shopid","4502080001","goodsid","45030183","count","1"),seed,catalog))
                .contains("活动尚未开启"),"Shared purchase route rejects the closed activity");
            check(Arrays.equals(savedBefore,Files.readAllBytes(saveFile.toPath())),
                "Rejected purchase must not write the player save");
            System.out.println("CAPH closed shop OK; cached shelf filtered, purchase/replay rejected, save unchanged");
            return;
        }
        byte[] listed=shop.respond(first,catalog,"/shop/allShopSet",
            form(),new byte[0],1700000000L).response;
        check(stock(listed,44000017L,4502080001L,45030183L)==1,
            "Original CAPH point good and finite stock appear in SetInfo");
        byte[] item=buy(shop,first,catalog,"45030183","item-first");
        check(status(item).equals("Buy Success")&&
            first.getLong("vipPoint")==500&&
            first.getJSONObject("items").getLong("40510004")==1,
            "Original 6000-point product reaches only purchasing account");
        check(second.getLong("vipPoint")==6500&&
            !second.getJSONObject("items").has("40510004"),
            "CAPH point purchases are account isolated");
        String after=first.toString();
        check(Arrays.equals(item,buy(shop,first,catalog,"45030183","item-first"))&&
            after.equals(first.toString()),"Request replay cannot spend or grant twice");
        check(stock(shop.respond(first,catalog,"/shop/getSetData",form(),
            new byte[0],1700000000L).response,44000017L,4502080001L,45030183L)==0,
            "Finite stock updates immediately after purchase");
        check(status(buy(shop,first,catalog,"45030183","item-again"))
            .equals("Sold Out"),"Second purchase cannot bypass finite stock");
        byte[] gold=buy(shop,first,catalog,"45130012","gold-first");
        check(status(gold).equals("Buy Success")&&
            first.getLong("vipPoint")==0&&first.getLong("gold")==11000,
            "Original unlimited 500-point good grants 10000 gold");
        File directory=new File(args[1]);
        check(directory.mkdir(),"Fresh CAPH integration directory required");
        File saveFile=new File(directory,"offline_save_v1.json");
        Files.write(saveFile.toPath(),(account(303).toString()+"\n")
            .getBytes(StandardCharsets.UTF_8));
        LocalSave save=new LocalSave(directory);
        listed=save.respond("/shop/allShopSet",form(),new byte[0],catalog);
        check(stock(listed,44000017L,4502080001L,45030183L)==1,
            "Shared original shop route includes CAPH point set");
        byte[] bought=save.respond("/shop/buy",form("setid","44000017",
            "shopid","4502080001","goodsid","45030183","count","1",
            "idempotency","persisted-item"),new byte[0],catalog);
        JSONObject persisted=new JSONObject(new String(Files.readAllBytes(saveFile.toPath()),
            StandardCharsets.UTF_8));
        check(status(bought).equals("Buy Success")&&
            persisted.getLong("vipPoint")==500&&
            persisted.getJSONObject("items").getLong("40510004")==1,
            "CAPH purchase is persisted by the real LocalSave route");
        System.out.println("VIP_SHOP_OK");
    }
}
