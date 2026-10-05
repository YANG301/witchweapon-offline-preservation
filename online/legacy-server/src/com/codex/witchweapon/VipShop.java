package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/** Original 47000009 C.A.P.H point exchange, separate from paid event shelves. */
final class VipShop {
    private static final long SET_ID=44000017L;
    private static final String RESOURCE="/caph_shop_catalog.json";
    private static VipShop singleton;
    private final JSONObject source;
    private final JSONArray shops;
    private final Map<Long,JSONObject> goods=new HashMap<Long,JSONObject>();
    private final Map<Long,JSONObject> shelf=new HashMap<Long,JSONObject>();
    static final class Action {
        final byte[] response;
        final boolean changed;
        Action(byte[] response,boolean changed){this.response=response;this.changed=changed;}
    }

    private VipShop(JSONObject document)throws Exception {
        if(document.getInt("schemaVersion")!=1 || document.getLong("bigSetId")!=47000009L ||
           document.getLong("setId")!=SET_ID)throw new IOException("Unexpected CAPH catalog");
        source=document;
        shops=document.getJSONArray("shops");
        if(shops.length()!=3)throw new IOException("Incomplete CAPH shelves");
        int[] counts={6,2,1};
        for(int i=0;i<shops.length();i++){
            JSONObject shop=shops.getJSONObject(i);
            if(shop.getLong("id")!=4502080001L+i || shop.getInt("priceType")!=8 ||
               shop.getJSONArray("goods").length()!=counts[i])
                throw new IOException("Unexpected CAPH point shelf");
            shelf.put(shop.getLong("id"),shop);
            JSONArray products=shop.getJSONArray("goods");
            for(int j=0;j<products.length();j++){
                JSONObject good=products.getJSONObject(j);
                int type=good.getInt("type");
                if(type!=3&&type!=13 || good.getLong("price")<0 ||
                   good.getLong("stock")<0 || good.getLong("value")<1 ||
                   goods.put(good.getLong("id"),good)!=null)
                    throw new IOException("Invalid CAPH point product");
            }
        }
    }

