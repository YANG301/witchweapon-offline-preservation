package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import org.json.JSONObject;

/** The current preservation rules for exchange shelves. */
public final class ExchangePolicySelfTest {
    private static int checks;
    private static void check(boolean ok,String message){
        checks++;if(!ok)throw new AssertionError(message);
    }
    private static ProtoWire set(ProtoWire all,long id)throws Exception{
        for(ProtoWire.Field field:all.fields)if(field.number==1){
            ProtoWire value=ProtoWire.parse(field.data);
            if(value.number(1,0)==id)return value;
        }
        throw new AssertionError("Exchange set absent: "+id);
    }
    private static ProtoWire firstShop(ProtoWire set)throws Exception{
        for(ProtoWire.Field field:set.fields)if(field.number==5)
            return ProtoWire.parse(field.data);
        throw new AssertionError("Shop absent");
    }
    private static ProtoWire firstGood(ProtoWire shop)throws Exception{
        for(ProtoWire.Field field:shop.fields)if(field.number==2)
            return ProtoWire.parse(field.data);
        throw new AssertionError("Good absent");
    }
    private static int goodCount(ProtoWire shop){
        int count=0;for(ProtoWire.Field field:shop.fields)if(field.number==2)count++;
        return count;
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Pass responses.json");
        JSONObject fixture=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),
            StandardCharsets.UTF_8));
        JSONObject state=new JSONObject().put("roleCreated",true).put("legacyRoleId",1901)
            .put("starterProfile",1).put("gold",100000).put("rmb",10000)
            .put("guildCurrency",100000).put("recycleCurrency",100000)
            .put("drawCurrency",100000).put("exp",0);
        OriginalShop shop=OriginalShop.bundled();long now=1790380800L;
        ProtoWire all=ProtoWire.parse(shop.respond(state,fixture.getJSONObject("_catalog"),
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response);
        check(firstShop(set(all,44000071L)).number(4,0)==4,
            "Guild regular shelf must retain four shared purchases");
        check(firstShop(set(all,44000068L)).number(4,0)==6,
            "Maze regular shelf must retain six shared purchases");
        for(long id:new long[]{44000016L,44000002L,44000015L}){
            ProtoWire shelf=firstShop(set(all,id));
            check(shelf.number(4,0)==-1,
                "Unlimited exchange shelf must hide native daily counter: "+id);
            check(firstGood(shelf).number(3,0)>=1000000,
                "Essence or wish good has finite stock: "+id);
        }
        for(ProtoWire.Field field:all.fields)if(field.number==1){
            ProtoWire setValue=ProtoWire.parse(field.data);
            long setId=setValue.number(1,0);
            if(setId==44000071L || setId==44000068L)continue;
            for(ProtoWire.Field shelfField:setValue.fields)if(shelfField.number==5){
                ProtoWire shelf=ProtoWire.parse(shelfField.data);
                check(shelf.number(4,0)==-1,
                    "Non-daily shelf leaks native daily counter in set "+setId);
            }
        }
        for(long id=44000047L;id<=44000051L;id++){
            ProtoWire slot=set(all,id);
            check(goodCount(firstShop(slot))==1,"Star shelf must show one random item: "+id);
            check(slot.number(4,0)==1,"Star shelf must allow a manual refresh: "+id);
            check(slot.number(2,0)<=86400,"Star shelf must reset within one China day: "+id);
        }
        ProtoWire allAgain=ProtoWire.parse(shop.respond(state,fixture.getJSONObject("_catalog"),
            "/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response);
        for(long id=44000047L;id<=44000051L;id++)
            check(firstGood(firstShop(set(all,id))).number(1,0)==
                firstGood(firstShop(set(allAgain,id))).number(1,0),
                "Star item rerolled without a refresh: "+id);
        System.out.println("ExchangePolicySelfTest: "+checks+" checks passed");
    }
}
