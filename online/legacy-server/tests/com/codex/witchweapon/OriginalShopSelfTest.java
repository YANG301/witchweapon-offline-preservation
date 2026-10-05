package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/** Real original-catalog limits, account separation and virtual-clock rotation. */
public final class OriginalShopSelfTest {
    private static int checks;
    private static void check(boolean ok,String reason){
        checks++;if(!ok)throw new AssertionError(reason);
    }
    private static Map<String,String> buy(long set,long shop,long good,long count,String request){
        Map<String,String> fields=new HashMap<String,String>();
        fields.put("setid",Long.toString(set));fields.put("shopid",Long.toString(shop));
        fields.put("goodsid",Long.toString(good));fields.put("count",Long.toString(count));
        if(request!=null)fields.put("idempotency",request);
        return fields;
    }
    private static String status(byte[] bytes)throws Exception{
        return new String(ProtoWire.parse(bytes).data(1),StandardCharsets.UTF_8);
    }
    private static JSONObject role(long id,long gems,long green)throws Exception{
        return new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",id).put("starterProfile",1)
            .put("gold",1000).put("rmb",gems).put("activeCurrencyGreen",green)
            .put("exp",0);
    }
    private static ProtoWire set(ProtoWire all,long id)throws Exception{
        for(ProtoWire.Field f:all.fields)if(f.number==1&&f.type==2){
            ProtoWire entry=ProtoWire.parse(f.data);
            if(entry.number(1,0)==id)return entry;
        }
        throw new AssertionError("set absent "+id);
    }
    private static ProtoWire shop(ProtoWire set,long id)throws Exception{
        for(ProtoWire.Field f:set.fields)if(f.number==5&&f.type==2){
            ProtoWire entry=ProtoWire.parse(f.data);
            if(entry.number(1,0)==id)return entry;
        }
        throw new AssertionError("shop absent "+id);
    }
    private static ProtoWire good(ProtoWire shop,long id)throws Exception{
        for(ProtoWire.Field f:shop.fields)if(f.number==2&&f.type==2){
            ProtoWire entry=ProtoWire.parse(f.data);
            if(entry.number(1,0)==id)return entry;
        }
        throw new AssertionError("good absent "+id);
    }
    public static void main(String[] args)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            Paths.get(args[0])),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        OriginalShop store=OriginalShop.bundled();
        long friday=1790337600L;  // 2026-09-25 12:00 UTC / 20:00 China
        long saturday=friday+86400L;
        JSONObject a=role(11,100,20),b=role(12,100,20);
        ProtoWire before=ProtoWire.parse(store.respond(a,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],friday).response);
        int setCount=0;for(ProtoWire.Field f:before.fields)if(f.number==1)setCount++;
        check(setCount==23,"twenty-three original and shared sets");
        check(shop(set(before,44000016L),4501070001L).number(3,0)==1,
            "shared group-zero guild exchange shelf visible");
        check(shop(set(before,44000002L),4501020001L).number(3,0)==1,
            "shared group-zero maze exchange shelf visible");
        check(set(before,44000014L).number(9,0)==1,
            "shared group-zero second 7# shelf open every day");
        JSONObject shared=role(13,100,20).put("gold",100000);
        ProtoWire sharedView=ProtoWire.parse(store.respond(shared,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],friday).response);
        ProtoWire sharedShelf=shop(set(sharedView,44000014L),4501010013L);
        long sharedGood=0,sharedPrice=0;
        for(ProtoWire.Field field:sharedShelf.fields)if(field.number==2&&field.type==2){
            ProtoWire offered=ProtoWire.parse(field.data);
            sharedGood=offered.number(1,0);sharedPrice=offered.number(2,0);break;
        }
        check(sharedGood>0,"shared 7# rotates two original goods");
        byte[] sharedBuy=store.respond(shared,catalog,"/shop/buy",
            buy(44000014L,4501010013L,sharedGood,1,"shared-7shop"),
            new byte[0],friday).response;
        long sharedItem="Buy Success".equals(status(sharedBuy))?
            ProtoWire.parse(ProtoWire.parse(sharedBuy).data(5)).number(2,0):0;
        check("Buy Success".equals(status(sharedBuy)) &&
            shared.getLong("gold")==100000-sharedPrice &&
            sharedItem>0&&shared.getJSONObject("equips").getLong(Long.toString(sharedItem))==1,
            "shared second 7# shelf debits original gold price and grants equipment");
        check(set(before,44000070L).number(9,0)==1,"7# shop open every day");
        check(set(before,44000069L).number(9,1)==0,"airship shut on Friday");
        check(set(before,44000012L).number(9,1)==0,"airship material shelf shut");
        check(shop(set(before,44000070L),4501500009L).number(4,0)==-1,
            "7# page must not flash the reused daily-counter widget");
        check(good(shop(set(before,44000070L),4501500009L),45030168L)
            .number(2,0)==10,"original 7# price");
        check(good(shop(set(before,44000188L),4502060001L),45130001L)
            .number(2,0)==1,"original green-currency price");
        check(shop(set(before,44000188L),4501060008L).number(3,0)==0,
            "level-one powder shows its own level band only");
        ProtoWire highTier=shop(set(before,44000188L),4501060008L);
        long highTierGood=0;
        for(ProtoWire.Field f:highTier.fields)if(f.number==2&&f.type==2){
            highTierGood=ProtoWire.parse(f.data).number(1,0);break;
        }
        check(highTierGood>0 && good(highTier,highTierGood).number(2,0)==4,
            "high-tier shelf uses original four-green-powder price");
        check(shop(set(before,44000012L),4501010028L).number(3,1)==0,
            "level-92 airship shelf stays closed only by weekday schedule");
        ProtoWire random=shop(set(before,44000012L),4501010021L);
        check(random.number(3,1)==0,"closed weekend random shelf");
        int slots=0;for(ProtoWire.Field f:random.fields)if(f.number==2)slots++;
        check(slots==3,"original random-num shelf");
        byte[] stable=store.respond(a,catalog,"/shop/getSetData",
            new HashMap<String,String>(),new byte[0],friday).response;
        check(java.util.Arrays.equals(before.bytes(),stable),"stable shelf across requests");

        byte[] green=store.respond(a,catalog,"/shop/buy",
            buy(44000188L,4502060001L,45130001L,1,"green-1"),
            new byte[0],friday).response;
        check("Buy Success".equals(status(green)),"powder shop success");
        check(a.getLong("activeCurrencyGreen")==19,"green currency debited");
        check(a.getLong("gold")==2500,"original gold reward credited");
        check(ProtoWire.parse(green).data(5).length>0,"native loot return");
        byte[] tieredResponse=store.respond(a,catalog,"/shop/buy",
            buy(44000188L,4501060008L,highTierGood,1,"level-open-92"),
            new byte[0],friday).response;
        String tieredPurchase=status(tieredResponse);
        check("No This Goods".equals(tieredPurchase),
            "level-one role cannot buy a hidden level-92 shelf: "+tieredPurchase);
        check(a.getLong("activeCurrencyGreen")==19,
            "hidden-tier purchase does not debit currency");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000188L,4502060001L,45130001L,1,"green-1"),
            new byte[0],friday).response)),"same request replay");
        check(a.getLong("activeCurrencyGreen")==19,"replay does not debit");

        Map<String,String> daily=buy(44000070L,4501500009L,45030168L,1,"daily-1");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            daily,new byte[0],friday).response)),"7# purchase");
        check(a.getLong("rmb")==90,"7# original diamond price charged");
        check(a.getJSONObject("items").getLong("40130022")==1,"7# item delivered");
        check(good(shop(set(ProtoWire.parse(store.respond(a,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],friday).response),
            44000070L),4501500009L),45030168L).number(3,0)==2,
            "7# stock immediately decremented");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            daily,new byte[0],friday).response)),"7# retry returns original response");
        check(a.getLong("rmb")==90,"7# retry safe");
        check(b.getLong("rmb")==100 && !b.has("originalShopClaims"),"account isolation");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000070L,4501500009L,45030168L,2,"daily-2"),
            new byte[0],friday).response)),"remaining 7# stock");
        check(a.getLong("rmb")==70 && a.getJSONObject("items").getLong("40130022")==3,
            "second claim charges and delivers exact quantity");
        check("Sold Out".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000070L,4501500009L,45030168L,1,"daily-3"),
            new byte[0],friday).response)),"7# sold out returns original status");
        check(a.getLong("rmb")==70,"sold-out claim never charges");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000070L,4501500009L,45030168L,1,"next-day"),
            new byte[0],saturday).response)),"daily 7# stock resets");
        check(a.getLong("rmb")==60 && a.getJSONObject("items").getLong("40130022")==4,
            "daily reset still debits and grants once");
        check("Buy Success".equals(status(store.respond(b,catalog,"/shop/buy",
            buy(44000070L,4501500009L,45030168L,1,"account-b"),
            new byte[0],friday).response)),"second account has independent stock");
        check(b.getLong("rmb")==90,"second account charged independently");

        check("No This Goods".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000069L,4501500010L,45030158L,1,null),
            new byte[0],friday).response)),"weekday airship denied");
        ProtoWire weekend=ProtoWire.parse(store.respond(a,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],saturday).response);
        check(set(weekend,44000069L).number(9,0)==1,"weekend airship open");
        check(set(weekend,44000012L).number(9,0)==1,"weekend material shelf open");
        check("Buy Success".equals(status(store.respond(a,catalog,"/shop/buy",
            buy(44000069L,4501500010L,45030158L,1,"weekend-1"),
            new byte[0],saturday).response)),"airship purchase");
        check(a.getLong("rmb")==53,"airship diamond cost");
        check(a.getJSONObject("items").getLong("40130002")==1,"airship item delivered");

        try{
            store.respond(a,catalog,"/shop/buy",
                buy(44000070L,4501500009L,45030168L,1,"weekend-1"),
                new byte[0],saturday);
            throw new AssertionError("conflicting idempotency accepted");
        }catch(java.io.IOException expected){checks++;}
        check(a.getLong("rmb")==53,"conflicting retry left save intact");
        check(!OriginalShop.purchase(buy(44000025L,1,1,1,null)),
            "gift set remains in original gift handler");
        System.out.println("OriginalShopSelfTest: "+checks+" checks passed");
    }
}