    static synchronized VipShop bundled()throws Exception {
        if(singleton!=null)return singleton;
        InputStream input=VipShop.class.getResourceAsStream(RESOURCE);
        if(input==null)throw new IOException("Original CAPH point catalog missing");
        try{
            ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            byte[] buffer=new byte[4096];int size;
            while((size=input.read(buffer))!=-1){
                if(bytes.size()+size>32768)throw new IOException("CAPH catalog too large");
                bytes.write(buffer,0,size);
            }
            singleton=new VipShop(new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }finally{input.close();}
    }

    static boolean purchase(Map<String,String> args){
        String raw=args.containsKey("setid")?args.get("setid"):args.get("shopsetid");
        return Long.toString(SET_ID).equals(raw);
    }

    private static long id(Map<String,String> args,String primary,String alternate)throws IOException {
        String raw=args.get(primary),other=alternate==null?null:args.get(alternate);
        if(raw!=null&&other!=null&&!raw.equals(other))throw new IOException("Conflicting CAPH shop ID");
        if(raw==null)raw=other;
        if(raw==null||!raw.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid CAPH shop ID");
        try{return Long.parseLong(raw);}catch(NumberFormatException ex){
            throw new IOException("Invalid CAPH shop ID",ex);
        }
    }

    private static JSONObject ledger(JSONObject state,String key)throws IOException {
        Object value=state.opt(key);
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid CAPH shop ledger");
        return (JSONObject)value;
    }

    private static String fingerprint(long shop,long good,long count)throws Exception {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(
            (SET_ID+":"+shop+":"+good+":"+count).getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder();
        for(byte b:hash){hex.append(Character.forDigit((b>>>4)&15,16));
                         hex.append(Character.forDigit(b&15,16));}
        return hex.toString();
    }

    private static ProtoWire loot(JSONObject good,long count)throws Exception {
        long amount=Math.multiplyExact(good.getLong("value"),count);
        ProtoWire item=new ProtoWire().set(1,good.getInt("type"))
            .set(3,amount).set(4,amount);
        if(good.getLong("itemId")>0)item.set(2,good.getLong("itemId"));
        return item;
    }

    private static void reward(JSONObject state,JSONObject catalog,JSONObject good,long count)
            throws Exception {
        int type=good.getInt("type");
        long amount=Math.multiplyExact(good.getLong("value"),count);
        if(type==13){LocalEconomy.addResource(state,"gold",0,amount);return;}
        String itemId=Long.toString(good.getLong("itemId"));
        if(!catalog.getJSONObject("items").has(itemId))
            throw new IOException("Unknown CAPH shop item");
        JSONObject inventory=state.getJSONObject("items");
        long quantity=Math.addExact(inventory.optLong(itemId,0),amount);
        if(quantity>LocalEconomy.stackCap(catalog,itemId))
            throw new IOException("CAPH shop inventory full");
        inventory.put(itemId,quantity);
    }

    private byte[] setInfo(JSONObject state)throws Exception {
        JSONObject claims=ledger(state,"vipShopClaims");
        ProtoWire set=new ProtoWire().set(1,SET_ID).set(2,0).set(3,0)
            .set(4,0).set(9,1).set(10,0);
        for(int i=0;i<shops.length();i++){
            JSONObject shop=shops.getJSONObject(i);
            ProtoWire wire=new ProtoWire().set(1,shop.getLong("id"))
                .set(3,1).set(4,-1);
            JSONArray products=shop.getJSONArray("goods");
            for(int j=0;j<products.length();j++){
                JSONObject good=products.getJSONObject(j);
                long stock=good.getLong("stock"),used=claims.optLong(
                    Long.toString(good.getLong("id")),0);
                if(used<0 || stock>0&&used>stock)
                    throw new IOException("Invalid CAPH shop stock ledger");
                wire.add(2,new ProtoWire().set(1,good.getLong("id"))
                    .set(2,good.getLong("price"))
                    .set(3,stock==0?1000000:stock-used).set(4,100).bytes());
            }
            set.add(5,wire.bytes());
        }
        return set.bytes();
    }

    Action respond(JSONObject state,JSONObject catalog,String path,
                   Map<String,String> args,byte[] seed,long now)throws Exception {
        if(path.equals("/shop/allShopSet")||path.equals("/shop/getSetData")){
            ProtoWire result=ProtoWire.parse(seed);
            // Cached fixture data must not expose the closed activity shelf.
            for(Iterator<ProtoWire.Field> it=result.fields.iterator();it.hasNext();) {
                ProtoWire.Field field=it.next();
                if(field.number==1&&field.type==2&&
                   ProtoWire.parse(field.data).number(1,0)==SET_ID)it.remove();
            }
            if(CaphActivityAccess.shopOpen(now))result.add(1,setInfo(state));
            return new Action(result.bytes(),false);
        }
        if(!path.equals("/shop/buy"))throw new IOException("Unknown CAPH shop route");
        if(!CaphActivityAccess.shopOpen(now))
            return new Action(new ProtoWire().text(1,"活动尚未开启，C.A.P.H商店暂未开放").bytes(),false);
        if(!state.optBoolean("roleCreated",false))throw new IOException("Role required for CAPH shop");
        if(id(args,"setid","shopsetid")!=SET_ID)
            throw new IOException("Wrong CAPH set ID");
        long shopId=id(args,"shopid",null),goodId=id(args,"goodsid","goodid");
        long count=id(args,"count",null);
        if(count>100)throw new IOException("CAPH purchase quantity too large");
        JSONObject shop=shelf.get(shopId),good=goods.get(goodId);
        if(shop==null||good==null)return new Action(new ProtoWire().text(1,"No This Goods").bytes(),false);
        boolean matched=false;
        JSONArray products=shop.getJSONArray("goods");
        for(int i=0;i<products.length();i++)
            if(products.getJSONObject(i).getLong("id")==goodId){matched=true;break;}
        if(!matched)return new Action(new ProtoWire().text(1,"No This Goods").bytes(),false);
        String requestId=args.get("idempotency");
        JSONObject replay=null;String digest=null;
        if(requestId!=null){
            if(!requestId.matches("[A-Za-z0-9._:-]{1,128}"))
                throw new IOException("Invalid CAPH purchase request ID");
            replay=ledger(state,"vipShopReplay");digest=fingerprint(shopId,goodId,count);
            JSONObject prior=replay.optJSONObject(requestId);
            if(prior!=null){
                if(!digest.equals(prior.optString("fingerprint")))
                    throw new IOException("Conflicting CAPH purchase retry");
                return new Action(Base64.decode(prior.getString("response"),Base64.DEFAULT),false);
            }
        }
        JSONObject claims=ledger(state,"vipShopClaims");
        String key=Long.toString(goodId);
        long used=claims.optLong(key,0),stock=good.getLong("stock");
        if(used<0)throw new IOException("Invalid CAPH shop claim count");
        if(stock>0&&count>stock-used)
            return new Action(new ProtoWire().text(1,"Sold Out").bytes(),false);
        long price=Math.multiplyExact(good.getLong("price"),count);
        long points=state.optLong("vipPoint",0);
        if(price<0||points<price)throw new IOException("Insufficient CAPH points");
        if(catalog==null)throw new IOException("CAPH item catalog unavailable");
        LocalEconomy.init(state,catalog);
        reward(state,catalog,good,count);
        state.put("vipPoint",points-price);
        claims.put(key,Math.addExact(used,count));state.put("vipShopClaims",claims);
        state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
        byte[] result=new ProtoWire().text(1,"Buy Success")
            .add(5,loot(good,count).bytes()).bytes();
        if(replay!=null){
            if(replay.length()>=256)throw new IOException("CAPH replay ledger full");
            replay.put(requestId,new JSONObject().put("fingerprint",digest)
                .put("response",Base64.encodeToString(result,Base64.NO_WRAP)).put("at",now));
            state.put("vipShopReplay",replay);
        }
        return new Action(result,true);
    }
}
