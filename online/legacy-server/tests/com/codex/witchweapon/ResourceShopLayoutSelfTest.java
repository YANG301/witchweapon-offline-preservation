package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Permanent Resource contains only the seven original diamond exchanges. */
public final class ResourceShopLayoutSelfTest {
    private static void check(boolean condition,String reason) {
        if(!condition)throw new AssertionError(reason);
    }
    private static Map<String,String> buy(long set,long shop,long good) {
        Map<String,String> args=new HashMap<String,String>();
        args.put("setid",Long.toString(set));
        args.put("shopid",Long.toString(shop));
        args.put("goodsid",Long.toString(good));
        args.put("count","1");
        return args;
    }
    private static String status(byte[] response)throws Exception {
        return new String(ProtoWire.parse(response).data(1),StandardCharsets.UTF_8);
    }
    private static ProtoWire set(ProtoWire all,long id)throws Exception {
        for(ProtoWire.Field field:all.fields)if(field.number==1&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==id)return entry;
        }
        return null;
    }
    private static ProtoWire shelf(ProtoWire set,long id)throws Exception {
        if(set==null)return null;
        for(ProtoWire.Field field:set.fields)if(field.number==5&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==id)return entry;
        }
        return null;
    }
    public static void main(String[] ignored)throws Exception {
        JSONObject source=new JSONObject(new String(Files.readAllBytes(Paths.get(
            "D:/Project/魔女兵器在线版/legacy-server/resources/offline_responses.json")),
            StandardCharsets.UTF_8));
        JSONObject catalog=source.getJSONObject("_catalog");
        JSONObject player=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("legacyRoleId",918023L).put("gold",1000).put("rmb",500).put("exp",0);
        ResourceShop shop=ResourceShop.bundled();
        long now=1790380800L;
        ProtoWire all=ProtoWire.parse(shop.respond(player,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response);
        check(set(all,44000028)==null,"Retired material set is still shown");
        check(set(all,44000009)!=null&&set(all,44000247)!=null&&
            set(all,44000007)!=null,"Resource, sundry or recharge set missing");
        ProtoWire resource=shelf(set(all,44000009),4502500001L);
        check(resource!=null&&resource.number(4,0)==-1,"Resource shelf stock or ID wrong");
        Set<Long> actual=new HashSet<Long>();
        Map<Long,Long> prices=new HashMap<Long,Long>();
        for(ProtoWire.Field field:resource.fields)if(field.number==2&&field.type==2){
            ProtoWire good=ProtoWire.parse(field.data);
            long id=good.number(1,0);
            check(actual.add(id),"Duplicate diamond product");
            prices.put(id,good.number(2,-1));
        }
        Set<Long> expected=new HashSet<Long>(Arrays.asList(
            45030125L,45030124L,45130009L,45130010L,45130011L,
            45030202L,45030267L));
        check(actual.equals(expected),"Resource list differs from seven permanent products");
        long[] ids={45030125L,45030124L,45130009L,45130010L,
            45130011L,45030202L,45030267L};
        long[] amounts={26L,260L,5L,45L,420L,100L,30L};
        for(int i=0;i<ids.length;i++)
            check(prices.get(ids[i])==amounts[i],"Original diamond price changed");
        String before=player.toString();
        check("No This Goods".equals(status(shop.respond(player,catalog,"/shop/buy",
            buy(44000028,4502500004L,45030268L),new byte[0],now).response)),
            "Retired material purchase should be rejected");
        check("No This Goods".equals(status(shop.respond(player,catalog,"/shop/buy",
            buy(44000009,4502500001L,45030256L),new byte[0],now).response)),
            "Event-only investigation pass should be rejected");
        check(before.equals(player.toString()),"Rejected products mutated player account");
        ResourceShop.Action tarot=shop.respond(player,catalog,"/shop/buy",
            buy(44000009,4502500001L,45030125L),new byte[0],now);
        check(tarot.changed&&"Buy Success".equals(status(tarot.response)),
            "Original tarot exchange failed");
        check(player.getLong("rmb")==474L&&
            player.getJSONObject("items").getLong("40350003")==1L,
            "Diamond cost or tarot grant wrong");
        // An older server treated its positive protocol compatibility value
        // as finite stock. An already-maxed old ledger must not cap this item.
        JSONObject oldClaim=new JSONObject().put("bucket",0).put("refreshCount",0)
            .put("count",1000000);
        player.put("resourceShopClaims",new JSONObject()
            .put("44000009:4502500001:45030125",oldClaim));
        ResourceShop.Action again=shop.respond(player,catalog,"/shop/buy",
            buy(44000009,4502500001L,45030125L),new byte[0],now);
        check(again.changed&&"Buy Success".equals(status(again.response))&&
            player.getLong("rmb")==448L&&
            player.getJSONObject("items").getLong("40350003")==2L&&
            player.getJSONObject("resourceShopClaims")
                .getJSONObject("44000009:4502500001:45030125").getInt("count")==1000000,
            "Unlimited resource item was capped or wrote a fake stock ledger");
        JSONObject sundryPlayer=new JSONObject(player.toString());
        Map<String,String> refresh=new HashMap<String,String>();
        refresh.put("shopsetid","44000247");
        ResourceShop.Action manual=shop.respond(sundryPlayer,catalog,"/shop/refresh",
            refresh,new byte[0],now);
        check(manual.changed,"Sundry manual refresh did not work");
        ProtoWire current=set(ProtoWire.parse(shop.respond(sundryPlayer,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response),
            44000247L);
        ProtoWire next=set(ProtoWire.parse(shop.respond(sundryPlayer,catalog,
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],now+28800L).response),
            44000247L);
        check(current.number(8,0)==1&&next.number(8,-1)==0&&
            next.number(6,0)==current.number(6,0)+28800L&&
            next.number(7,0)==current.number(7,0)+28800L,
            "Sundry eight-hour refresh was not calculated on the next request");
        System.out.println("RESOURCE_SHOP_LAYOUT_OK");
    }
}

