package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/** The public zero-cost catalog never calls payment routes or double-credits. */
public final class ShopRedesignSelfTest {
    private static int checks;
    private static void check(boolean yes,String why){checks++;if(!yes)throw new AssertionError(why);}
    private static Map<String,String> buy(long set,long shop,long good,String id){
        Map<String,String> args=new HashMap<String,String>();
        args.put("setid",Long.toString(set));args.put("shopid",Long.toString(shop));
        args.put("goodsid",Long.toString(good));args.put("count","1");
        args.put("idempotency",id);return args;
    }
    private static String result(byte[] response)throws Exception{
        return new String(ProtoWire.parse(response).data(1),StandardCharsets.UTF_8);
    }
    private static JSONObject role(long id)throws Exception{return new JSONObject().put("starterProfile",1)
        .put("roleCreated",true).put("legacyRoleId",id).put("gold",100000).put("rmb",1000).put("exp",0);}
    private static ProtoWire set(ProtoWire all,long id)throws Exception{
        for(ProtoWire.Field field:all.fields)if(field.number==1&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==id)return entry;
        }
        return null;
    }
    private static ProtoWire shelf(ProtoWire set,long id)throws Exception{
        if(set==null)return null;
        for(ProtoWire.Field field:set.fields)if(field.number==5&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==id)return entry;
        }
        return null;
    }
    private static ProtoWire good(ProtoWire shop,long id)throws Exception{
        if(shop==null)return null;
        for(ProtoWire.Field field:shop.fields)if(field.number==2&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==id)return entry;
        }
        return null;
    }
    public static void main(String[] ignored)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(
            "D:/Project/魔女兵器在线版/legacy-server/resources/offline_responses.json")),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        long now=1790380800L;
        GiftShop gifts=GiftShop.bundled();ResourceShop resources=ResourceShop.bundled();
        JSONObject player=role(99001);
        ProtoWire giftsView=ProtoWire.parse(gifts.respond(player,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response);
        for(ProtoWire.Field setField:giftsView.fields)if(setField.number==1&&setField.type==2){
            ProtoWire giftSet=ProtoWire.parse(setField.data);
            for(ProtoWire.Field shelfField:giftSet.fields)if(shelfField.number==5&&shelfField.type==2){
                ProtoWire giftShelf=ProtoWire.parse(shelfField.data);
                check(giftShelf.number(4,0)==-1,
                    "unlimited gift shelf must hide native daily counter");
            }
        }
        check(set(giftsView,44000074)==null&&set(giftsView,44000061)==null,
            "retired paid festival shelves must be hidden");
        check(good(shelf(set(giftsView,44000006),4502990002L),45030639)==null,
            "retired New-Year package must not be offered");
        check(good(shelf(set(giftsView,44000006),4502990002L),45030620)!=null &&
            good(shelf(set(giftsView,44000006),4502990002L),45030621)!=null,
            "daily and weekly uniform boxes visible");
        check(good(shelf(set(giftsView,44000022),4502990008L),45820006).number(3,-1)==0,
            "special-action card unavailable before the event");
        check("No This Goods".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000074,4502990025L,45030431,"hidden"),new byte[0],now).response)),
            "hidden festival product denied server-side");
        Map<String,String> daily=buy(44000025,4502990011L,45030285,"daily");
        GiftShop.Action first=gifts.respond(player,catalog,"/shop/buy",daily,new byte[0],now);
        check(first.changed&&"Buy Success".equals(result(first.response)),"daily free claim succeeds");
        check(player.getLong("vipExp")==276&&player.getLong("vipPoint")==276&&
            player.getLong("virtualPurchaseCents")==1200,
            "original Goods.goods_score and nominal value credited together");
        check(!gifts.respond(player,catalog,"/shop/buy",daily,new byte[0],now).changed &&
            player.getLong("vipPoint")==276&&player.getLong("virtualPurchaseCents")==1200,
            "idempotent replay never double credits CAPH or welfare value");
        check("Sold Out".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000025,4502990011L,45030285,"daily-again"),new byte[0],now).response)),
            "second daily claim denied");
        Map<String,String> uniform=buy(44000006,4502990002L,45030620,"uniform-day");
        check("Buy Success".equals(result(gifts.respond(player,catalog,"/shop/buy",
            uniform,new byte[0],now).response)),"daily uniform claimed");
        check("Sold Out".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000006,4502990002L,45030620,"uniform-day2"),new byte[0],now).response)),
            "daily uniform capped");
        check("Buy Success".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000006,4502990002L,45030620,"uniform-next"),new byte[0],now+86400).response)),
            "daily uniform refreshes next day");
        check("Buy Success".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000006,4502990002L,45030621,"uniform-week"),new byte[0],now).response)),
            "weekly uniform claimed");
        check("Sold Out".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000006,4502990002L,45030621,"uniform-next-day"),new byte[0],now+86400).response)),
            "weekly uniform does not refresh daily");
        check("Buy Success".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000006,4502990002L,45030621,"uniform-next-week"),new byte[0],now+8*86400L).response)),
            "weekly uniform refreshes next week");
        check("Sold Out".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000022,4502990008L,45820006,"special-before"),new byte[0],now).response)),
            "special card denied before event opens");
        player.put("specialActionOpen",true);
        check("Buy Success".equals(result(gifts.respond(player,catalog,"/shop/buy",
            buy(44000022,4502990008L,45820006,"special-open"),new byte[0],now).response)),
            "special card may be claimed after explicit event activation");

        JSONObject resourceRole=role(99002);
        ProtoWire resourceView=ProtoWire.parse(resources.respond(resourceRole,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response);
        check(set(resourceView,44000028)==null&&set(resourceView,44000009)!=null&&
            set(resourceView,44000247)!=null&&set(resourceView,44000007)!=null,
            "permanent Resource excludes the archived material event set");
        check(good(shelf(set(resourceView,44000009),4502500001L),45030256)==null,
            "permanent Resource excludes the timed investigation pass");
        for(ProtoWire.Field setField:resourceView.fields)if(setField.number==1&&setField.type==2){
            ProtoWire resourceSet=ProtoWire.parse(setField.data);
            for(ProtoWire.Field shelfField:resourceSet.fields)if(shelfField.number==5&&shelfField.type==2){
                ProtoWire resourceShelf=ProtoWire.parse(shelfField.data);
                check(resourceShelf.number(4,0)==-1,
                    "unlimited resource shelf must hide native daily counter");
            }
        }
        check(good(shelf(set(resourceView,44000007),4502990003L),45990010).number(2,-1)==0,
            "virtual recharge displays zero price");
        check(shelf(set(resourceView,44000247),4501010003L)!=null,
            "original sundry random shelf exists");
        Map<String,String> recharge=buy(44000007,4502990003L,45990010,"recharge-daily");
        check("Buy Success".equals(result(resources.respond(resourceRole,catalog,"/shop/buy",
            recharge,new byte[0],now).response)),"zero-cost recharge succeeds without payment route");
        check(resourceRole.getLong("rmb")==1036&&resourceRole.getLong("vipExp")==414&&
            resourceRole.getLong("vipPoint")==414&&resourceRole.getLong("virtualPurchaseCents")==1800,
            "18-yuan nominal tier grants exactly 36 gems, 414 CAPH and 1800 virtual cents");
        check(!resources.respond(resourceRole,catalog,"/shop/buy",recharge,new byte[0],now).changed &&
            resourceRole.getLong("rmb")==1036&&resourceRole.getLong("virtualPurchaseCents")==1800,
            "recharge retry is idempotent");
        check("Sold Out".equals(result(resources.respond(resourceRole,catalog,"/shop/buy",
            buy(44000007,4502990003L,45990010,"recharge-again"),new byte[0],now).response)),
            "daily recharge tier capped");
        check("Buy Success".equals(result(resources.respond(resourceRole,catalog,"/shop/buy",
            buy(44000007,4502990003L,45990010,"recharge-next-day"),new byte[0],now+86400).response)),
            "daily recharge tier resets");
        Map<String,String> refresh=new HashMap<String,String>();
        refresh.put("shopsetid","44000247");refresh.put("idempotency","sundry-refresh");
        long before=resourceRole.getLong("rmb");
        ResourceShop.Action rotated=resources.respond(resourceRole,catalog,"/shop/refresh",
            refresh,new byte[0],now);
        check(rotated.changed&&resourceRole.getLong("rmb")==before-10&&
            resourceRole.getJSONObject("resourceShopRefreshes").getJSONObject("44000247")
                .getInt("count")==1,"only sundry consumes original 10-gem refresh");
        check(!resources.respond(resourceRole,catalog,"/shop/refresh",refresh,new byte[0],now).changed &&
            resourceRole.getLong("rmb")==before-10,"sundry refresh retry is idempotent");
        check(!ResourceShop.purchase(buy(44000188,4502060001L,45130001,"unrelated")) &&
            !ResourceShop.refresh(new HashMap<String,String>()),
            "resource shop routing cannot intercept exchange sets");
        System.out.println("SHOP_REDESIGN_OK " + checks);
    }
}
