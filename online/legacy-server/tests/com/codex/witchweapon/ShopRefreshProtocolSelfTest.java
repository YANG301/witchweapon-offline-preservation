package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Exercise the real original ShopRefresh setid wire key and transaction. */
public final class ShopRefreshProtocolSelfTest {
    private static void check(boolean condition,String reason){
        if(!condition)throw new AssertionError(reason);
    }
    private static JSONObject player(long id)throws Exception{
        return new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",id).put("starterProfile",1).put("exp",0)
            .put("rmb",1000).put("gold",500000).put("vipExp",0)
            .put("recycleCurrency",1000);
    }
    private static Map<String,String> request(long id,String token){
        Map<String,String> args=new HashMap<String,String>();
        args.put("roleid","925100");args.put("setid",Long.toString(id));
        args.put("idempotency",token);return args;
    }
    private static ProtoWire set(byte[] data,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(data).fields)if(field.number==1&&field.type==2){
            ProtoWire set=ProtoWire.parse(field.data);
            if(set.number(1,0)==id)return set;
        }
        throw new AssertionError("Missing set "+id);
    }
    private static String goods(ProtoWire set)throws Exception{
        StringBuilder ids=new StringBuilder();int count=0;
        for(ProtoWire.Field shopField:set.fields)if(shopField.number==5&&shopField.type==2){
            ProtoWire shop=ProtoWire.parse(shopField.data);
            for(ProtoWire.Field field:shop.fields)if(field.number==2&&field.type==2){
                ProtoWire good=ProtoWire.parse(field.data);
                check(good.number(1,0)>0&&good.number(3,-1)>0,"New stock must be valid");
                ids.append(good.number(1,0)).append(':').append(good.number(3,0)).append(',');count++;
            }
        }
        check(count>0,"Refresh must include actual goods");return ids.toString();
    }
    public static void main(String[] args)throws Exception{
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");
        long now=1790380800L;
        ResourceShop shop=ResourceShop.bundled();JSONObject state=player(925100);
        Map<String,String> nativeRequest=request(44000247L,"native-first");
        check(ResourceShop.refresh(nativeRequest),"Native setid must select the sundry route");
        ProtoWire before=set(shop.respond(state,catalog,"/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response,44000247L);
        ResourceShop.Action action=shop.respond(state,catalog,"/shop/refresh",nativeRequest,new byte[0],now);
        ProtoWire receipt=ProtoWire.parse(action.response);
        check(action.changed&&receipt.number(1,0)==44000247L,"Native refresh must return one SetInfo");
        check(receipt.number(8,-1)==1&&receipt.number(4,-1)==1,"Refresh metadata must advance once");
        check(state.getLong("rmb")==990&&state.getLong("gold")==500000,"Refresh costs exactly 10 diamonds");
        check(!goods(before).equals(goods(receipt)),"Manual refresh must reroll original sundry goods");
        ResourceShop.Action retry=shop.respond(state,catalog,"/shop/refresh",nativeRequest,new byte[0],now);
        check(!retry.changed&&Arrays.equals(action.response,retry.response)&&state.getLong("rmb")==990,"Retry must not charge or reroll again");
        Map<String,String> conflict=request(44000247L,"conflict");conflict.put("shopsetid","44000047");
        String unchanged=state.toString();
        try{shop.respond(state,catalog,"/shop/refresh",conflict,new byte[0],now);throw new AssertionError("Conflicting IDs accepted");}
        catch(IOException expected){}
        check(state.toString().equals(unchanged),"Rejected IDs must preserve state");
        Map<String,String> alias=new HashMap<String,String>();alias.put("shopsetid","44000247");alias.put("idempotency","alias");
        check(ResourceShop.refresh(alias),"Legacy test alias should remain compatible");
        shop.respond(state,catalog,"/shop/refresh",alias,new byte[0],now);
        check(state.getLong("rmb")==980,"Legacy alias uses the same price and ledger");
        OriginalShop original=OriginalShop.bundled();JSONObject stars=player(925101);
        ProtoWire star=ProtoWire.parse(original.respond(stars,catalog,"/shop/refresh",request(44000047L,"star-native"),new byte[0],now).response);
        check(star.number(1,0)==44000047L&&star.number(8,0)==1&&stars.getLong("recycleCurrency")==850,"Original star refresh must accept native setid too");
        check(stars.getLong("rmb")==1000,"Star refresh must not spend diamonds");
        JSONObject poor=player(925102);poor.put("rmb",9);unchanged=poor.toString();
        try{shop.respond(poor,catalog,"/shop/refresh",request(44000247L,"poor"),new byte[0],now);throw new AssertionError("Insufficient balance accepted");}
        catch(IOException expected){}
        check(poor.toString().equals(unchanged),"Insufficient balance must preserve stock, count and wallet");
        JSONObject last=new JSONObject(state.toString());
        last.getJSONObject("resourceShopRefreshes").getJSONObject("44000247").put("count",29);
        long oldBalance=last.getLong("rmb");
        ProtoWire exhausted=ProtoWire.parse(shop.respond(last,catalog,"/shop/refresh",request(44000247L,"last"),new byte[0],now).response);
        check(exhausted.number(4,-1)==1&&exhausted.number(8,-1)==30,"Last successful refresh must preserve native completion support flag");
        check(last.getLong("rmb")==oldBalance-10,"Last refresh must cost exactly ten diamonds");
        unchanged=last.toString();
        try{shop.respond(last,catalog,"/shop/refresh",request(44000247L,"over-limit"),new byte[0],now);throw new AssertionError("Thirty-first refresh accepted");}
        catch(IOException expected){}
        check(last.toString().equals(unchanged),"Exhausted refresh must preserve stock, count and wallet");
        ProtoWire renewed=set(shop.respond(state,catalog,"/shop/allShopSet",new HashMap<String,String>(),new byte[0],now+28800L).response,44000247L);
        check(renewed.number(8,-1)==0&&renewed.number(6,0)==before.number(6,0)+28800L,"Eight-hour automatic refresh must reset manual count");
        System.out.println("SHOP_REFRESH_NATIVE_PROTOCOL_OK");
    }
}
