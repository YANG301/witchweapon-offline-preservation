package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Original channel-25 gift tab: free packages and monthly cards. */
final class GiftShop {
    private static final String RESOURCE="/gift_shop_catalog.json";
    private static final int MAX_REPLAY=256;
    // The preservation server offers only the seven packages requested for
    // the public Gift page. Other archived products remain in the catalog so
    // old claim/migration records can still be interpreted safely.
    private static final long[] PUBLIC_GOODS={45030285L,45030435L,45030619L,
        45030434L,45030301L,45030620L,45030621L,45820001L,45820006L};
    private static GiftShop singleton;
    private final List<JSONObject> sets=new ArrayList<JSONObject>();
    private final Map<Long,JSONObject> bySet=new HashMap<Long,JSONObject>();

    static synchronized GiftShop bundled() throws Exception {
        if(singleton!=null)return singleton;
        InputStream in=GiftShop.class.getResourceAsStream(RESOURCE);
        if(in==null)throw new IOException("Bundled original gift catalog missing");
        try {
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buf=new byte[4096];int n;
            while((n=in.read(buf))!=-1){
                if(out.size()+n>65536)throw new IOException("Gift catalog too large");
                out.write(buf,0,n);
            }
            singleton=new GiftShop(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        } finally {in.close();}
    }

    GiftShop(JSONObject document) throws Exception {
        JSONArray bigSets=document.getJSONArray("bigSetIds");
        if(document.getInt("schemaVersion")!=1 || bigSets.length()!=2 ||
           bigSets.getLong(0)!=47000002L || bigSets.getLong(1)!=47000016L)
            throw new IOException("Unexpected original gift catalog");
        JSONArray source=document.getJSONArray("sets");
        if(source.length()!=6)throw new IOException("Expected six original gift sets");
        int products=0,cards=0;
        for(int i=0;i<source.length();i++){
            JSONObject set=source.getJSONObject(i);long id=set.getLong("id");
            int period=set.getInt("periodHours");
            if(period!=0 && period!=24 && period!=168 || bySet.put(id,set)!=null)
                throw new IOException("Invalid original gift set");
            sets.add(set);
            JSONArray shops=set.getJSONArray("shops");
            for(int j=0;j<shops.length();j++){
                JSONArray goods=shops.getJSONObject(j).getJSONArray("goods");
                for(int k=0;k<goods.length();k++){
                    JSONObject good=goods.getJSONObject(k);
                    if(good.optLong("goodsScore",-1)<0 || good.optLong("originalPrice",-1)<0)
                        throw new IOException("Invalid archived gift value");
                    String kind=good.getString("kind");
                    if(kind.equals("monthCard")){
                        long card=good.getLong("monthCardId");
                        if(card!=1&&card!=6 || good.getInt("days")!=(card==1?30:15))
                            throw new IOException("Unexpected original monthly card");
                        cards++;
                    }else if(!kind.equals("item"))throw new IOException("Unknown gift kind");
                    products++;
                }
            }
        }
        if(products!=19 || cards!=2)throw new IOException("Expected 19 original gift goods");
    }

    static boolean handles(String path){
        return path.equals("/shop/allShopSet") || path.equals("/shop/getSetData") ||
            path.equals("/shop/buy");
    }
    static boolean giftPurchase(Map<String,String> args){
        String id=args.containsKey("setid")?args.get("setid"):args.get("shopsetid");
        return "44000025".equals(id)||"44000074".equals(id)||"44000088".equals(id)||
            "44000006".equals(id)||"44000061".equals(id)||"44000022".equals(id);
    }

    static final class Action {
        final byte[] response;
        final boolean changed;
        Action(byte[] response,boolean changed){this.response=response;this.changed=changed;}
    }
    // ShopSystemManagerController.DealResultBuy compares Result against these
    // exact native strings. A generic "ok" leaves its purchase callback idle.
    private static final String BUY_SUCCESS="Buy Success";
    private static final String SOLD_OUT="Sold Out";
    private static final String NO_GOODS="No This Goods";
    private static Action buyMessage(String message,boolean changed){
        return new Action(new ProtoWire().text(1,message).bytes(),changed);
    }

    // Same midnight-in-China clock as LocalDaily and DailyBattle. The original
    // shopset.txt specifies 24/168 hours, but its source server reset phase is
    // unavailable; a stable China-calendar day/week makes limits predictable.
    private static long chinaDay(long now){return Math.floorDiv(now+28800L,86400L);}
    private static long chinaMonth(long now){
        java.time.LocalDate date=Instant.ofEpochSecond(now).atOffset(ZoneOffset.ofHours(8)).toLocalDate();
        return Math.addExact(Math.multiplyExact((long)date.getYear(),12L),date.getMonthValue());
    }
    private static boolean publicGood(JSONObject good){
        long id=good.optLong("id",-1);
        for(long visible:PUBLIC_GOODS)if(visible==id)return true;
        return false;
    }
    private static long bucket(int period,long now){
        long day=chinaDay(now);
        if(period==24)return day;
        if(period==168)return Math.floorDiv(day+3L,7L); // Monday-to-Sunday.
        return 0;
    }
    private static long remainingSeconds(int period,long now){
        if(period==0)return 0;
        long day=chinaDay(now);
        long nextDay=period==24?day+1:
            Math.multiplyExact(Math.floorDiv(day+3L,7L)+1,7L)-3L;
        return Math.max(0,Math.multiplyExact(nextDay,86400L)-28800L-now);
    }
    private static String claimKey(long set,long shop,long good){return set+":"+shop+":"+good;}
    private static JSONObject claims(JSONObject state)throws IOException{
        Object value=state.opt("giftShopClaims");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid gift claim save");
        return (JSONObject)value;
    }
    private static JSONObject replay(JSONObject state)throws IOException{
        Object value=state.opt("giftShopReplay");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid gift replay save");
        return (JSONObject)value;
    }
    private static int limit(JSONObject good){
        int original=good.optInt("originalLimit",0);
        return original==0?1:original;
    }
    private static boolean monthCard(JSONObject good){return "monthCard".equals(good.optString("kind"));}
    private static JSONObject cards(JSONObject state)throws IOException{
        Object value=state.opt("giftMonthCards");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid monthly-card save");
        return (JSONObject)value;
    }
    private static long claimBucket(JSONObject set,JSONObject good,long now){
        if(monthCard(good))return chinaMonth(now);
        long id=good.optLong("id",-1);
        if(id==45030620L)return bucket(24,now);
        if(id==45030621L)return bucket(168,now);
        // The original 0 count means unbounded paid purchases. A free server
        // grants those two goods once daily, preventing infinite item farming.
        return bucket(good.optInt("originalLimit",0)==0?24:set.optInt("periodHours",0),now);
    }
    private static int used(JSONObject state,JSONObject set,JSONObject shop,JSONObject good,long now)
            throws Exception {
        // Both free cards may renew only in a later China calendar month,
        // after expiry and after all older daily mail has entered the mailbox.
        if(monthCard(good)){
            JSONObject card=cards(state).optJSONObject(Long.toString(good.getLong("monthCardId")));
            if(card!=null && (card.optLong("expiresDay",Long.MIN_VALUE)>chinaDay(now) ||
                card.optLong("lastGrantDay",Long.MIN_VALUE)<
                    card.optLong("expiresDay",Long.MIN_VALUE)-1))return 1;
        }
        JSONObject entry=claims(state).optJSONObject(claimKey(set.getLong("id"),shop.getLong("id"),good.getLong("id")));
        if(entry==null || entry.optLong("bucket",Long.MIN_VALUE)!=claimBucket(set,good,now))return 0;
        int count=entry.optInt("count",0);
        if(count<0 || count>limit(good))throw new IOException("Invalid gift claim count");
        return count;
    }
    private static ProtoWire shopWire(JSONObject state,JSONObject set,JSONObject shop,long now)
            throws Exception {
        // No gift shelf has a shared daily purchase limit. The original UI
        // interprets a negative Shop.Number as "hide the shared counter";
        // individual gift limits are enforced per Goods.Number below.
        ProtoWire wire=new ProtoWire().set(1,shop.getLong("id")).set(3,1)
            .set(4,-1);
        JSONArray goods=shop.getJSONArray("goods");
        for(int i=0;i<goods.length();i++){
            JSONObject good=goods.getJSONObject(i);
            if(!publicGood(good))continue;
            int available=limit(good)-used(state,set,shop,good,now);
            if(available<0)throw new IOException("Gift availability underflow");
            wire.add(2,new ProtoWire().set(1,good.getLong("id")).set(2,0)
                .set(3,available).set(4,100).bytes());
        }
        return wire;
    }
    private static ProtoWire setWire(JSONObject state,JSONObject set,long now)throws Exception {
        long left=remainingSeconds(set.getInt("periodHours"),now);
        ProtoWire wire=new ProtoWire().set(1,set.getLong("id")).set(2,left)
            .set(3,set.getInt("periodHours")>0?1:0).set(4,0)
            .set(6,left==0?0:Math.addExact(now,left)-set.getInt("periodHours")*3600L)
            .set(7,left==0?0:Math.addExact(now,left)).set(9,1);
        JSONArray shops=set.getJSONArray("shops");
        for(int i=0;i<shops.length();i++){
            JSONObject shop=shops.getJSONObject(i);
            JSONArray goods=shop.getJSONArray("goods");
            boolean visible=false;
            for(int j=0;j<goods.length();j++)if(publicGood(goods.getJSONObject(j))){visible=true;break;}
            if(visible)wire.add(5,shopWire(state,set,shop,now).bytes());
        }
        return wire;
    }
    private static long positive(Map<String,String> args,String... names)throws IOException {
        String value=null;
        for(String name:names){
            String candidate=args.get(name);
            if(candidate!=null){
                if(value!=null && !value.equals(candidate))throw new IOException("Conflicting gift form fields");
                value=candidate;
            }
        }
        if(value==null || !value.matches("[1-9][0-9]{0,18}"))
            throw new IOException("Missing or invalid gift form field");
        try{return Long.parseLong(value);}catch(NumberFormatException e){throw new IOException("Invalid gift number",e);}
    }
    private static String sha256(String input)throws Exception {
        byte[] digest=MessageDigest.getInstance("SHA-256").digest(input.getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder(64);
        for(byte b:digest)hex.append(Character.forDigit((b>>>4)&15,16))
                              .append(Character.forDigit(b&15,16));
        return hex.toString();
    }
    private static String requestKey(Map<String,String> args)throws Exception {
        String id=args.get("idempotency");
        if(id!=null){
            if(!id.matches("[A-Za-z0-9._:-]{1,128}"))throw new IOException("Invalid gift request ID");
            return sha256("id\u0000"+id);
        }
        String time=args.get("time"),sign=args.get("sign");
        if(time!=null && !time.matches("[0-9]{1,19}"))
            throw new IOException("Invalid native gift time");
        if(sign!=null && !sign.matches("[A-Za-z0-9._~+/=-]{8,512}"))
            throw new IOException("Invalid native gift sign");
        // NetMsgBase adds common authentication time/sign fields, not a
        // purchase nonce. They can remain the same for two intentional buys.
        return null;
    }
    private static void trimReplay(JSONObject entries)throws Exception {
        while(entries.length()>MAX_REPLAY){
            String oldest=null;long at=Long.MAX_VALUE;
            for(java.util.Iterator<String> it=entries.keys();it.hasNext();){
                String key=it.next();long moment=entries.getJSONObject(key).optLong("at",0);
                if(moment<at){at=moment;oldest=key;}
            }
            if(oldest==null)break;entries.remove(oldest);
        }
    }
    private static JSONObject findShop(JSONObject set,long shopId)throws Exception {
        JSONArray shops=set.getJSONArray("shops");
        for(int i=0;i<shops.length();i++){
            JSONObject shop=shops.getJSONObject(i);
            if(shop.getLong("id")==shopId)return shop;
        }
        return null;
    }
    private static JSONObject findGood(JSONObject shop,long goodId)throws Exception {
        JSONArray goods=shop.getJSONArray("goods");
        for(int i=0;i<goods.length();i++){
            JSONObject good=goods.getJSONObject(i);
            if(good.getLong("id")==goodId)return good;
        }
        return null;
    }
    /** Type 9 / subtype 5 is a purchase bundle, not a visible backpack item.
     * The original package panel only lists type-9 subtypes 13--15. Award the
     * exact Item.item_set_* contents and describe those contents in BuyResult.
     */
    private static List<ProtoWire> deliverPackage(JSONObject state,JSONObject catalog,
                                                  long itemId,long count)throws Exception {
        if(count<1||count>5)throw new IOException("Invalid gift package count");
        JSONObject definitions=catalog.getJSONObject("items");
        JSONObject packageItem=definitions.optJSONObject(Long.toString(itemId));
        if(packageItem==null || packageItem.optInt("item_type")!=9 ||
           packageItem.optInt("item_sub_type")!=5)
            throw new IOException("Original gift is not a supported purchase bundle");
        JSONArray rewards=packageItem.getJSONArray("rewards");
        if(rewards.length()<1||rewards.length()>15)
            throw new IOException("Original gift has invalid contents");
        List<ProtoWire> loots=new ArrayList<ProtoWire>();
        Map<String,Long> itemIncrease=new HashMap<String,Long>();
        for(int index=0;index<rewards.length();index++){
            JSONObject reward=rewards.getJSONObject(index);
            int type=reward.getInt("type");
            long id=reward.getLong("id"),value=reward.getLong("value");
            long units=reward.getLong("count");
            if(type!=3 && type!=12 && type!=13 && type!=81 && type!=99)
                throw new IOException("Unsupported original gift reward type");
            if(id<0||value<0||units<0 || (units==0&&value==0))
                throw new IOException("Invalid original gift reward");
            long amount=Math.multiplyExact(units>0?units:value,count);
            if(type==3){
                String key=Long.toString(id);
                JSONObject rewardItem=definitions.optJSONObject(key);
                if(rewardItem==null)throw new IOException("Original gift reward item missing");
                // None of the 17 original gift goods or two monthly chests
                // nests another subtype-5 box. Fail closed if a future table
                // does, rather than silently delivering another hidden item.
                if(rewardItem.optInt("item_type")==9 && rewardItem.optInt("item_sub_type")==5)
                    throw new IOException("Nested hidden gift reward needs explicit expansion");
                JSONObject bag=state.getJSONObject("items");
                long before=bag.optLong(key,0),cap=LocalEconomy.stackCap(catalog,key);
                long combined=Math.addExact(itemIncrease.containsKey(key)?itemIncrease.get(key):0L,amount);
                if(before<0||before>cap||combined>cap-before)
                    throw new IOException("Gift reward item stack is full");
                itemIncrease.put(key,combined);
            }else if(type==81){
                // The value is the cosmetic index, not a resource quantity.
                if(value<1||value>10000||units!=0||id!=0)
                    throw new IOException("Invalid original gift cosmetic");
            }else if(id!=0||units!=0){
                throw new IOException("Invalid original gift resource");
            }
            long displayedValue=type==81?value:amount;
            long displayedNumber=type==3?amount:count;
            loots.add(new ProtoWire().set(1,type).set(2,id)
                .set(3,displayedValue).set(4,displayedNumber));
        }
        // Validate the complete package before mutating any resource or item.
        for(int index=0;index<rewards.length();index++)
            LocalEconomy.grantItemReward(state,catalog,rewards.getJSONObject(index),count);
        return loots;
    }
    private static boolean fullStack(IOException failure){
        return "Gift reward item stack is full".equals(failure.getMessage());
    }
    /** Snapshot only already-claimed boxes from the previous server version.
     * New purchases are delivered directly and never enter this migration.
     */
    private boolean migrateClaimedBoxes(JSONObject state,JSONObject catalog)throws Exception {
        boolean changed=false;
        if(!state.optBoolean("giftShopLegacySnapshotTaken",false)){
            LocalEconomy.init(state,catalog);
            JSONObject bag=state.getJSONObject("items"),claims=claims(state);
            JSONObject eligible=new JSONObject();
            Map<String,Long> claimed=new HashMap<String,Long>();
            for(JSONObject set:sets){
                JSONArray shops=set.getJSONArray("shops");
                for(int i=0;i<shops.length();i++){
                    JSONObject shop=shops.getJSONObject(i),entry;
                    JSONArray goods=shop.getJSONArray("goods");
                    for(int j=0;j<goods.length();j++){
                        JSONObject good=goods.getJSONObject(j);
                        entry=claims.optJSONObject(claimKey(set.getLong("id"),
                            shop.getLong("id"),good.getLong("id")));
                        if(entry==null)continue;
                        int count=entry.optInt("count",0);
                        if(count<0||count>limit(good))
                            throw new IOException("Invalid legacy gift claim count");
                        String item;
                        long credited=count;
                        if(monthCard(good)){
                            JSONObject card=cards(state).optJSONObject(
                                Long.toString(good.getLong("monthCardId")));
                            if(card==null)continue;
                            long start=card.optLong("startDay",Long.MAX_VALUE);
                            long last=card.optLong("lastGrantDay",Long.MIN_VALUE);
                            long end=card.optLong("expiresDay",Long.MIN_VALUE);
                            if(start>=end || last<start || last>=end)continue;
                            // The old save records the last credited day but
                            // no per-day ledger. Existing server routes only
                            // produced this hidden ID for this month card.
                            credited=Math.min(good.getInt("days"),Math.addExact(last-start,1));
                            item=Long.toString(good.getLong("dailyItemId"));
                        }else item=Long.toString(good.getLong("itemId"));
                        claimed.put(item,Math.addExact(claimed.containsKey(item)?
                            claimed.get(item):0L,credited));
                    }
                }
            }
            for(Map.Entry<String,Long> entry:claimed.entrySet()){
                long pending=Math.min(bag.optLong(entry.getKey(),0),entry.getValue());
                if(pending<0)throw new IOException("Invalid legacy gift stock");
                if(pending>0)eligible.put(entry.getKey(),pending);
            }
            state.put("giftShopLegacyBoxPending",eligible);
            state.put("giftShopLegacySnapshotTaken",true);
            changed=true;
        }
        JSONObject pending=state.optJSONObject("giftShopLegacyBoxPending");
        if(pending==null||pending.length()==0)return changed;
        JSONObject bag=state.getJSONObject("items");
        List<String> keys=new ArrayList<String>();
        for(java.util.Iterator<String> it=pending.keys();it.hasNext();)keys.add(it.next());
        for(String key:keys){
            long allowed=pending.getLong(key),held=bag.optLong(key,0);
            if(allowed<0||held<0)throw new IOException("Invalid legacy gift migration");
            long amount=Math.min(allowed,held);
            if(amount>0){
                // A shop claim can cover at most five copies. Process in small
                // batches so the same validated delivery path is reused.
                while(amount>0){
                    long batch=Math.min(amount,5);
                    try{deliverPackage(state,catalog,Long.parseLong(key),batch);}
                    catch(IOException e){
                        if(fullStack(e))break; // Retry after the player frees space.
                        throw e;
                    }
                    bag.put(key,bag.getLong(key)-batch);
                    amount-=batch;
                    pending.put(key,Math.subtractExact(pending.getLong(key),batch));
                    state.put("inventoryRevision",Math.addExact(
                        state.optLong("inventoryRevision",0),1));
                    changed=true;
                }
            }
            // A claimed box removed before conversion must not make a later
            // unrelated box eligible. A full stack keeps only held boxes due.
            if(bag.optLong(key,0)==0 || pending.getLong(key)==0){pending.remove(key);changed=true;}
        }
        return changed;
    }
    /** Queue original daily chests as attachment mail on the next account
     * request. Offline days are caught up and each calendar day is committed
     * atomically with its mail, so retries and repeat logins cannot duplicate
     * rewards. If the mailbox is full, the unqueued days remain due.
     */
    boolean advanceMonthCards(JSONObject state,JSONObject inventoryCatalog,long now)throws Exception {
        boolean migrated=migrateClaimedBoxes(state,inventoryCatalog),cardChanged=false;
        JSONObject all=cards(state);
        if(all.length()==0)return migrated;
        long day=chinaDay(now);
        for(JSONObject set:sets){
            JSONArray shops=set.getJSONArray("shops");
            for(int i=0;i<shops.length();i++){
                JSONArray goods=shops.getJSONObject(i).getJSONArray("goods");
                for(int j=0;j<goods.length();j++){
                    JSONObject good=goods.getJSONObject(j);
                    if(!monthCard(good))continue;
                    JSONObject card=all.optJSONObject(Long.toString(good.getLong("monthCardId")));
                    if(card==null)continue;
                    long start=card.getLong("startDay"),end=card.getLong("expiresDay");
                    if(start<0 || Math.subtractExact(end,start)!=good.getInt("days"))
                        throw new IOException("Invalid monthly-card period");
                    long last=card.optLong("lastGrantDay",Long.MIN_VALUE);
                    if(last>=end)throw new IOException("Invalid monthly-card grant day");
                    long latest=Math.min(day,end-1);
                    for(long due=Math.max(start,last==Long.MIN_VALUE?start:last+1);
                            due<=latest;due++){
                        if(!LocalMail.queueMonthCard(state,inventoryCatalog,
                                good.getLong("monthCardId"),good.getLong("dailyItemId"),
                                due,Math.multiplyExact(now,1000L)))break;
                        card.put("lastGrantDay",due);
                        cardChanged=true;
                    }
                }
            }
        }
        if(cardChanged){
            state.put("giftMonthCards",all);
        }
        return migrated||cardChanged;
    }
    /** RoleInstanceProto fields 6/7 are month-card days and sent flags. */
    void monthCardRole(ProtoWire role,JSONObject state,long now)throws Exception {
        JSONObject all=cards(state);long day=chinaDay(now);
        role.clear(6).clear(7);
        for(int id=1;id<=13;id++){
            JSONObject card=all.optJSONObject(Integer.toString(id));
            long remaining=card==null?0:Math.max(0,card.optLong("expiresDay",0)-day);
            role.add(6,remaining);
            role.add(7,card!=null && remaining>0 &&
                card.optLong("lastGrantDay",Long.MIN_VALUE)==day?1:0);
        }
    }
    Action respond(JSONObject state,JSONObject inventoryCatalog,String path,Map<String,String> args,
                   byte[] seed,long now)throws Exception {
        boolean accrued=advanceMonthCards(state,inventoryCatalog,now);
        if(path.equals("/shop/allShopSet") || path.equals("/shop/getSetData")){
            // Preserve the author's existing non-gift set and append original
            // Gift-tab sets. The original client consumes shopmod.AllSets here.
            ProtoWire output=ProtoWire.parse(seed);
            for(JSONObject set:sets){
                // Hide archived festival groups which have no selected goods.
                long setId=set.getLong("id");
                if(setId==44000074L || setId==44000061L)continue;
                output.add(1,setWire(state,set,now).bytes());
            }
            output.set(2,0); // CanPay=false: never invoke a payment SDK.
            return new Action(output.bytes(),accrued);
        }
        if(!path.equals("/shop/buy"))throw new IOException("Unknown gift route");
        long setId=positive(args,"setid","shopsetid");
        long shopId=positive(args,"shopid");
        long goodId=positive(args,"goodsid","goodid","shopgoodid");
        long count=positive(args,"count");
        if(count>5)throw new IOException("Gift claim batch too large");
        JSONObject set=bySet.get(setId);
        if(set==null)return buyMessage(NO_GOODS,accrued);
        JSONObject shop=findShop(set,shopId);
        if(shop==null)return buyMessage(NO_GOODS,accrued);
        JSONObject good=findGood(shop,goodId);
        if(good==null || !publicGood(good))return buyMessage(NO_GOODS,accrued);
        if(!state.optBoolean("roleCreated",false))throw new IOException("Gift claim needs a role");
        String fingerprint=sha256(setId+":"+shopId+":"+goodId+":"+count);
        String identity=requestKey(args);
        // The native time/sign fields are authentication data, not a request
        // nonce. With no explicit ID, rely on stock: a second one-copy claim
        // returns Sold Out, while a two-copy good can be bought twice. A true
        // retry of a multi-copy purchase is indistinguishable from a second
        // intentional purchase until the client sends unique request IDs.
        JSONObject ledger=identity==null?null:replay(state);
        JSONObject recorded=identity==null?null:ledger.optJSONObject(identity);
        if(recorded!=null){
            if(!fingerprint.equals(recorded.optString("fingerprint","")))
                throw new IOException("Conflicting gift retry");
            return new Action(VipSystem.withBuyResultExtra(Base64.decode(recorded.getString("response"),
                Base64.DEFAULT),state),accrued);
        }
        int used=used(state,set,shop,good,now);
        // A stale or double-clicked UI must receive a valid BuyResult so the
        // original controller can clear its pending state and refresh stock.
        // The transaction copy is unchanged and no loot is issued.
        if(count>limit(good)-used)return buyMessage(SOLD_OUT,accrued);
        if(inventoryCatalog==null)throw new IOException("Gift item catalog unavailable");
        LocalEconomy.init(state,inventoryCatalog);
        List<ProtoWire> loots=new ArrayList<ProtoWire>();
        if(monthCard(good)){
            if(count!=1)throw new IOException("Monthly card is single purchase");
            long cardId=good.getLong("monthCardId"),day=chinaDay(now);
            JSONObject all=cards(state);
            all.put(Long.toString(cardId),new JSONObject().put("startDay",day)
                .put("expiresDay",Math.addExact(day,good.getInt("days")))
                .put("lastGrantDay",Long.MIN_VALUE));
            state.put("giftMonthCards",all);
            advanceMonthCards(state,inventoryCatalog,now);
            loots.add(new ProtoWire().set(1,82).set(2,cardId).set(3,1).set(4,1));
        }else{
            loots.addAll(deliverPackage(state,inventoryCatalog,good.getLong("itemId"),count));
        }
        JSONObject claims=claims(state);
        claims.put(claimKey(setId,shopId,goodId),new JSONObject()
            .put("bucket",claimBucket(set,good,now)).put("count",used+(int)count));
        state.put("giftShopClaims",claims);
        if(!monthCard(good))
            state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
        long score=Math.multiplyExact(good.optLong("goodsScore",0),count);
        if(score<0)throw new IOException("Invalid archived gift score");
        if(score>0){
            LocalEconomy.addResource(state,"vipExp",0,score);
            LocalEconomy.addResource(state,"vipPoint",0,score);
            loots.add(new ProtoWire().set(1,20).set(3,score).set(4,score));
            loots.add(new ProtoWire().set(1,21).set(3,score).set(4,score));
        }
        // This is a virtual original-price counter for the free welfare
        // return page. It is never a payment, and never changes RealRmb.
        long cents=Math.multiplyExact(good.getLong("originalPrice"),count);
        if(cents<0)throw new IOException("Invalid archived gift value");
        LocalEconomy.addResource(state,"virtualPurchaseCents",0,cents);
        // shopmod.BuyResult: Result=1, Loots=5. The original purchase bundle
        // is server-opened, so this lists its actual Item.item_set_* rewards.
        ProtoWire resultWire=new ProtoWire().text(1,BUY_SUCCESS);
        for(ProtoWire loot:loots)resultWire.add(5,loot.bytes());
        byte[] result=VipSystem.withBuyResultExtra(resultWire.bytes(),state);
        if(identity!=null){
            ledger.put(identity,new JSONObject().put("fingerprint",fingerprint)
                .put("response",Base64.encodeToString(result,Base64.NO_WRAP)).put("at",now));
            trimReplay(ledger);state.put("giftShopReplay",ledger);
        }
        return new Action(result,true);
    }
}
