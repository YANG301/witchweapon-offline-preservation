package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/** Original ShopRefresh shopsetid request, SetInfo response and paid stock reset. */
public final class OriginalShopRefreshSelfTest {
    private static int checks;
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    private static JSONObject player(long id,long vipExp,long recycle)throws Exception{
        return new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",id).put("starterProfile",1).put("name","refresh-test")
            .put("vipExp",vipExp).put("recycleCurrency",recycle)
            .put("gold",1000).put("rmb",0).put("stamina",200).put("exp",0);
    }
    private static Map<String,String> refresh(long set,String id){
        Map<String,String> args=new HashMap<String,String>();
        args.put("shopsetid",Long.toString(set));
        if(id!=null)args.put("idempotency",id);
        return args;
    }
    private static Map<String,String> buy(long good){
        Map<String,String> args=new HashMap<String,String>();
        args.put("setid","44000047");args.put("shopid","4502500014");
        args.put("goodsid",Long.toString(good));args.put("count","1");
        return args;
    }
    private static ProtoWire set(ProtoWire all,long id)throws Exception{
        for(ProtoWire.Field field:all.fields)if(field.number==1){
            ProtoWire candidate=ProtoWire.parse(field.data);
            if(candidate.number(1,0)==id)return candidate;
        }
        throw new AssertionError("Shop set absent: "+id);
    }
    private static ProtoWire firstGood(ProtoWire set)throws Exception{
        for(ProtoWire.Field shopField:set.fields)if(shopField.number==5){
            ProtoWire shop=ProtoWire.parse(shopField.data);
            if(shop.number(1,0)!=4502500014L)continue;
            for(ProtoWire.Field goodField:shop.fields)if(goodField.number==2){
                return ProtoWire.parse(goodField.data);
            }
        }
        throw new AssertionError("Refreshable good absent");
    }
    private static void rejected(OriginalShop store,JSONObject state,JSONObject catalog,
                                 Map<String,String> args,long now)throws Exception{
        String before=state.toString();
        try{store.respond(state,catalog,"/shop/refresh",args,new byte[0],now);
            throw new AssertionError("Unavailable refresh accepted");}
        catch(IOException expected){}
        check(before.equals(state.toString()),"Rejected refresh mutated account state");
    }
    public static void main(String[] argv)throws Exception{
        if(argv.length!=1)throw new IllegalArgumentException("responses.json required");
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(Paths.get(argv[0])),
            StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");
        OriginalShop store=OriginalShop.bundled();
        long now=1790337600L;
        JSONObject vip0=player(14,0,1000),vip1=player(15,1000,1000);
        ProtoWire before=ProtoWire.parse(store.respond(vip1,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response);
        check(set(before,44000047L).number(4,-1)==1,
            "Daily star shop refresh enabled: wire="+
            set(before,44000047L).number(4,-1)+" vip="+VipSystem.level(vip1.getLong("vipExp")));
        check(set(before,44000047L).number(8,-1)==0,"Initial refresh count zero");
        check(set(before,44000070L).number(4,-1)==0,"7# manual refresh remains disabled");
        check(set(ProtoWire.parse(store.respond(vip0,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response),44000047L)
            .number(4,-1)==1,"Level-one account may refresh daily star shop");
        rejected(store,vip1,catalog,refresh(44000070L,null),now);
        long offered=firstGood(set(before,44000047L)).number(1,0);
        check(offered>0,"One of the original star goods is selected");
        check("Buy Success".equals(new String(ProtoWire.parse(store.respond(vip1,catalog,
            "/shop/buy",buy(offered),new byte[0],now).response).data(1),StandardCharsets.UTF_8)),
            "Selected one-item star good is purchasable");
        ProtoWire sold=set(ProtoWire.parse(store.respond(vip1,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response),44000047L);
        check(firstGood(sold).number(3,-1)==0,"Stock becomes zero after purchase");
        check(vip1.getLong("recycleCurrency")==970,"Original item costs 30 recycle coins");
        byte[] refreshed=store.respond(vip1,catalog,"/shop/refresh",
            refresh(44000047L,"first"),new byte[0],now).response;
        ProtoWire setInfo=ProtoWire.parse(refreshed);
        check(setInfo.number(1,0)==44000047L && setInfo.number(8,-1)==1,
            "ShopRefresh returns original SetInfo envelope with count one");
        check(setInfo.number(4,0)==1 && firstGood(setInfo).number(3,-1)==1,
            "Manual refresh immediately offers one new original item");
        check(vip1.getLong("recycleCurrency")==820,"Original 150 recycle coin price debited");
        check(java.util.Arrays.equals(refreshed,store.respond(vip1,catalog,"/shop/refresh",
            refresh(44000047L,"first"),new byte[0],now).response),
            "Same refresh request ID replays SetInfo");
        check(vip1.getLong("recycleCurrency")==820,"Refresh retry does not charge twice");
        for(int i=2;i<=4;i++){
            ProtoWire receipt=ProtoWire.parse(store.respond(vip1,catalog,"/shop/refresh",
                refresh(44000047L,"refresh-"+i),new byte[0],now).response);
            check(receipt.number(8,-1)==i,"Refresh count advances once");
        }
        check(vip1.getLong("recycleCurrency")==370,"Four refreshes cost 600 total");
        check(set(ProtoWire.parse(store.respond(vip1,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],now).response),44000047L)
            .number(4,-1)==1,"Manual support flag must survive the last success; count enforces the limit");
        rejected(store,vip1,catalog,refresh(44000047L,"fifth"),now);
        check(vip1.getLong("recycleCurrency")==370,"Limit rejection preserves balance");
        long next=now+24*3600L;
        ProtoWire renewed=set(ProtoWire.parse(store.respond(vip1,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),new byte[0],next).response),44000047L);
        check(renewed.number(8,-1)==0&&renewed.number(4,-1)==1,
            "Daily star-shop period resets manual allowance");
        check(firstGood(renewed).number(3,-1)==1,"Auto refresh restores one shelf item next day");

        Path directory=Files.createTempDirectory("original-shop-refresh-");
        try{
            Files.write(directory.resolve("offline_save_v1.json"),
                player(16,1000,1000).toString().getBytes(StandardCharsets.UTF_8));
            LocalSave save=new LocalSave(directory.toFile());
            ProtoWire receipt=ProtoWire.parse(save.respond("/shop/refresh",
                refresh(44000047L,"persist"),new byte[0],catalog));
            check(receipt.number(1,0)==44000047L&&receipt.number(8,-1)==1,
                "Real LocalSave route returns SetInfo");
            JSONObject disk=new JSONObject(new String(Files.readAllBytes(
                directory.resolve("offline_save_v1.json")),StandardCharsets.UTF_8));
            check(disk.getLong("recycleCurrency")==850,
                "Real LocalSave route persists original price once");
            check(disk.getJSONObject("originalShopRefreshes")
                .getJSONObject("44000047").getInt("count")==1,
                "Per-account refresh ledger survives restart");
            LocalSave reopened=new LocalSave(directory.toFile());
            ProtoWire retry=ProtoWire.parse(reopened.respond("/shop/refresh",
                refresh(44000047L,"persist"),new byte[0],catalog));
            check(retry.number(8,-1)==1&&new JSONObject(new String(Files.readAllBytes(
                directory.resolve("offline_save_v1.json")),StandardCharsets.UTF_8))
                .getLong("recycleCurrency")==850,"Persisted retry is idempotent");
        }finally{
            try(java.util.stream.Stream<Path> paths=Files.walk(directory)){
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path->{
                    try{Files.deleteIfExists(path);}catch(Exception ignored){}
                });
            }
        }
        System.out.println("OriginalShopRefreshSelfTest: "+checks+" checks passed");
    }
}
