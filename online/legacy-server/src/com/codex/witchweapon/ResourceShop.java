package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/** Original CN resource and sundry shelves, plus zero-cost virtual recharge. */
final class ResourceShop {
    private static final String RESOURCE="/resource_shop_catalog.json";
    private static final String BUY_SUCCESS="Buy Success";
    private static final String SOLD_OUT="Sold Out";
    private static final String NO_GOODS="No This Goods";
    private static final int UNLIMITED=1000000;
    // The archived 24-hour material shelf and event-only investigation pass
    // are absent from the original permanent Resource page shown to players.
    private static final long RETIRED_RESOURCE_SET=44000028L;
    private static final long RETIRED_EVENT_GOOD=45030256L;
    private static ResourceShop singleton;
    private final List<JSONObject> sets=new ArrayList<JSONObject>();
    private final Map<Long,JSONObject> bySet=new HashMap<Long,JSONObject>();

    static synchronized ResourceShop bundled()throws Exception {
        if(singleton!=null)return singleton;
        InputStream in=ResourceShop.class.getResourceAsStream(RESOURCE);
        if(in==null)throw new IOException("Original resource catalog missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buf=new byte[8192];int n;
            while((n=in.read(buf))!=-1){
                if(out.size()+n>1024*1024)throw new IOException("Resource catalog too large");
                out.write(buf,0,n);
            }
            singleton=new ResourceShop(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }finally{in.close();}
    }

    ResourceShop(JSONObject catalog)throws Exception {
        if(catalog.getInt("schemaVersion")!=1)throw new IOException("Unsupported resource catalog");
        JSONArray source=catalog.getJSONArray("sets");
        if(source.length()!=4)throw new IOException("Incomplete original resource catalog");
        for(int i=0;i<source.length();i++){
            JSONObject set=source.getJSONObject(i);long id=set.getLong("id");
            if(bySet.put(id,set)!=null)throw new IOException("Duplicate resource set "+id);
            int refreshPrice=set.optInt("refreshPrice"),refreshLimit=set.optInt("refreshLimit");
            if(id!=44000028L && id!=44000009L && id!=44000247L && id!=44000007L)
                throw new IOException("Unexpected resource set "+id);
            if(refreshPrice>0 && (id!=44000247L ||
                    set.optInt("refreshCurrencyType")!=50 || refreshPrice!=10 ||
                    refreshLimit!=30))
                throw new IOException("Unverified sundry refresh terms "+id);
            if(refreshPrice==0 && refreshLimit!=0)
                throw new IOException("Unpriced exchange refresh limit "+id);
            sets.add(set);
            JSONArray shops=set.getJSONArray("shops");
            if(shops.length()<1)throw new IOException("Empty resource set");
            for(int j=0;j<shops.length();j++){
                JSONObject shop=shops.getJSONObject(j);
                int type=shop.getInt("priceType");
                if(type!=1&&type!=50&&type!=99)
                    throw new IOException("Unknown resource shop currency");
                if(shop.getJSONArray("goods").length()<1)throw new IOException("Empty resource shelf");
            }
        }
    }

    static final class Action {
        final byte[] response;
        final boolean changed;
        Action(byte[] response,boolean changed){this.response=response;this.changed=changed;}
    }

    static boolean purchase(Map<String,String> args){
        String raw=args.containsKey("setid")?args.get("setid"):args.get("shopsetid");
        if(raw==null)return false;
        try{return bundled().bySet.containsKey(Long.parseLong(raw));}
        catch(Exception e){return false;}
    }
    static boolean refresh(Map<String,String> args){
        String id=args.containsKey("setid")?args.get("setid"):args.get("shopsetid");
        return "44000247".equals(id);
    }

    private static long positive(Map<String,String> args,String... keys)throws IOException{
        String raw=null;
        for(String key:keys)if(args.containsKey(key)){
            String candidate=args.get(key);
            if(raw!=null&&!raw.equals(candidate))throw new IOException("Conflicting shop IDs");
            raw=candidate;
        }
        if(raw==null||!raw.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid shop ID");
        try{return Long.parseLong(raw);}catch(NumberFormatException e){throw new IOException("Invalid shop ID",e);}
    }
    private static String digest(String text)throws Exception{
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder(bytes.length*2);
        for(byte b:bytes)hex.append(Character.forDigit((b>>>4)&15,16))
                            .append(Character.forDigit(b&15,16));
        return hex.toString();
    }
    private static long chinaDay(long now){return Math.floorDiv(now+28800L,86400L);}
    private static int dayOfWeek(long now){
        // Unix epoch was Thursday; Monday=0, Saturday=5, Sunday=6.
        return (int)Math.floorMod(chinaDay(now)+3,7);
    }
    private static boolean open(JSONObject set,long now){
        return !set.optBoolean("weekendOnly")||dayOfWeek(now)>=5;
    }
    private static long bucket(JSONObject set,long now){
        int hours=set.optInt("periodHours");
        if(hours<=0)return 0;
        long day=chinaDay(now);
        if(hours==168)return Math.floorDiv(day+3,7);
        if(hours%24==0)return Math.floorDiv(day,hours/24);
        return Math.floorDiv(now+28800L,hours*3600L);
    }
    private static long claimBucket(JSONObject set,JSONObject good,long now){
        String period=good.optString("claimPeriod","");
        if(period.equals("day"))return chinaDay(now);
        if(period.equals("week"))return Math.floorDiv(chinaDay(now)+3,7);
        if(period.equals("month")){
            java.time.LocalDate date=java.time.Instant.ofEpochSecond(now)
                .atOffset(java.time.ZoneOffset.ofHours(8)).toLocalDate();
            return Math.addExact(Math.multiplyExact((long)date.getYear(),12L),date.getMonthValue());
        }
        return bucket(set,now);
    }
    private static long periodStart(JSONObject set,long now){
        int hours=set.optInt("periodHours");
        if(hours<=0)return 0;
        long period=bucket(set,now),day;
        if(hours==168)day=period*7-3;
        else if(hours%24==0)day=period*(hours/24);
        else return period*hours*3600L-28800L;
        return day*86400L-28800L;
    }
    private static long periodEnd(JSONObject set,long now){
        int hours=set.optInt("periodHours");
        return hours<=0?0:Math.addExact(periodStart(set,now),hours*3600L);
    }
    private static String claimKey(long set,long shop,long good){
        return set+":"+shop+":"+good;
    }
    private static JSONObject claims(JSONObject state)throws IOException{
        Object value=state.opt("resourceShopClaims");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid shop claim ledger");
        return (JSONObject)value;
    }
    private static JSONObject replay(JSONObject state)throws IOException{
        Object value=state.opt("resourceShopReplay");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid shop replay ledger");
        return (JSONObject)value;
    }
    private static boolean unlimited(JSONObject good){return good.optInt("stock")==0;}
    // The original protocol sends a positive Goods.Number even for unlimited
    // goods. This is a display compatibility value, never a purchase cap.
    private static int limit(JSONObject good){int n=good.optInt("stock");return n==0?UNLIMITED:n;}
    private static int refreshCount(JSONObject state,JSONObject set,long now)throws IOException{
        JSONObject ledger=state.optJSONObject("resourceShopRefreshes");
        if(ledger==null)return 0;
        JSONObject record=ledger.optJSONObject(Long.toString(set.optLong("id")));
        if(record==null||record.optLong("bucket",Long.MIN_VALUE)!=bucket(set,now))return 0;
        int n=record.optInt("count",-1);
        if(n<0||n>set.optInt("refreshLimit",0))throw new IOException("Corrupt shop refresh count");
        return n;
    }
    private static int used(JSONObject state,JSONObject set,JSONObject shop,JSONObject good,long now)
            throws Exception{
        if(unlimited(good))return 0;
        JSONObject record=claims(state).optJSONObject(claimKey(
            set.getLong("id"),shop.getLong("id"),good.getLong("id")));
        if(record==null||record.optLong("bucket",Long.MIN_VALUE)!=claimBucket(set,good,now)||
           record.optInt("refreshCount",0)!=refreshCount(state,set,now))return 0;
        int n=record.optInt("count",-1);
        if(n<0||n>limit(good))throw new IOException("Corrupt shop stock");
        return n;
    }
    private static int shopUsed(JSONObject state,JSONObject set,JSONObject shop,long now)
            throws Exception{
        int total=0;JSONArray goods=shop.getJSONArray("goods");
        for(int i=0;i<goods.length();i++)
            total=Math.addExact(total,used(state,set,shop,goods.getJSONObject(i),now));
        return total;
    }
    private static int roleLevel(JSONObject state,JSONObject catalog)throws Exception{
        long exp=state.optLong("exp",0);int level=state.optInt("starterProfile",0)==1?1:5;
        JSONObject curve=catalog.getJSONObject("roleLevels");
        while(level<100){
            long cost=curve.optLong(String.valueOf(level),Long.MAX_VALUE);
            if(cost<=0||exp<cost)break;
            exp-=cost;level++;
        }
        return level;
    }
    private static List<JSONObject> selected(JSONObject state,JSONObject set,JSONObject shop,long now)
            throws Exception{
        JSONArray raw=shop.getJSONArray("goods");
        List<JSONObject> selected=new ArrayList<JSONObject>();
        for(int i=0;i<raw.length();i++)selected.add(raw.getJSONObject(i));
        int count=shop.optInt("randomNum");
        if(count<=0||selected.size()<=count)return selected;
        // Stable per account and refresh period.  No request may reroll items.
        String identity=state.optLong("legacyRoleId",0)+":"+set.getLong("id")+":"+
                        shop.getLong("id")+":"+bucket(set,now)+":"+refreshCount(state,set,now);
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(
            identity.getBytes(StandardCharsets.UTF_8));
        long seed=0;for(int i=0;i<8;i++)seed=(seed<<8)|(hash[i]&255L);
        Collections.shuffle(selected,new Random(seed));
        selected=new ArrayList<JSONObject>(selected.subList(0,count));
        Collections.sort(selected,new Comparator<JSONObject>(){
            public int compare(JSONObject a,JSONObject b){
                return Long.compare(a.optLong("id"),b.optLong("id"));
            }
        });
        return selected;
    }
    private static boolean visible(JSONObject shop,int level){
        // The archived resource shelves have no role-level restriction.
        return level>=1;
    }
    private static ProtoWire shopWire(JSONObject state,JSONObject set,JSONObject shop,
                                      int level,long now)throws Exception{
        // -1 tells the original shop UI that this shelf has no shared daily
        // purchase limit. Goods.Number still carries each item's stock.
        int total=shop.optInt("maxTotal"),left=total<=0?-1:
            Math.max(0,total-shopUsed(state,set,shop,now));
        ProtoWire result=new ProtoWire().set(1,shop.getLong("id"))
            .set(3,visible(shop,level)&&open(set,now)?1:0).set(4,left);
        for(JSONObject good:selected(state,set,shop,now)){
            if(set.getLong("id")==44000009L&&good.getLong("id")==RETIRED_EVENT_GOOD)
                continue;
            int stock=Math.max(0,limit(good)-used(state,set,shop,good,now));
            if(total>0)stock=Math.min(stock,left);
            if(unlimited(good)&&total<=0)stock=-1;
            result.add(2,new ProtoWire().set(1,good.getLong("id"))
                .set(2,good.getInt("price")).set(3,stock).set(4,100).bytes());
        }
        return result;
    }
    private static ProtoWire setWire(JSONObject state,JSONObject catalog,JSONObject set,long now)
            throws Exception{
        int period=set.optInt("periodHours");
        long start=periodStart(set,now),end=periodEnd(set,now);
        int count=refreshCount(state,set,now);
        int vip=VipSystem.level(state.optLong("vipExp",0));
        boolean manual=set.optInt("refreshPrice")>0 &&
            vip>=set.optInt("needVip") && open(set,now);
        ProtoWire wire=new ProtoWire().set(1,set.getLong("id"))
            .set(2,period>0?Math.max(0,end-now):0)
            .set(3,period>0?1:0).set(4,manual?1:0)
            .set(6,start).set(7,end).set(8,count).set(9,open(set,now)?1:0)
            .set(10,0);
        int level=roleLevel(state,catalog);
        JSONArray shops=set.getJSONArray("shops");
        for(int i=0;i<shops.length();i++)
            wire.add(5,shopWire(state,set,shops.getJSONObject(i),level,now).bytes());
        return wire;
    }
    private static JSONObject find(JSONArray values,long id)throws Exception{
        for(int i=0;i<values.length();i++){
            JSONObject value=values.getJSONObject(i);
            if(value.optLong("id")==id)return value;
        }
        return null;
    }
    private static String currencyKey(int type){
        switch(type){
            case 1:return "gold";
            case 2:return "cscCurrency";
            case 3:return "activeCurrencyRed";
            case 4:return "activeCurrencyYellow";
            case 5:return "activeCurrencyBlue";
            case 6:return "activeCurrencyGreen";
            case 7:return "guildCurrency";
            case 8:return "vipPoint";
            case 9:return "drawCurrency";
            case 10:return "recycleCurrency";
            case 50:return "rmb";
            case 99:return "rmb"; // Zero-cost virtual recharge only.
            default:return null;
        }
    }
    private static ProtoWire loot(JSONObject good,long count)throws Exception{
        int type=good.getInt("type");long id=good.optLong("itemId");
        long amount=Math.multiplyExact(good.getLong("value"),count);
        long displayedNumber=type==2||type==3?amount:count;
        ProtoWire wire=new ProtoWire().set(1,type).set(3,amount).set(4,displayedNumber);
        if(id>0)wire.set(2,id);
        return wire;
    }
    private static void grant(JSONObject state,JSONObject catalog,JSONObject good,long count)
            throws Exception{
        int type=good.getInt("type");long id=good.optLong("itemId");
        long amount=Math.multiplyExact(good.getLong("value"),count);
        if(type==2||type==3){
            String bucket=type==2?"equips":"items";
            JSONObject inventory=state.getJSONObject(bucket);
            String key=Long.toString(id);
            if(!catalog.getJSONObject(bucket).has(key))throw new IOException("Unknown shop reward");
            long old=inventory.optLong(key),updated=Math.addExact(old,amount);
            if(type==3&&updated>LocalEconomy.stackCap(catalog,key))
                throw new IOException("Insufficient item stack space");
            inventory.put(key,updated);
        }else if(type==13||type==99)
            LocalEconomy.addResource(state,type==13?"gold":"rmb",0,amount);
        else throw new IOException("Unsupported shop reward");
    }
    private static Action message(String status){return new Action(new ProtoWire().text(1,status).bytes(),false);}
    private static void trimReplay(JSONObject replay)throws Exception{
        if(replay.length()<=256)return;
        String oldest=null;long time=Long.MAX_VALUE;
        for(java.util.Iterator<String> it=replay.keys();it.hasNext();){
            String key=it.next();JSONObject entry=replay.optJSONObject(key);
            long at=entry==null?0:entry.optLong("at",0);
            if(at<time){time=at;oldest=key;}
        }
        if(oldest!=null)replay.remove(oldest);
    }

    Action respond(JSONObject state,JSONObject catalog,String path,Map<String,String> args,
                   byte[] seed,long now)throws Exception{
        if(path.equals("/shop/allShopSet")||path.equals("/shop/getSetData")){
            ProtoWire output=ProtoWire.parse(seed);
            for(JSONObject set:sets){
                if(set.getLong("id")==RETIRED_RESOURCE_SET)continue;
                output.add(1,setWire(state,catalog,set,now).bytes());
            }
            output.set(2,0); // No real-money payment integration.
            return new Action(output.bytes(),false);
        }
        if(path.equals("/shop/refresh")){
            // NetMsgField.shopsetid is the native symbol; its wire key is
            // "setid". Keep the old explicit alias, but reject conflicts.
            long setId=positive(args,"setid","shopsetid");
            JSONObject set=bySet.get(setId);
            if(set==null||setId!=44000247L||set.optInt("refreshPrice")<=0)
                throw new IOException("Only sundry shelves can be refreshed manually");
            if(!state.optBoolean("roleCreated",false))throw new IOException("Role required for shop refresh");
            String requestId=args.get("idempotency");
            JSONObject ledger=null;
            String fingerprint=digest("refresh:"+setId+":"+bucket(set,now));
            if(requestId!=null){
                if(!requestId.matches("[A-Za-z0-9._:-]{1,128}"))
                    throw new IOException("Invalid shop refresh request ID");
                ledger=replay(state);JSONObject previous=ledger.optJSONObject(requestId);
                if(previous!=null){
                    if(!fingerprint.equals(previous.optString("fingerprint")))
                        throw new IOException("Conflicting shop refresh retry");
                    return new Action(Base64.decode(previous.getString("response"),Base64.DEFAULT),false);
                }
            }
            if(!open(set,now)||VipSystem.level(state.optLong("vipExp",0))<set.optInt("needVip")||
               refreshCount(state,set,now)>=set.getInt("refreshLimit"))
                throw new IOException("Shop manual refresh unavailable");
            int type=set.getInt("refreshCurrencyType");String key=currencyKey(type);
            if(key==null)throw new IOException("Unknown shop refresh currency");
            long cost=set.getLong("refreshPrice"),balance=state.optLong(key,0);
            if(cost<=0||balance<cost)throw new IOException("Insufficient shop refresh currency");
            int nextCount=refreshCount(state,set,now)+1;
            state.put(key,balance-cost);
            JSONObject records=state.optJSONObject("resourceShopRefreshes");
            if(records==null)records=new JSONObject();
            records.put(Long.toString(setId),new JSONObject().put("bucket",bucket(set,now))
                .put("count",nextCount));
            state.put("resourceShopRefreshes",records);
            state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
            byte[] response=setWire(state,catalog,set,now).bytes();
            if(ledger!=null){
                ledger.put(requestId,new JSONObject().put("fingerprint",fingerprint)
                    .put("response",Base64.encodeToString(response,Base64.NO_WRAP)).put("at",now));
                trimReplay(ledger);state.put("resourceShopReplay",ledger);
            }
            return new Action(response,true);
        }
        if(!path.equals("/shop/buy"))throw new IOException("Unknown resource route");
        long setId=positive(args,"setid","shopsetid");
        long shopId=positive(args,"shopid"),goodId=positive(args,"goodsid","goodid","shopgoodid");
        long count=positive(args,"count");
        if(count>100)throw new IOException("Shop quantity too large");
        JSONObject set=bySet.get(setId);
        if(set==null||setId==RETIRED_RESOURCE_SET||
                setId==44000009L&&goodId==RETIRED_EVENT_GOOD)
            return message(NO_GOODS);
        JSONObject shop=find(set.getJSONArray("shops"),shopId);
        if(shop==null)return message(NO_GOODS);
        JSONObject good=find(shop.getJSONArray("goods"),goodId);
        if(good==null)return message(NO_GOODS);
        if(!state.optBoolean("roleCreated",false))throw new IOException("Role required for shop");
        if(!open(set,now)||!visible(shop,roleLevel(state,catalog))||
           !selected(state,set,shop,now).contains(good))
            return message(NO_GOODS);
        String requestId=args.get("idempotency"),fingerprint=digest(setId+":"+shopId+":"+goodId+":"+count);
        JSONObject ledger=null;
        if(requestId!=null){
            if(!requestId.matches("[A-Za-z0-9._:-]{1,128}"))throw new IOException("Invalid shop request ID");
            ledger=replay(state);JSONObject previous=ledger.optJSONObject(requestId);
            if(previous!=null){
                if(!fingerprint.equals(previous.optString("fingerprint")))
                    throw new IOException("Conflicting shop retry");
                byte[] earlier=Base64.decode(previous.getString("response"),Base64.DEFAULT);
                return new Action(good.optLong("goodsScore",0)>0?
                    VipSystem.withBuyResultExtra(earlier,state):earlier,false);
            }
        }
        int already=used(state,set,shop,good,now);
        int total=shop.optInt("maxTotal");
        if(!unlimited(good)&&count>limit(good)-already ||
           total>0&&count>total-shopUsed(state,set,shop,now))return message(SOLD_OUT);
        int type=shop.getInt("priceType");String key=currencyKey(type);
        if(key==null)throw new IOException("Unknown shop currency");
        long cost=Math.multiplyExact(good.getLong("price"),count);
        long balance=state.optLong(key,0);
        if(cost<0||balance<cost)throw new IOException("Insufficient "+key);
        LocalEconomy.init(state,catalog);
        // All validation and granting occur on LocalSave's transaction copy.
        // An exception leaves the committed save and displayed stock intact.
        state.put(key,balance-cost);
        grant(state,catalog,good,count);
        long score=Math.multiplyExact(good.optLong("goodsScore",0),count);
        if(score<0)throw new IOException("Invalid recharge score");
        if(score>0){
            LocalEconomy.addResource(state,"vipExp",0,score);
            LocalEconomy.addResource(state,"vipPoint",0,score);
        }
        if(setId==44000007L){
            long cents=Math.multiplyExact(good.getLong("originalPrice"),count);
            if(cents<=0)throw new IOException("Invalid virtual recharge value");
            LocalEconomy.addResource(state,"virtualPurchaseCents",0,cents);
        }
        if(!unlimited(good)){
            JSONObject all=claims(state);
            all.put(claimKey(setId,shopId,goodId),new JSONObject()
                .put("bucket",claimBucket(set,good,now)).put("refreshCount",refreshCount(state,set,now))
                .put("count",already+(int)count));
            state.put("resourceShopClaims",all);
        }
        state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
        ProtoWire result=new ProtoWire().text(1,BUY_SUCCESS).add(5,loot(good,count).bytes());
        if(score>0){
            result.add(5,new ProtoWire().set(1,20).set(3,score).set(4,score).bytes());
            result.add(5,new ProtoWire().set(1,21).set(3,score).set(4,score).bytes());
        }
        byte[] bytes=score>0?VipSystem.withBuyResultExtra(result.bytes(),state):result.bytes();
        if(ledger!=null){
            ledger.put(requestId,new JSONObject().put("fingerprint",fingerprint)
                .put("response",Base64.encodeToString(bytes,Base64.NO_WRAP)).put("at",now));
            trimReplay(ledger);state.put("resourceShopReplay",ledger);
        }
        return new Action(bytes,true);
    }
}
