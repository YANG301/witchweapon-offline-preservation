package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/** Full permanent pools, owned-weapon filtering, duplicate rewards and retry accounting. */
public final class PrayerShopSelfTest {
    private static int checks;
    private static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
    private static JSONObject read(String path)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(Paths.get(path)),StandardCharsets.UTF_8));
    }
    private static final class Pick extends Random {
        int pick;int bound;int calls;
        @Override public int nextInt(int n){bound=n;calls++;check(pick>=0&&pick<n,"Test choice outside original pool");return pick;}
    }
    private static JSONObject role()throws Exception{
        return new JSONObject().put("roleCreated",true).put("starterProfile",1).put("legacyRoleId",77991)
            .put("drawCurrency",1000000).put("gold",1000).put("rmb",0).put("exp",0)
            .put("ownedServants",new JSONObject()).put("items",new JSONObject()).put("equips",new JSONObject());
    }
    private static Map<String,String> form(long good,String key){
        Map<String,String> result=new HashMap<String,String>();
        result.put("setid","44000015");result.put("shopid","4502090001");
        result.put("goodsid",Long.toString(good));result.put("count","1");
        if(key!=null)result.put("idempotency",key);return result;
    }
    private static List<ProtoWire> loots(byte[] raw)throws Exception{
        ProtoWire message=ProtoWire.parse(raw);check("Buy Success".equals(new String(message.data(1),StandardCharsets.UTF_8)),"Original buy success status");
        List<ProtoWire> results=new ArrayList<ProtoWire>();
        for(ProtoWire.Field field:message.fields)if(field.number==5)results.add(ProtoWire.parse(field.data));
        return results;
    }
    private static void own(JSONObject state,JSONObject catalog,long weapon)throws Exception{
        LocalEconomy.grantItemReward(state,catalog,new JSONObject().put("type",4).put("id",weapon).put("value",1).put("count",1),1);
    }
    public static void main(String[] args)throws Exception{
        check(args.length==3||args.length==4,"Pass offline responses, exchange and prayer catalog");
        JSONObject catalog=read(args[0]).getJSONObject("_catalog"),shelves=read(args[1]),prayer=read(args[2]);
        if(args.length==4&&args[3].equals("--baseline")){
            List<ProtoWire> baseline=loots(new OriginalShop(shelves).respond(role(),catalog,"/shop/buy",form(45030152,null),new byte[0],1700000000).response);
            check(baseline.size()>=2&&baseline.get(0).number(1,0)==1&&baseline.get(1).number(1,0)==4,
                "Prayer must return witch/weapon pair instead of voucher item");
            return;
        }
        Pick pick=new Pick();OriginalShop shop=new OriginalShop(shelves,pick);
        long[] costs={70,600,3000,140,1200,6000};int[] poolSizes={16,29,15};
        for(int category=0;category<3;category++){
            int rarity=NormalDrawRates.R-category;List<Long> pool=NormalDrawRates.weaponPool(rarity,catalog);
            check(pool.size()==poolSizes[category],"Exact disclosed permanent rarity pool");
            // Each index can be reached, even when every weapon is owned.
            JSONObject all=role();for(long weapon:pool)own(all,catalog,weapon);
            for(int index=0;index<pool.size();index++){
                JSONObject state=new JSONObject(all.toString());pick.pick=index;
                List<ProtoWire> results=loots(shop.respond(state,catalog,"/shop/buy",form(45030152L+category,null),new byte[0],1700000000).response);
                check(results.size()>=2,"Prayer must return witch/weapon pair instead of voucher item");
                check(pick.bound==pool.size()&&results.get(1).number(2,0)==pool.get(index),"Random exchange includes owned weapons uniformly");
                check(state.getLong("drawCurrency")==1000000-costs[category],"Original random exchange charge");
            }
            JSONObject first=role();pick.pick=0;
            List<ProtoWire> result=loots(shop.respond(first,catalog,"/shop/buy",form(45030155L+category,"special-first-"+category),new byte[0],1700000000).response);
            check(result.size()==2&&result.get(0).number(1,0)==1&&result.get(1).number(1,0)==4,"Original witch/weapon result pair");
            check(PrayerShop.ownedWeapons(first).contains(pool.get(0)),"Weapon ownership is persisted");
            check(first.getJSONObject("ownedServants").has(Long.toString(result.get(0).number(2,0))),"Associated witch unlocked");
            String unchanged=first.toString();int calls=pick.calls;
            byte[] replay=shop.respond(first,catalog,"/shop/buy",form(45030155L+category,"special-first-"+category),new byte[0],1700000000).response;
            check(first.toString().equals(unchanged)&&pick.calls==calls,"Retry never rerolls, charges or grants twice");
            check(loots(replay).get(1).number(2,0)==pool.get(0),"Same persisted result on replay");
            pick.pick=0;
            List<ProtoWire> missing=loots(shop.respond(first,catalog,"/shop/buy",form(45030155L+category,"special-next-"+category),new byte[0],1700000000).response);
            check(pick.bound==pool.size()-1&&missing.get(1).number(2,0)==pool.get(1),"Special filters owned weapons on every purchase");
            check(first.getLong("drawCurrency")==1000000-2*costs[3+category],"Special original cost charged twice");
            // With exactly one missing weapon, that weapon must be selected.
            JSONObject one=role();for(int index=0;index<pool.size()-1;index++)own(one,catalog,pool.get(index));
            List<ProtoWire> last=loots(shop.respond(one,catalog,"/shop/buy",form(45030155L+category,null),new byte[0],1700000000).response);
            check(pick.bound==1&&last.get(1).number(2,0)==pool.get(pool.size()-1),"Special chooses sole missing weapon");
            pick.pick=pool.size()-1;
            List<ProtoWire> fallback=loots(shop.respond(all,catalog,"/shop/buy",form(45030155L+category,null),new byte[0],1700000000).response);
            check(pick.bound==pool.size()&&fallback.get(1).number(2,0)==pool.get(pool.size()-1),"Special falls back to entire pool when all owned");
        }
        JSONObject duplicate=role();long weapon=1701000101L;own(duplicate,catalog,weapon);pick.pick=0;
        List<ProtoWire> rewards=loots(shop.respond(duplicate,catalog,"/shop/buy",form(45030152,"duplicate"),new byte[0],1700000000).response);
        check(rewards.size()==3&&rewards.get(2).number(1,0)==3&&rewards.get(2).number(2,0)==40240042&&rewards.get(2).number(4,0)==1,"Knife stone is the only explicit material loot");
        JSONObject items=duplicate.getJSONObject("items");
        check(items.getLong("40330003")==2&&items.getLong("40330006")==2&&items.getLong("40330039")==1&&items.getLong("40240042")==1,"Original duplicate decomposition really credited");
        check(items.getLong("40130001")==2,"Owned witch grants exact R fragments");
        JSONObject sameWitch=role();own(sameWitch,catalog,weapon);pick.pick=0;
        List<ProtoWire> newWeapon=loots(shop.respond(sameWitch,catalog,"/shop/buy",form(45030155,null),new byte[0],1700000000).response);
        check(newWeapon.get(1).number(2,0)==1701000102L&&sameWitch.getJSONObject("items").getLong("40130001")==2,"Missing second weapon eligible even when witch owned; fragments credited");
        for(String id:new String[]{"40330085","40330086","40340007","40340008","40350014","40350015"})
            check(items.optLong(id,0)==0,"Exchange must not grant unusable voucher "+id);
        JSONObject poor=role();poor.put("drawCurrency",69);String before=poor.toString();
        try{shop.respond(poor,catalog,"/shop/buy",form(45030152,null),new byte[0],1700000000);throw new AssertionError("Underfunded exchange accepted");}
        catch(java.io.IOException expected){check(poor.toString().equals(before),"Insufficient balance never mutates ownership/currency");}
        Map<String,String> bulk=form(45030152,null);bulk.put("count","2");
        try{shop.respond(poor,catalog,"/shop/buy",bulk,new byte[0],1700000000);throw new AssertionError("Bulk prayer accepted");}
        catch(java.io.IOException expected){check(poor.toString().equals(before),"Invalid bulk request never charges");}
        System.out.println("PrayerShopSelfTest: "+checks+" checks passed; all 60 weapons, random/special/fallback/decomposition/retry");
    }
}
