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

/**
 * Original CN exchange, 7# daily secret and weekend airship shelves.
 *
 * Catalog IDs, prices and limits come from the APK. Historical server event
 * dates and random seeds are not in the APK; our deterministic reset policy is
 * explicit in exchange_shop_catalog.json. Called under LocalSave's lock.
 */
final class OriginalShop {
    private static final String RESOURCE="/exchange_shop_catalog.json";
    private static final String BUY_SUCCESS="Buy Success";
    private static final String SOLD_OUT="Sold Out";
    private static final String NO_GOODS="No This Goods";
    private static final int UNLIMITED=1000000;
    private static OriginalShop singleton;
    private final List<JSONObject> sets=new ArrayList<JSONObject>();
    private final Map<Long,JSONObject> bySet=new HashMap<Long,JSONObject>();
    private final int guildDiscountChance;
    private final int guildDiscountAmount;
    private final Random prayerRandom;
    private final long starScheduleEffectiveAt;
    private final StarShopEvents starEvents;

    static synchronized OriginalShop bundled()throws Exception {
        if(singleton!=null)return singleton;
        InputStream in=OriginalShop.class.getResourceAsStream(RESOURCE);
        if(in==null)throw new IOException("Original exchange catalog missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buf=new byte[8192];int n;
            while((n=in.read(buf))!=-1){
                if(out.size()+n>1024*1024)throw new IOException("Exchange catalog too large");
                out.write(buf,0,n);
            }
            singleton=new OriginalShop(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }finally{in.close();}
    }

    OriginalShop(JSONObject catalog)throws Exception {
        this(catalog,new java.security.SecureRandom());
    }

    OriginalShop(JSONObject catalog,Random random)throws Exception {
        prayerRandom=random;
        starEvents=new StarShopEvents(catalog);
        JSONObject policy=catalog.optJSONObject("policy");
        starScheduleEffectiveAt=policy==null?0:policy.optLong("starScheduleEffectiveAt",0);
        if(catalog.getInt("schemaVersion")!=1)throw new IOException("Unsupported exchange catalog");
        JSONObject discounts=catalog.optJSONObject("guildOriginDiscount");
        guildDiscountChance=discounts==null?0:discounts.getInt("chanceBasisPoints");
        guildDiscountAmount=discounts==null?0:discounts.getInt("discountBasisPoints");
        if(guildDiscountChance<0||guildDiscountChance>10000||
           guildDiscountAmount<0||guildDiscountAmount>=10000)
            throw new IOException("Invalid guild exchange discount policy");
        JSONArray source=catalog.getJSONArray("sets");
        if(source.length()!=23)throw new IOException("Incomplete original exchange catalog");
        for(int i=0;i<source.length();i++){
            JSONObject set=source.getJSONObject(i);long id=set.getLong("id");
            if(bySet.put(id,set)!=null)throw new IOException("Duplicate exchange set "+id);
            int refreshPrice=set.optInt("refreshPrice"),refreshLimit=set.optInt("refreshLimit");
            if(refreshPrice>0 && (id<44000047L || id>44000051L ||
                    set.optInt("refreshCurrencyType")!=10 || refreshPrice!=150 ||
                    refreshLimit!=4 || set.optInt("needVip")!=1 ||
                    set.optInt("vipIncrease")!=1 || set.optLong("refreshItem")!=0))
                throw new IOException("Unverified exchange refresh terms "+id);
            if(refreshPrice==0 && refreshLimit!=0)
                throw new IOException("Unpriced exchange refresh limit "+id);
            sets.add(set);
            JSONArray shops=set.getJSONArray("shops");
            if(shops.length()<1)throw new IOException("Empty exchange set");
            for(int j=0;j<shops.length();j++){
                JSONObject shop=shops.getJSONObject(j);
                int type=shop.getInt("priceType");
                if(type!=1&&type!=2&&type!=6&&type!=7&&type!=9&&type!=10&&type!=50)
                    throw new IOException("Unknown original shop currency");
                if(shop.getJSONArray("goods").length()<1)throw new IOException("Empty exchange shelf");
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
    private static boolean starSlot(JSONObject set){
        long id=set.optLong("id");
        return id>=44000047L&&id<=44000051L;
    }
    private static int periodHours(JSONObject set){
        // The five original 追忆之泉 shelves each select one of their own item
        // pools. The preservation schedule requested here is a China day.
        return StarShopPolicy.daily(set)?24:set.optInt("periodHours");
    }
    private static int minimumRefreshVip(JSONObject set){
        // The restored server opens functions to new accounts from level one.
        return starSlot(set)?0:set.optInt("needVip");
    }
    private static int dayOfWeek(long now){
        // Unix epoch was Thursday; Monday=0, Saturday=5, Sunday=6.
        return (int)Math.floorMod(chinaDay(now)+3,7);
    }
    private boolean open(JSONObject set,long now){
        if(StarShopPolicy.activitySet(set)&&!starEvents.anyOpen(now))return false;
        return !set.optBoolean("weekendOnly")||dayOfWeek(now)>=5;
    }
    private static long bucket(JSONObject set,long now){
        if(StarShopPolicy.naturalMonths(set))return StarShopPolicy.monthBucket(now);
        int hours=periodHours(set);
        if(hours<=0)return 0;
        long day=chinaDay(now);
        if(hours==168)return Math.floorDiv(day+3,7);
        if(hours%24==0)return Math.floorDiv(day,hours/24);
        return Math.floorDiv(now+28800L,hours*3600L);
    }
    private static long periodStart(JSONObject set,long now){
        if(StarShopPolicy.naturalMonths(set))return StarShopPolicy.monthStart(now,false);
        int hours=periodHours(set);
        if(hours<=0)return 0;
        long period=bucket(set,now),day;
        if(hours==168)day=period*7-3;
        else if(hours%24==0)day=period*(hours/24);
        else return period*hours*3600L-28800L;
        return day*86400L-28800L;
    }
    private static long periodEnd(JSONObject set,long now){
        if(StarShopPolicy.naturalMonths(set))return StarShopPolicy.monthStart(now,true);
        int hours=periodHours(set);
        return hours<=0?0:Math.addExact(periodStart(set,now),hours*3600L);
    }
    private static String claimKey(long set,long shop,long good){
        return set+":"+shop+":"+good;
    }
    private static JSONObject claims(JSONObject state)throws IOException{
        Object value=state.opt("originalShopClaims");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid shop claim ledger");
        return (JSONObject)value;
    }
    private static JSONObject replay(JSONObject state)throws IOException{
        Object value=state.opt("originalShopReplay");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid shop replay ledger");
        return (JSONObject)value;
    }
    private static boolean noStock(JSONObject set){
        long id=set.optLong("id");
        // Maze origin and Prayer remain unrestricted by the owner's request.
        // Guild origin uses its original per-good stock (one per rotation).
        return id==44000002L || id==44000015L || id>=44000042L&&id<=44000046L;
    }
    private static int limit(JSONObject set,JSONObject good){
        if(noStock(set))return UNLIMITED;
        int n=good.optInt("stock");return n==0?UNLIMITED:n;
    }
    private static int refreshCount(JSONObject state,JSONObject set,long now)throws IOException{
        JSONObject ledger=state.optJSONObject("originalShopRefreshes");
        if(ledger==null)return 0;
        JSONObject record=ledger.optJSONObject(Long.toString(set.optLong("id")));
        if(record==null||record.optLong("bucket",Long.MIN_VALUE)!=bucket(set,now))return 0;
        int n=record.optInt("count",-1);
        if(n<0||n>set.optInt("refreshLimit",0))throw new IOException("Corrupt shop refresh count");
        return n;
    }
    private int starGroupRefreshCount(JSONObject state,long now)throws IOException {
        int count=0;
        for(long id=44000047;id<=44000051;id++)count=Math.max(count,refreshCount(state,bySet.get(id),now));
        return count;
    }
    private int used(JSONObject state,JSONObject set,JSONObject shop,JSONObject good,long now)
            throws Exception{
        if(noStock(set))return 0;
        JSONObject record=claims(state).optJSONObject(claimKey(
            set.getLong("id"),shop.getLong("id"),good.getLong("id")));
        if(record==null||record.optLong("bucket",Long.MIN_VALUE)!=bucket(set,now)&&
           !StarShopPolicy.legacyStock(record,set,now,starScheduleEffectiveAt)||
           record.optInt("refreshCount",0)!=refreshCount(state,set,now))return 0;
        int n=record.optInt("count",-1);
        if(n<0||n>limit(set,good))throw new IOException("Corrupt shop stock");
        return n;
    }
    private int shopUsed(JSONObject state,JSONObject set,JSONObject shop,long now)
            throws Exception{
        int total=0;JSONArray goods=shop.getJSONArray("goods");
        for(int i=0;i<goods.length();i++)
            total=Math.addExact(total,used(state,set,shop,goods.getJSONObject(i),now));
        return total;
    }
    private static int starExtra(JSONObject state,JSONObject set,long now)throws Exception {
        if(!starSlot(set))return 0;
        JSONObject ledger=state.optJSONObject("originalStarPurchases");
        JSONObject record=ledger==null?null:ledger.optJSONObject(Long.toString(set.optLong("id")));
        if(record!=null){
            if(record.optLong("day",Long.MIN_VALUE)!=chinaDay(now))return 0;
            int count=record.optInt("count",-1);
            if(count<0||count>4)throw new IOException("Invalid star purchase conditions");
            return count;
        }
        // Existing current-day purchases retain their increased condition.
        int total=0;JSONObject old=claims(state);String prefix=set.optLong("id")+":";
        for(java.util.Iterator<String> it=old.keys();it.hasNext();){
            String key=it.next();if(!key.startsWith(prefix))continue;
            JSONObject claim=old.optJSONObject(key);
            if(claim!=null&&claim.optLong("bucket",Long.MIN_VALUE)==bucket(set,now))
                total=Math.min(4,total+Math.max(0,claim.optInt("count",0)));
        }
        return total;
    }
    private static int starNeedVip(JSONObject state,JSONObject set,JSONObject good,long now)throws Exception {
        if(!StarShopPolicy.star(set))return 0;
        if(starSlot(set))return Math.min(5,set.optInt("needVip")+starExtra(state,set,now));
        return Math.max(set.optInt("needVip"),good.optInt("needVip"));
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
    private List<JSONObject> selected(JSONObject state,JSONObject set,JSONObject shop,long now)
            throws Exception{
        JSONArray raw=shop.getJSONArray("goods");
        List<JSONObject> selected=new ArrayList<JSONObject>();
        for(int i=0;i<raw.length();i++) {
            JSONObject good=raw.getJSONObject(i);
            if(StarShopPolicy.activitySet(set)&&!starEvents.open(good.optLong("timeId"),now))continue;
            selected.add(good);
        }
        int count=starSlot(set)||StarShopPolicy.cubeDevice(set)?1:shop.optInt("randomNum");
        if(count<=0||selected.size()<=count)return selected;
        // Stable per account and refresh period.  No request may reroll items.
        String identity=state.optLong("legacyRoleId",0)+":"+set.getLong("id")+":"+
                        shop.getLong("id")+":"+bucket(set,now)+":"+(starSlot(set)?0:refreshCount(state,set,now));
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(
            identity.getBytes(StandardCharsets.UTF_8));
        long seed=0;for(int i=0;i<8;i++)seed=(seed<<8)|(hash[i]&255L);
        Collections.shuffle(selected,new Random(seed));
        // A day's four paid refreshes move through one shuffled pool. Every
        // slot changes and all five daily offers differ within their own pool.
        if(starSlot(set)) {
            JSONObject good=selected.get(refreshCount(state,set,now)%selected.size());
            selected=new ArrayList<JSONObject>();selected.add(good);return selected;
        }
        selected=new ArrayList<JSONObject>(selected.subList(0,count));
        Collections.sort(selected,new Comparator<JSONObject>(){
            public int compare(JSONObject a,JSONObject b){
                return Long.compare(a.optLong("id"),b.optLong("id"));
            }
        });
        return selected;
    }
    private static boolean visible(JSONObject set,JSONObject shop,int level){
        long id=set.optLong("id");
        if(id==44000188L||id==44000016L){
            // Keep entrances open from level one, but do not expand every
            // tier into the same shelf. The preserved guild table ends at 67;
            // higher roles retain that last verified pool instead of emptiness.
            int shelfLevel=id==44000016L?Math.min(level,67):level;
            return shelfLevel>=shop.optInt("levelMin",1)&&
                   shelfLevel<=shop.optInt("levelMax",100);
        }
        return level>=1;
    }
    private int discount(JSONObject state,JSONObject set,JSONObject shop,
                         JSONObject good,long now)throws Exception{
        if(set.optLong("id")!=44000016L||guildDiscountChance==0||
           guildDiscountAmount==0)return 0;
        JSONArray refs=shop.optJSONArray("discountIds");
        if(refs==null||refs.length()==0)return 0;
        // Historical server odds are absent from the original files. This
        // configurable 20% chance / 10% reduction was explicitly approved.
        // A separate deterministic draw cannot reroll on opening or purchase.
        String key="guild-discount:"+state.optLong("legacyRoleId",0)+":"+
            set.getLong("id")+":"+shop.getLong("id")+":"+good.getLong("id")+
            ":"+bucket(set,now)+":"+refreshCount(state,set,now);
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(key.getBytes(StandardCharsets.UTF_8));
        long sample=0;for(int i=0;i<4;i++)sample=(sample<<8)|(hash[i]&255L);
        return sample%10000<guildDiscountChance?guildDiscountAmount:0;
    }
    private static long unitPrice(JSONObject good,int discount)throws Exception{
        return Math.multiplyExact(good.getLong("price"),10000L-discount)/10000L;
    }
    private ProtoWire shopWire(JSONObject state,JSONObject set,JSONObject shop,
                                      int level,long now)throws Exception{
        // The original client displays its shared "remaining today" widget
        // whenever Shop.Number is nonnegative. Only the guild and maze daily
        // shelves use that widget here. The 7# and airship catalog caps are
        // still enforced below and reflected in Goods stock, but their event
        // pages must not briefly show the reused daily-counter widget.
        int total=shop.optInt("maxTotal"),left=total<=0?-1:
            Math.max(0,total-shopUsed(state,set,shop,now));
        long bigSetId=set.optLong("bigSetId");
        int displayed=(bigSetId==47000006L||bigSetId==47000023L)?left:-1;
        ProtoWire result=new ProtoWire().set(1,shop.getLong("id"))
            .set(3,visible(set,shop,level)&&open(set,now)?1:0).set(4,displayed);
        for(JSONObject good:selected(state,set,shop,now)){
            int stock=Math.max(0,limit(set,good)-used(state,set,shop,good,now));
            if(total>0)stock=Math.min(stock,left);
            if(noStock(set)&&total<=0)stock=-1; // Native unlimited quantity semantics.
            int reduction=discount(state,set,shop,good,now);
            result.add(2,new ProtoWire().set(1,good.getLong("id"))
                .set(2,good.getInt("price")).set(3,stock).set(4,reduction)
                .set(5,reduction>0?1:0).bytes());
        }
        return result;
    }
    private ProtoWire setWire(JSONObject state,JSONObject catalog,JSONObject set,long now)
            throws Exception{
        int period=periodHours(set);
        long start=periodStart(set,now),end=periodEnd(set,now);
        int count=refreshCount(state,set,now);
        int vip=VipSystem.level(state.optLong("vipExp",0));
        boolean manual=set.optInt("refreshPrice")>0 &&
            vip>=minimumRefreshVip(set) && open(set,now);
        ProtoWire wire=new ProtoWire().set(1,set.getLong("id"))
            .set(2,period>0?Math.max(0,end-now):0)
            .set(3,period>0?1:0).set(4,manual?1:0)
            .set(6,start).set(7,end).set(8,count).set(9,open(set,now)?1:0)
            .set(10,starExtra(state,set,now));
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
        else if(type==85)
            LocalEconomy.grantItemReward(state,catalog,new JSONObject().put("type",85)
                .put("id",id).put("value",good.getLong("value")).put("count",count),1);
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
            for(JSONObject set:sets)output.add(1,setWire(state,catalog,set,now).bytes());
            output.set(2,0); // No real-money payment integration.
            return new Action(output.bytes(),false);
        }
        if(path.equals("/shop/refresh")){
            // NetMsgField.shopsetid is the native symbol; its wire key is
            // "setid". Keep the old explicit alias, but reject conflicts.
            long setId=positive(args,"setid","shopsetid");
            JSONObject set=bySet.get(setId);
            if(set==null||set.optInt("refreshPrice")<=0)
                throw new IOException("This exchange set cannot be refreshed manually");
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
            int currentCount=starSlot(set)?starGroupRefreshCount(state,now):refreshCount(state,set,now);
            if(!open(set,now)||VipSystem.level(state.optLong("vipExp",0))<minimumRefreshVip(set)||
               currentCount>=set.getInt("refreshLimit"))
                throw new IOException("Shop manual refresh unavailable");
            int type=set.getInt("refreshCurrencyType");String key=currencyKey(type);
            if(key==null)throw new IOException("Unknown shop refresh currency");
            long cost=set.getLong("refreshPrice"),balance=state.optLong(key,0);
            if(cost<=0||balance<cost)throw new IOException("Insufficient shop refresh currency");
            int nextCount=currentCount+1;
            state.put(key,balance-cost);
            JSONObject records=state.optJSONObject("originalShopRefreshes");
            if(records==null)records=new JSONObject();
            if(starSlot(set)) {
                // Native ManualFresh sends only the first SetInfo ID. It is
                // one page refresh, not five independent 150-fragment charges.
                for(long id=44000047;id<=44000051;id++)records.put(Long.toString(id),
                    new JSONObject().put("bucket",bucket(bySet.get(id),now)).put("count",nextCount));
            }else records.put(Long.toString(setId),new JSONObject().put("bucket",bucket(set,now))
                .put("count",nextCount));
            state.put("originalShopRefreshes",records);
            state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
            byte[] response=setWire(state,catalog,set,now).bytes();
            if(ledger!=null){
                ledger.put(requestId,new JSONObject().put("fingerprint",fingerprint)
                    .put("response",Base64.encodeToString(response,Base64.NO_WRAP)).put("at",now));
                trimReplay(ledger);state.put("originalShopReplay",ledger);
            }
            return new Action(response,true);
        }
        if(!path.equals("/shop/buy"))throw new IOException("Unknown exchange route");
        long setId=positive(args,"setid","shopsetid");
        long shopId=positive(args,"shopid"),goodId=positive(args,"goodsid","goodid","shopgoodid");
        long count=positive(args,"count");
        if(count>100)throw new IOException("Shop quantity too large");
        JSONObject set=bySet.get(setId);
        if(set==null)return message(NO_GOODS);
        JSONObject shop=find(set.getJSONArray("shops"),shopId);
        if(shop==null)return message(NO_GOODS);
        JSONObject good=find(shop.getJSONArray("goods"),goodId);
        if(good==null)return message(NO_GOODS);
        if(PrayerShop.isSet(setId)&&count!=1)
            throw new IOException("Prayer exchanges purchase one weapon at a time");
        if(!state.optBoolean("roleCreated",false))throw new IOException("Role required for shop");
        if(!open(set,now)||!visible(set,shop,roleLevel(state,catalog))||
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
                return new Action(Base64.decode(previous.getString("response"),Base64.DEFAULT),false);
            }
        }
        int already=used(state,set,shop,good,now);
        int total=shop.optInt("maxTotal");
        if(count>limit(set,good)-already ||
           total>0&&count>total-shopUsed(state,set,shop,now))return message(SOLD_OUT);
        if(VipSystem.level(state.optLong("vipExp",0))<starNeedVip(state,set,good,now))
            throw new IOException("CAPH level does not meet original star shop conditions");
        int type=shop.getInt("priceType");String key=currencyKey(type);
        if(key==null)throw new IOException("Unknown shop currency");
        long cost=Math.multiplyExact(unitPrice(good,discount(state,set,shop,good,now)),count);
        long balance=state.optLong(key,0);
        if(cost<0||balance<cost)throw new IOException("Insufficient "+key);
        LocalEconomy.init(state,catalog);
        // All validation and granting occur on LocalSave's transaction copy.
        // An exception leaves the committed save and displayed stock intact.
        state.put(key,balance-cost);
        List<ProtoWire> rewards;
        if(PrayerShop.isSet(setId)){
            rewards=PrayerShop.bundled().exchange(state,catalog,good,count,prayerRandom);
        }else{
            grant(state,catalog,good,count);
            rewards=new ArrayList<ProtoWire>();rewards.add(loot(good,count));
        }
        int nextStarExtra=starSlot(set)?Math.min(4,starExtra(state,set,now)+(int)count):0;
        if(!noStock(set)){
            JSONObject all=claims(state);
            all.put(claimKey(setId,shopId,goodId),new JSONObject()
                .put("bucket",bucket(set,now)).put("refreshCount",refreshCount(state,set,now))
                .put("count",already+(int)count).put("periodRule",StarShopPolicy.star(set)?2:0));
            state.put("originalShopClaims",all);
        }
        if(starSlot(set)){
            JSONObject purchases=state.optJSONObject("originalStarPurchases");
            if(purchases==null)purchases=new JSONObject();
            purchases.put(Long.toString(setId),new JSONObject().put("day",chinaDay(now)).put("count",nextStarExtra));
            state.put("originalStarPurchases",purchases);
        }
        state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
        ProtoWire result=new ProtoWire().text(1,BUY_SUCCESS);
        if(starSlot(set)){
            // Native ExtraInfo.ShopEvent.Values are set IDs to synchronize,
            // not CAPH increments. GetSetData then receives field 10 VipExtra.
            result.set(4,new ProtoWire().add(6,new ProtoWire().add(2,setId).bytes()).bytes());
        }
        for(ProtoWire reward:rewards)result.add(5,reward.bytes());
        byte[] bytes=result.bytes();
        if(ledger!=null){
            ledger.put(requestId,new JSONObject().put("fingerprint",fingerprint)
                .put("response",Base64.encodeToString(bytes,Base64.NO_WRAP)).put("at",now));
            trimReplay(ledger);state.put("originalShopReplay",ledger);
        }
        return new Action(bytes,true);
    }
}
