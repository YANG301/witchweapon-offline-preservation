package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.time.OffsetDateTime;
import org.json.JSONObject;

/** Real catalog transactions and simulated calendar boundaries, no live role. */
public final class StarShopSelfTest {
    private static int checks;
    private static void check(boolean ok,String why){checks++;if(!ok)throw new AssertionError(why);}
    private static long time(String text){return OffsetDateTime.parse(text+"+08:00").toEpochSecond();}
    private static JSONObject role(long vip)throws Exception {
        return new JSONObject().put("version",1).put("roleCreated",true).put("starterProfile",1)
            .put("legacyRoleId",12345).put("vipExp",vip).put("recycleCurrency",1000000)
            .put("gold",1).put("rmb",1).put("exp",0);
    }
    private static List<ProtoWire> children(ProtoWire wire,int field)throws Exception {
        List<ProtoWire> list=new ArrayList<ProtoWire>();
        for(ProtoWire.Field f:wire.fields)if(f.number==field&&f.type==2)list.add(ProtoWire.parse(f.data));
        return list;
    }
    private static ProtoWire set(OriginalShop shop,JSONObject state,JSONObject catalog,long id,long now)throws Exception {
        ProtoWire result=ProtoWire.parse(shop.respond(state,catalog,"/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response);
        for(ProtoWire s:children(result,1))if(s.number(1,0)==id)return s;
        throw new AssertionError("Missing original set "+id);
    }
    private static ProtoWire first(ProtoWire set)throws Exception {return children(children(set,5).get(0),2).get(0);}
    private static Map<String,String> request(ProtoWire set,ProtoWire good,int count,String retry)throws Exception {
        Map<String,String> args=new HashMap<String,String>();
        args.put("setid",""+set.number(1,0));args.put("shopid",""+children(set,5).get(0).number(1,0));
        args.put("goodsid",""+good.number(1,0));args.put("count",""+count);
        if(retry!=null)args.put("idempotency",retry);return args;
    }
    private static ProtoWire buy(OriginalShop shop,JSONObject state,JSONObject catalog,ProtoWire set,ProtoWire good,int count,String retry,long now)throws Exception {
        return ProtoWire.parse(shop.respond(state,catalog,"/shop/buy",request(set,good,count,retry),new byte[0],now).response);
    }
    private static void success(ProtoWire result){check(new String(result.data(1),StandardCharsets.UTF_8).equals("Buy Success"),"Native purchase succeeds");}
    private static void rejected(OriginalShop shop,JSONObject state,JSONObject catalog,ProtoWire set,ProtoWire good,long now)throws Exception {
        String before=state.toString();boolean rejected=false;
        try{buy(shop,state,catalog,set,good,1,null,now);}catch(java.io.IOException ex){rejected=true;}
        check(rejected,"Original CAPH requirement enforced");check(before.equals(state.toString()),"Rejection preserves all progress and money");
    }
    public static void main(String[] args)throws Exception {
        JSONObject catalog=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8)).getJSONObject("_catalog");
        JSONObject shelves=new JSONObject(new String(Files.readAllBytes(Paths.get(args[1])),StandardCharsets.UTF_8));
        OriginalShop shop=OriginalShop.bundled();long now=time("2026-10-02T07:00:00");
        JSONObject player=role(23000);int devices=0;
        for(long id=44000042;id<=44000046;id++) {
            ProtoWire shelf=set(shop,player,catalog,id,now);
            check(shelf.number(7,0)==time("2026-10-03T00:00:00"),"Cube device shelves use daily reset");
            check(shelf.number(8,-1)==0,"Cube devices do not acquire manual refresh count");
            for(ProtoWire g:children(children(shelf,5).get(0),2)){
                check(g.number(2,0)==100&&g.number(3,0)==-1,"Original 100-fragment devices have genuine unlimited wire stock");devices++;
            }
            ProtoWire good=first(shelf);long before=player.getLong("recycleCurrency");
            success(buy(shop,player,catalog,shelf,good,3,"cube-"+id,now));
            check(player.getLong("recycleCurrency")==before-300,"Batch purchase debits three original unit prices");
            success(buy(shop,player,catalog,shelf,good,3,"cube-"+id,now));
            check(player.getLong("recycleCurrency")==before-300,"Retry never charges twice");
            check(first(set(shop,player,catalog,id,now)).number(3,0)==-1,"Purchasing does not invent finite stock");
        }
        check(devices==5,"Cube selects one item per candidate group, five visible devices");
        check(!player.has("originalShopClaims"),"Unlimited devices have no stock claim ledger");
        ProtoWire lowShelf=set(shop,role(0),catalog,44000042,now);
        rejected(shop,role(0),catalog,lowShelf,first(lowShelf),now);
        int total=0;for(long id=44000047;id<=44000051;id++) {
            ProtoWire shelf=set(shop,player,catalog,id,now);
            check(children(children(shelf,5).get(0),2).size()==1,"One item from each original recollection group");
            check(first(shelf).number(2,0)==30&&first(shelf).number(3,0)==1,"Original recollection price and stock");total++;
        }
        check(total==5,"Five original recollection slots preserved");
        JSONObject vip1=role(1000);ProtoWire recalled=set(shop,vip1,catalog,44000047,now);
        ProtoWire recalledResult=buy(shop,vip1,catalog,recalled,first(recalled),1,"recall-first",now);
        success(recalledResult);
        check(ProtoWire.parse(ProtoWire.parse(recalledResult.data(4)).data(6)).integers(2).equals(java.util.Arrays.asList(44000047L)),
            "Native ShopEvent synchronizes the exact purchased set, not a fake VIP increment");
        check(set(shop,vip1,catalog,44000047,now).number(10,-1)==1,"Purchase immediately increases native per-set VipExtra");
        check(set(shop,vip1,catalog,44000048,now).number(10,-1)==0,"Other slots keep independent conditions");
        Map<String,String> refresh=new HashMap<String,String>();refresh.put("setid","44000047");
        refresh.put("idempotency","recall-refresh");
        ProtoWire renewed=ProtoWire.parse(shop.respond(vip1,catalog,"/shop/refresh",refresh,new byte[0],now).response);
        check(renewed.number(10,0)==1,"Manual refresh preserves increased CAPH condition");
        rejected(shop,vip1,catalog,renewed,first(renewed),now);
        vip1.put("vipExp",23000);
        for(int i=0;i<4;i++) {
            if(i>0){refresh.put("idempotency","recall-more-"+i);renewed=ProtoWire.parse(shop.respond(vip1,catalog,"/shop/refresh",refresh,new byte[0],now).response);}
            success(buy(shop,vip1,catalog,renewed,first(renewed),1,"recall-buy-"+i,now));
        }
        check(set(shop,vip1,catalog,44000047,now).number(10,-1)==4,"CAPH requirement caps at original Lv.5");
        ProtoWire nextDay=set(shop,vip1,catalog,44000047,time("2026-10-03T00:00:00"));
        check(nextDay.number(10,-1)==0&&nextDay.number(8,-1)==0&&first(nextDay).number(3,0)==1,"Daily reset restores recollection stock, condition and refresh allowance together");
        for(String[] pair:new String[][]{
            {"2026-02-28T23:59:59","2026-03-01T00:00:00"},
            {"2028-02-29T23:59:59","2028-03-01T00:00:00"},
            {"2026-12-31T23:59:59","2027-01-01T00:00:00"},
            {"2026-10-31T23:59:59","2026-11-01T00:00:00"}}) {
            JSONObject p=role(23000);long end=time(pair[1]),start=end-1;
            ProtoWire shelf=set(shop,p,catalog,44000052,start);check(shelf.number(7,0)==end,"Natural two-month boundary, including leap years");
            check(children(children(shelf,5).get(0),2).size()==6,"Six original resource products");
            success(buy(shop,p,catalog,shelf,first(shelf),1,null,start));
            check(first(set(shop,p,catalog,44000052,start)).number(3,-1)==0,"Finite product sold out immediately");
            check(first(set(shop,p,catalog,44000052,end)).number(3,-1)==1,"Inventory resets at next natural month pair");
        }
        long middle=time("2026-10-20T11:00:00");JSONObject p=role(23000);
        ProtoWire shelf=set(shop,p,catalog,44000052,now);
        success(buy(shop,p,catalog,shelf,first(shelf),1,null,now));
        check(first(set(shop,p,catalog,44000052,middle)).number(3,-1)==0,"Intermediate days do not replenish bimonthly resources");
        check(children(children(set(shop,player,catalog,44000053,now),5).get(0),2).isEmpty(),"No cores without an active event");
        check(children(children(set(shop,player,catalog,44000054,now),5).get(0),2).isEmpty(),"No costumes without an active event");
        JSONObject activeCatalog=new JSONObject(shelves.toString());
        org.json.JSONArray windows=new org.json.JSONArray();
        for(long timeId:StarShopEvents.IDS)windows.put(new JSONObject().put("timeId",timeId).put("start",now-1).put("end",time("2028-01-01T00:00:00")));
        activeCatalog.getJSONObject("policy").put("starEventWindows",windows);
        OriginalShop activeShop=new OriginalShop(activeCatalog);
        ProtoWire cores=set(activeShop,player,catalog,44000053,now);
        check(children(children(cores,5).get(0),2).size()==4&&first(cores).number(3,-1)==2,"Four original cores, two per cycle");
        success(buy(activeShop,player,catalog,cores,first(cores),1,null,now));
        check(first(set(activeShop,player,catalog,44000053,middle)).number(3,-1)==1,"Non-device core inventory follows original natural month help rule");
        ProtoWire costumes=set(activeShop,player,catalog,44000054,now);
        check(children(children(costumes,5).get(0),2).size()==15,"Fifteen original costumes");
        check(costumes.number(3,-1)==0&&costumes.number(7,-1)==0,"Original costumes have no automatic refresh period");
        check(first(costumes).number(2,0)==12500&&first(costumes).number(3,-1)==1,"Original costume price and one-time stock");
        player.put("ownedServants",new JSONObject(catalog.getJSONObject("servants").toString()));
        success(buy(activeShop,player,catalog,costumes,first(costumes),1,null,now));
        check(first(set(activeShop,player,catalog,44000054,time("2027-01-01T00:00:00"))).number(3,-1)==0,"Costumes do not resell at month rollover");
        // A deployed old 60-day claim is carried only through this release's
        // current calendar cycle, not indefinitely across future boundaries.
        JSONObject old=role(23000);JSONObject resourceSet=null;
        for(int i=0;i<shelves.getJSONArray("sets").length();i++){
            JSONObject candidate=shelves.getJSONArray("sets").getJSONObject(i);
            if(candidate.getLong("id")==44000052)resourceSet=candidate;
        }
        check(resourceSet!=null,"Original resource set present");
        long good=first(shelf).number(1,0),shopID=children(shelf,5).get(0).number(1,0);
        old.put("originalShopClaims",new JSONObject().put("44000052:"+shopID+":"+good,
            new JSONObject().put("bucket",StarShopPolicy.legacyBucket(resourceSet,now)).put("count",1)));
        check(first(set(shop,old,catalog,44000052,now)).number(3,-1)==0,"Existing purchased stock survives policy migration");
        check(first(set(shop,old,catalog,44000052,time("2026-11-01T00:00:00"))).number(3,-1)==1,"Legacy stock resets at next correct calendar boundary");
        System.out.println("StarShopSelfTest: "+checks+" checks passed");
    }
}
