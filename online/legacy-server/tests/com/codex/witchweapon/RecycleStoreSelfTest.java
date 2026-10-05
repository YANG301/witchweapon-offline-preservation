package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;

/** Original Item.recycle_value and original RecycleInstance wire fields. */
public final class RecycleStoreSelfTest {
    private static void check(boolean condition,String text){if(!condition)throw new AssertionError(text);}
    private static Map<String,String> form(String... pairs){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)result.put(pairs[i],pairs[i+1]);
        return result;
    }
    private static void rejected(RecycleStore shop,JSONObject state,JSONObject catalog,
                                 Map<String,String> args)throws Exception {
        String before=state.toString();
        try{shop.sell(state,catalog,args);throw new AssertionError("Invalid recycle sale accepted");}
        catch(java.io.IOException expected){}
        check(before.equals(state.toString()),"Rejected recycling changed account state");
    }
    public static void main(String[] arguments)throws Exception {
        if(arguments.length!=2)throw new IllegalArgumentException("catalog values");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(arguments[0])),
            StandardCharsets.UTF_8));
        JSONObject values=new JSONObject(new String(Files.readAllBytes(Paths.get(arguments[1])),
            StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        RecycleStore shop=new RecycleStore(values);
        check(RecycleStore.handles("/resource/recycle/get")&&
            RecycleStore.handles("/resource/recycle")&&
            !RecycleStore.handles("/resource/sell/gold"),"Original route mapping differs");
        JSONObject state=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("gold",1000).put("recycleCurrency",0);
        LocalEconomy.init(state,catalog);
        state.getJSONObject("items").put("40130001",3).put("40130021",2);
        ProtoWire listing=ProtoWire.parse(shop.list(state,catalog));
        check(listing.number(100,-1)==190,"Original Item.recycle_value total differs");
        int listed=0;
        for(ProtoWire.Field field:listing.fields)if(field.number==1){
            ProtoWire item=ProtoWire.parse(field.data);
            long id=item.number(1,0),count=item.number(2,0),price=item.number(3,0);
            check(id==40130001L&&count==3&&price==30 ||
                  id==40130021L&&count==2&&price==50,"RecycleItem wire field differs");
            listed++;
        }
        check(listed==2,"Non-recyclable starter items appeared in sale list");
        rejected(shop,state,catalog,form("items","40130001","itemnums","4"));
        rejected(shop,state,catalog,form("items","40310001","itemnums","1"));
        rejected(shop,state,catalog,form("items","40130001|40130001","itemnums","1|1"));
        ProtoWire sold=ProtoWire.parse(shop.sell(state,catalog,
            form("items","40130001","itemnums","2")));
        boolean emptyMessage=false;
        for(ProtoWire.Field field:sold.fields)if(field.number==2&&field.type==2)emptyMessage=true;
        check("ok".equals(new String(sold.data(1),StandardCharsets.UTF_8))&&emptyMessage,
            "Recycle sale response is not original CommonInfo shape");
        check(state.getLong("recycleCurrency")==60&&
            state.getJSONObject("items").getLong("40130001")==1,
            "Partial recycle sale did not exchange at Item.recycle_value");
        shop.sell(state,catalog,form("items","","itemnums",""));
        check(state.getLong("recycleCurrency")==190&&
            state.getJSONObject("items").getLong("40130001")==0&&
            state.getJSONObject("items").getLong("40130021")==0,
            "Sell-all did not consume only remaining recyclable inventory");
        shop.sell(state,catalog,form());
        check(state.getLong("recycleCurrency")==190,
            "Empty repeated sell-all credited recycling currency twice");
        JSONObject other=new JSONObject().put("starterProfile",1).put("roleCreated",true);
        LocalEconomy.init(other,catalog);
        check(other.optLong("recycleCurrency",0)==0&&
            ProtoWire.parse(shop.list(other,catalog)).number(100,-1)==0,
            "Recycle balance or inventory leaked between accounts");
        System.out.println("RECYCLE_STORE_OK");
    }
}
