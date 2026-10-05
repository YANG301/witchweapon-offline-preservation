package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import org.json.JSONArray;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Run against the public Gift-tab products and both original month cards. */
public final class GiftShopSelfTest {
    private static void check(boolean truth,String message){if(!truth)throw new AssertionError(message);}
    private static Map<String,String> args(long set,long shop,long good,String id){
        Map<String,String> fields=new HashMap<String,String>();
        fields.put("setid",Long.toString(set));fields.put("shopid",Long.toString(shop));
        fields.put("goodsid",Long.toString(good));fields.put("count","1");
        fields.put("idempotency",id);return fields;
    }
    private static JSONObject player()throws Exception{
        return new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("gold",1000).put("rmb",0);
    }
    private static JSONObject monthlyMail(JSONObject save,long cardId,long day)throws Exception{
        JSONArray mailbox=save.optJSONArray("mailbox");
        if(mailbox==null)return null;
        JSONObject found=null;
        for(int i=0;i<mailbox.length();i++){
            JSONObject mail=mailbox.getJSONObject(i);
            if("monthCard".equals(mail.optString("source")) &&
                    mail.optLong("cardId")==cardId && mail.optLong("grantDay")==day){
                check(found==null,"Duplicate monthly mail for one card and China day");
                found=mail;
            }
        }
        return found;
    }
    private static int monthlyMailCount(JSONObject save,long cardId)throws Exception{
        JSONArray mailbox=save.optJSONArray("mailbox");
        if(mailbox==null)return 0;
        int count=0;
        for(int i=0;i<mailbox.length();i++)
            if(mailbox.getJSONObject(i).optLong("cardId")==cardId)count++;
        return count;
    }
    private static boolean publicPackage(long id){
        for(long visible:new long[]{45030285L,45030435L,45030619L,
                45030434L,45030301L,45030620L,45030621L})
            if(visible==id)return true;
        return false;
    }
    private static void checkVipExtra(byte[] response,JSONObject state)throws Exception {
        ProtoWire buy=ProtoWire.parse(response);
        ProtoWire extra=ProtoWire.parse(buy.data(4));
        check(extra.fields.size()==1&&extra.fields.get(0).number==100,
            "BuyResult field 4 must contain Actionmod.ExtraInfo.VipExtra field 100");
        ProtoWire vip=ProtoWire.parse(extra.data(100));
        long total=state.optLong("vipExp",0),points=state.optLong("vipPoint",0);
        check(vip.number(1,-1)==0&&vip.number(2,-1)==0&&
            vip.number(3,-1)==VipSystem.level(total)&&
            vip.number(4,-1)==VipSystem.progress(total)&&vip.number(5,-1)==points,
            "BuyResult VipExtra does not match the committed CAPH balances");
    }
    private static void expectLimit(GiftShop shop,JSONObject save,JSONObject catalog,
                                    Map<String,String> fields,long time)throws Exception {
        String original=save.toString();
        JSONObject expected=new JSONObject(original);
        shop.advanceMonthCards(expected,catalog,time);
        JSONObject attempted=new JSONObject(expected.toString());
        GiftShop.Action denied=shop.respond(attempted,catalog,"/shop/buy",fields,new byte[0],time);
        ProtoWire result=ProtoWire.parse(denied.response);
        check(!denied.changed && expected.toString().equals(attempted.toString()) &&
            original.equals(save.toString()),
            "Sold-out gift changed account inventory or revision");
        check("Sold Out".equals(new String(result.data(1),StandardCharsets.UTF_8)) &&
            result.data(5).length==0,"Sold-out gift did not return original BuyResult status");
    }
    private static ProtoWire findGift(ProtoWire all,long setId,long shopId,long goodId)throws Exception {
        for(ProtoWire.Field setField:all.fields)if(setField.number==1&&setField.type==2){
            ProtoWire set=ProtoWire.parse(setField.data);
            if(set.number(1,0)!=setId)continue;
            for(ProtoWire.Field shopField:set.fields)if(shopField.number==5&&shopField.type==2){
                ProtoWire shop=ProtoWire.parse(shopField.data);
                if(shop.number(1,0)!=shopId)continue;
                check(shop.number(4,0)==-1,
                    "Unlimited gift shelf must hide native daily counter");
                for(ProtoWire.Field goodField:shop.fields)if(goodField.number==2&&goodField.type==2){
                    ProtoWire good=ProtoWire.parse(goodField.data);
                    if(good.number(1,0)==goodId)return good;
                }
            }
        }
        throw new AssertionError("Gift absent from original shop protobuf");
    }
    private static void verifyAllOriginalPackages(GiftShop shop,JSONObject catalog,
                                                  byte[] seed,long today)throws Exception {
        JSONObject catalogFile=new JSONObject(new String(Files.readAllBytes(Paths.get(
            "D:/Project/魔女兵器在线版/legacy-server/resources/gift_shop_catalog.json")),
            StandardCharsets.UTF_8));
        JSONArray sets=catalogFile.getJSONArray("sets");
        int packageGoods=0;
        for(int si=0;si<sets.length();si++){
            JSONObject set=sets.getJSONObject(si);
            JSONArray shops=set.getJSONArray("shops");
            for(int pi=0;pi<shops.length();pi++){
                JSONObject shopDef=shops.getJSONObject(pi);
                JSONArray goods=shopDef.getJSONArray("goods");
                for(int gi=0;gi<goods.length();gi++){
                    JSONObject good=goods.getJSONObject(gi);
                    if(!"item".equals(good.getString("kind")))continue;
                    if(!publicPackage(good.getLong("id")))continue;
                    packageGoods++;
                    String box=Long.toString(good.getLong("itemId"));
                    JSONObject item=catalog.getJSONObject("items").getJSONObject(box);
                    check(item.getInt("item_type")==9&&item.getInt("item_sub_type")==5,
                        "Original Gift good changed from hidden bundle: "+box);
                    JSONArray rewards=item.getJSONArray("rewards");
                    JSONObject save=player();LocalEconomy.init(save,catalog);
                    JSONObject before=new JSONObject(save.toString());
                    Map<String,String> fields=args(set.getLong("id"),shopDef.getLong("id"),
                        good.getLong("id"),"every-package-"+packageGoods);
                    GiftShop.Action delivered=shop.respond(save,catalog,"/shop/buy",fields,seed,today);
                    check(delivered.changed,"Gift did not commit: "+good.getLong("id"));
                    checkVipExtra(delivered.response,save);
                    check(save.getJSONObject("items").optLong(box,0)==0,
                        "Hidden outer package still in backpack: "+box);
                    ProtoWire result=ProtoWire.parse(delivered.response);
                    int lootIndex=0,extraLoot=0;
                    for(ProtoWire.Field field:result.fields){
                        if(field.number!=5||field.type!=2)continue;
                        if(lootIndex==rewards.length()){
                            ProtoWire extra=ProtoWire.parse(field.data);
                            long score=good.getLong("goodsScore");
                            check(score>0&&extraLoot<2&&extra.number(1,-1)==20+extraLoot&&
                                extra.number(3,-1)==score&&extra.number(4,-1)==score,
                                "BuyResult has unexpected score loot");
                            extraLoot++;
                            continue;
                        }
                        JSONObject reward=rewards.getJSONObject(lootIndex++);
                        int type=reward.getInt("type");long id=reward.getLong("id");
                        long rawValue=reward.getLong("value"),rawCount=reward.getLong("count");
                        long amount=rawCount>0?rawCount:rawValue;
                        ProtoWire loot=ProtoWire.parse(field.data);
                        check(loot.number(1,-1)==type&&loot.number(2,-1)==id&&
                            loot.number(3,-1)==(type==81?rawValue:amount)&&
                            loot.number(4,-1)==(type==3?amount:1),
                            "BuyResult disagrees with original item_set: "+box+" #"+lootIndex);
                        if(type==3){
                            String key=Long.toString(id);
                            JSONObject received=catalog.getJSONObject("items").getJSONObject(key);
                            check(!(received.optInt("item_type")==9&&
                                received.optInt("item_sub_type")==5),
                                "Original gift nests an invisible box: "+box+" -> "+key);
                            check(save.getJSONObject("items").optLong(key,0)==
                                before.getJSONObject("items").optLong(key,0)+amount,
                                "Item not credited: "+box+" -> "+key);
                        }else if(type==12||type==13||type==99){
                            String name=type==12?"stamina":type==13?"gold":"rmb";
                            long initial=type==12?200:type==13?1000000:100000;
                            check(save.optLong(name,initial)==before.optLong(name,initial)+amount,
                                "Resource not credited: "+box+" -> "+name);
                        }else if(type==81){
                            check(save.getJSONObject("roleUnlocks").getJSONObject("2")
                                .optBoolean(Long.toString(rawValue),false),
                                "Cosmetic unlock not credited: "+box);
                        }else throw new AssertionError("Unsupported original reward type "+type);
                    }
                    check(lootIndex==rewards.length()&&extraLoot==(good.getLong("goodsScore")>0?2:0),
                        "BuyResult missing original item_set or score loot: "+box);
                    String once=save.toString();
                    check(!shop.respond(save,catalog,"/shop/buy",fields,seed,today).changed&&
                        once.equals(save.toString()),"Gift replay mutated inventory: "+box);
                    if(good.getInt("originalLimit")==1)
                        expectLimit(shop,save,catalog,args(set.getLong("id"),shopDef.getLong("id"),
                            good.getLong("id"),"another-"+packageGoods),today);
                }
            }
        }
        check(packageGoods==7,"Expected seven public original package goods");
    }
    private static void verifyVipExtraAndReplay(GiftShop shop,JSONObject catalog,
                                                byte[] seed,long today)throws Exception {
        JSONObject save=player();
        Map<String,String> normal=args(44000022,4502990008L,45820001,"vip-normal");
        GiftShop.Action first=shop.respond(save,catalog,"/shop/buy",normal,seed,today);
        check(first.changed&&save.optLong("vipExp")==690&&save.optLong("vipPoint")==690,
            "Normal monthly card did not commit its CAPH score exactly once");
        checkVipExtra(first.response,save);
        Map<String,String> special=args(44000022,4502990008L,45820006,"vip-special");
        GiftShop.Action second=shop.respond(save,catalog,"/shop/buy",special,seed,today);
        check(second.changed&&save.optLong("vipExp")==2944&&save.optLong("vipPoint")==2944&&
            VipSystem.level(save.optLong("vipExp"))==1&&
            VipSystem.progress(save.optLong("vipExp"))==1944,
            "Both zero-price cards must cross one CAPH level without duplicate points");
        checkVipExtra(second.response,save);
        String committed=save.toString();
        GiftShop.Action replay=shop.respond(save,catalog,"/shop/buy",normal,seed,today);
        check(!replay.changed&&committed.equals(save.toString()),
            "Explicit monthly retry changed committed CAPH score or points");
        checkVipExtra(replay.response,save);
        check(!Arrays.equals(first.response,replay.response)&&
            Arrays.equals(ProtoWire.parse(first.response).clear(4).bytes(),
                ProtoWire.parse(replay.response).clear(4).bytes()),
            "Retry must preserve the original result and loots but refresh VipExtra");
    }
    private static void verifyLegacyMigration(GiftShop shop,JSONObject catalog,long today)
            throws Exception {
        JSONObject old=player();LocalEconomy.init(old,catalog);
        JSONObject bag=old.getJSONObject("items"),claims=new JSONObject();
        long[][] bought={
            {44000025,4502990011L,45030619,40940027},
            {44000006,4502990002L,45030639,40950096},
            {44000006,4502990002L,45030620,40940028},
            {44000006,4502500025L,45030460,40950076},
            {44000061,4502990023L,45030431,40930019}
        };
        for(long[] good:bought){
            claims.put(good[0]+":"+good[1]+":"+good[2],
                new JSONObject().put("bucket",0).put("count",1));
            bag.put(Long.toString(good[3]),1);
        }
        bag.put("40940009",1); // A hidden box without this account's shop claim.
        old.put("giftShopClaims",claims);
        check(shop.advanceMonthCards(old,catalog,today),"Legacy claimed boxes were not migrated");
        for(long[] good:bought)
            check(bag.optLong(Long.toString(good[3]),0)==0,
                "Previously claimed hidden box was not consumed: "+good[3]);
        check(bag.optLong("40940009",0)==1,"Unclaimed old box was converted");
        check(bag.optLong("40350003",0)==29 && bag.optLong("40350013",0)==50,
            "Original visible item rewards not fully credited to gh-style save");
        check(old.optLong("rmb")==716&&old.optLong("gold")==71000,
            "Original currency rewards not credited to gh-style save");
        check(old.getJSONObject("roleUnlocks").getJSONObject("2").optBoolean("15"),
            "Original cosmetic reward not credited to gh-style save");
        String migrated=old.toString();
        check(!shop.advanceMonthCards(old,catalog,today)&&migrated.equals(old.toString()),
            "Legacy migration must run exactly once");
        bag.put("40940027",1); // Another-source box after the migration snapshot.
        check(!shop.advanceMonthCards(old,catalog,today)&&bag.optLong("40940027")==1,
            "Later unrelated box was mistaken for an old shop claim");

        JSONObject monthly=player();LocalEconomy.init(monthly,catalog);
        JSONObject monthlyBag=monthly.getJSONObject("items");
        monthlyBag.put("40950003",1).put("40950029",1);
        long day=Math.floorDiv(today+28800L,86400L);
        monthly.put("giftShopClaims",new JSONObject()
            .put("44000022:4502990008:45820001",new JSONObject().put("bucket",0).put("count",1))
            .put("44000022:4502990008:45820006",new JSONObject().put("bucket",0).put("count",1)));
        monthly.put("giftMonthCards",new JSONObject()
            .put("1",new JSONObject().put("startDay",day-1).put("expiresDay",day+29)
                .put("lastGrantDay",day))
            .put("6",new JSONObject().put("startDay",day-1).put("expiresDay",day+14)
                .put("lastGrantDay",day)));
        check(shop.advanceMonthCards(monthly,catalog,today),
            "Legacy claimed monthly chests were not migrated");
        check(monthlyBag.optLong("40950003",0)==0&&monthlyBag.optLong("40950029",0)==0&&
            monthlyBag.optLong("40330001",0)==5&&monthlyBag.optLong("40510003",0)==1&&
            monthly.optLong("rmb")==20&&monthly.optLong("gold")==21000,
            "Legacy monthly chest contents were not credited");
        check(!shop.advanceMonthCards(monthly,catalog,today),
            "Legacy monthly chest migrated more than once");
        check(shop.advanceMonthCards(monthly,catalog,today+86400L)&&
            monthlyBag.optLong("40330001",0)==5&&monthlyBag.optLong("40510003",0)==1&&
            monthlyMail(monthly,1,day+1)!=null&&monthlyMail(monthly,6,day+1)!=null,
            "Next-day legacy month cards did not switch to mail");

        JSONObject full=player();LocalEconomy.init(full,catalog);
        full.getJSONObject("items").put("40330001",9999);
        full.put("giftMonthCards",new JSONObject().put("1",new JSONObject()
            .put("startDay",day-1).put("expiresDay",day+29)
            .put("lastGrantDay",day-1)));
        check(shop.advanceMonthCards(full,catalog,today)&&
            full.getJSONObject("items").optLong("40330001")==9999&&
            full.getJSONObject("giftMonthCards").getJSONObject("1")
                .optLong("lastGrantDay")==day&&monthlyMail(full,1,day)!=null,
            "Full item stack must not prevent the monthly mail");
        full.put("legacyRoleId",123L);
        Map<String,String> claim=new HashMap<String,String>();
        claim.put("roleid","123");
        claim.put("mailids",monthlyMail(full,1,day).getString("id"));
        JSONObject attempted=new JSONObject(full.toString());
        boolean blocked=false;
        try{LocalMail.respond(attempted,catalog,"/mail/getAttachAndDelete",claim,
            Math.multiplyExact(today,1000L));}
        catch(java.io.IOException expected){blocked=expected.getMessage().contains("stack capacity");}
        check(blocked&&monthlyMail(full,1,day)!=null&&
            full.getJSONObject("items").optLong("40330001")==9999,
            "Full bag should keep monthly mail claimable");
        full.getJSONObject("items").put("40330001",9994);
        LocalMail.respond(full,catalog,"/mail/getAttachAndDelete",claim,
            Math.multiplyExact(today,1000L));
        check(!shop.advanceMonthCards(full,catalog,today)&&
            full.getJSONObject("items").optLong("40330001")==9999&&
            full.getJSONObject("giftMonthCards").getJSONObject("1")
                .optLong("lastGrantDay")==day&&monthlyMail(full,1,day)==null,
            "Monthly mail claim did not credit after space was freed");
    }
    private static void verifySerializedDoubleClick(JSONObject catalog,byte[] seed)throws Exception {
        Path directory=Files.createTempDirectory("gift-shop-double-click-");
        ExecutorService pool=Executors.newFixedThreadPool(2);
        try{
            JSONObject original=player().put("version",1).put("name","shop-test")
                .put("stamina",200).put("exp",0);
            Files.write(directory.resolve("offline_save_v1.json"),
                original.toString().getBytes(StandardCharsets.UTF_8));
            final LocalSave account=new LocalSave(directory.toFile());
            final CountDownLatch start=new CountDownLatch(1);
            final Map<String,String> first=args(44000025,4502990011L,45030285,"parallel-1");
            final Map<String,String> second=args(44000025,4502990011L,45030285,"parallel-2");
            Callable<byte[]> a=()->{start.await();return account.respond("/shop/buy",first,seed,catalog);};
            Callable<byte[]> b=()->{start.await();return account.respond("/shop/buy",second,seed,catalog);};
            Future<byte[]> left=pool.submit(a),right=pool.submit(b);
            start.countDown();
            byte[] leftResult=left.get(),rightResult=right.get();
            String leftStatus=new String(ProtoWire.parse(leftResult).data(1),StandardCharsets.UTF_8);
            String rightStatus=new String(ProtoWire.parse(rightResult).data(1),StandardCharsets.UTF_8);
            check(("Buy Success".equals(leftStatus)&&"Sold Out".equals(rightStatus))||
                ("Sold Out".equals(leftStatus)&&"Buy Success".equals(rightStatus)),
                "Two simultaneous claims did not serialize to one success and one sold out");
            JSONObject persisted=new JSONObject(new String(Files.readAllBytes(
                directory.resolve("offline_save_v1.json")),StandardCharsets.UTF_8));
            check(persisted.getJSONObject("items").optLong("40350003")==2 &&
                persisted.getJSONObject("giftShopClaims").getJSONObject(
                    "44000025:4502990011:45030285").optInt("count")==1,
                "Concurrent claims credited more than one package");
            Map<String,String> winner="Buy Success".equals(leftStatus)?first:second;
            byte[] replay=account.respond("/shop/buy",winner,seed,catalog);
            check(Arrays.equals(replay,"Buy Success".equals(leftStatus)?leftResult:rightResult),
                "Same request ID did not replay its original response");
            ProtoWire current=ProtoWire.parse(account.respond("/shop/getSetData",
                new HashMap<String,String>(),seed,catalog));
            check(findGift(current,44000025,4502990011L,45030285).number(3,-1)==0,
                "Stock lookup after a double-click did not show zero immediately");
        }finally{
            pool.shutdownNow();
            try(java.util.stream.Stream<Path> files=Files.list(directory)){
                files.forEach(path->{try{Files.deleteIfExists(path);}catch(Exception ignored){}});
            }
            Files.deleteIfExists(directory);
        }
    }
    private static void verifyMailFetchAccrual(JSONObject catalog)throws Exception {
        Path directory=Files.createTempDirectory("monthcard-mail-fetch-");
        try{
            long day=Math.floorDiv(System.currentTimeMillis()/1000L+28800L,86400L);
            JSONObject save=player().put("version",1).put("name","mail-fetch-test")
                .put("legacyRoleId",123L).put("stamina",200).put("exp",0)
                .put("giftMonthCards",new JSONObject().put("1",new JSONObject()
                    .put("startDay",day-1).put("expiresDay",day+29)
                    .put("lastGrantDay",day-1)));
            Files.write(directory.resolve("offline_save_v1.json"),
                save.toString().getBytes(StandardCharsets.UTF_8));
            LocalSave account=new LocalSave(directory.toFile());
            byte[] first=account.respond("/mail/fetch",new HashMap<String,String>(),
                new byte[0],catalog);
            ProtoWire fetched=ProtoWire.parse(first);
            check(fetched.fields.size()==1&&fetched.fields.get(0).number==2,
                "Mail fetch did not queue due month-card mail in the original wire field");
            JSONObject persisted=new JSONObject(new String(Files.readAllBytes(
                directory.resolve("offline_save_v1.json")),StandardCharsets.UTF_8));
            check(monthlyMail(persisted,1,day)!=null&&monthlyMailCount(persisted,1)==1,
                "Mail fetch did not persist the daily reward");
            check(Arrays.equals(first,account.respond("/mail/fetch",new HashMap<String,String>(),
                new byte[0],catalog)),"Repeat fetch changed the month-card mailbox");
        }finally{
            try(java.util.stream.Stream<Path> files=Files.list(directory)){
                files.forEach(path->{try{Files.deleteIfExists(path);}catch(Exception ignored){}});
            }
            Files.deleteIfExists(directory);
        }
    }
    public static void main(String[] argv)throws Exception {
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(
            "D:/Project/魔女兵器在线版/legacy-server/resources/offline_responses.json")),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        byte[] seed=Base64.decode(responses.getJSONObject("/shop/allShopSet").getString("base64"),Base64.DEFAULT);
        GiftShop shop=GiftShop.bundled();
        long today=1790380800L; // Stable China-calendar boundary tests use these virtual seconds.
        verifySerializedDoubleClick(catalog,seed);
        verifyMailFetchAccrual(catalog);
        verifyAllOriginalPackages(shop,catalog,seed,today);
        verifyVipExtraAndReplay(shop,catalog,seed,today);
        verifyLegacyMigration(shop,catalog,today);
        JSONObject unknownCatalog=new JSONObject(catalog.toString());
        unknownCatalog.getJSONObject("items").getJSONObject("40940027")
            .getJSONArray("rewards").getJSONObject(0).put("type",777);
        boolean refused=false;
        try{shop.respond(player(),unknownCatalog,"/shop/buy",
            args(44000025,4502990011L,45030619,"unknown-reward"),seed,today);}
        catch(java.io.IOException expected){refused=expected.getMessage().contains("Unsupported original gift reward type");}
        check(refused,"Unknown future gift rewards must fail closed");
        JSONObject a=player(),b=player();
        ProtoWire all=ProtoWire.parse(shop.respond(a,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),seed,today).response);
        check(all.number(2,1)==0,"Payments must be disabled");
        ProtoWire daily=findGift(all,44000025L,4502990011L,45030285L);
        check(daily.number(2,-1)==0&&daily.number(3,-1)==1,"Daily gift must be free and available");
        check(findGift(all,44000088L,4502990006L,45030434L).number(3,-1)==2,
            "Weekly original quantity missing");
        ProtoWire month=findGift(all,44000022L,4502990008L,45820001L);
        check(month.number(2,-1)==0 && month.number(3,-1)==1,
            "Original monthly-card page must be visible and free");
        check(findGift(all,44000022L,4502990008L,45820006L).number(3,-1)==1,
            "Advanced monthly card must be purchasable without an activity flag");
        Map<String,String> day1=args(44000025,4502990011L,45030285,"daily-one");
        GiftShop.Action award=shop.respond(a,catalog,"/shop/buy",day1,seed,today);
        check(award.changed,"First claim must mutate account");
        ProtoWire buy=ProtoWire.parse(award.response);
        check("Buy Success".equals(new String(buy.data(1),StandardCharsets.UTF_8)),
            "BuyResult must use original client's exact success status");
        ProtoWire item=ProtoWire.parse(buy.data(5));
        check(item.number(1,0)==3&&item.number(2,0)==40350003L&&item.number(4,0)==2,
            "Original package contents not delivered");
        check(a.getJSONObject("items").optLong("40950044")==0&&
            a.getJSONObject("items").optLong("40350003")==2,
            "Gift contents missing or hidden outer box retained");
        GiftShop.Action replay=shop.respond(a,catalog,"/shop/buy",day1,seed,today);
        check(!replay.changed && Arrays.equals(award.response,replay.response),
            "Retry must replay the same result without a second item");
        expectLimit(shop,a,catalog,args(44000025,4502990011L,45030285,"daily-two"),today);
        check(findGift(ProtoWire.parse(shop.respond(a,catalog,"/shop/getSetData",
            new HashMap<String,String>(),seed,today).response),44000025L,4502990011L,45030285L)
            .number(3,-1)==0,"Claimed daily gift still shown available");
        check(findGift(ProtoWire.parse(shop.respond(b,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),seed,today).response),44000025L,4502990011L,45030285L)
            .number(3,-1)==1,"Gift stock leaked between accounts");
        shop.respond(a,catalog,"/shop/buy",args(44000025,4502990011L,45030285,"tomorrow"),seed,today+86400);
        check(a.getJSONObject("items").optLong("40350003")==4,"Daily reset did not grant contents");
        // Weekly two-claim product, then next China-calendar week.
        shop.respond(a,catalog,"/shop/buy",args(44000088,4502990006L,45030434,"weekly-1"),seed,today);
        check(findGift(ProtoWire.parse(shop.respond(a,catalog,"/shop/getSetData",
            new HashMap<String,String>(),seed,today).response),44000088,4502990006L,45030434)
            .number(3,-1)==1,"Weekly stock did not refresh after first purchase");
        shop.respond(a,catalog,"/shop/buy",args(44000088,4502990006L,45030434,"weekly-2"),seed,today);
        expectLimit(shop,a,catalog,args(44000088,4502990006L,45030434,"weekly-3"),today);
        check(findGift(ProtoWire.parse(shop.respond(a,catalog,"/shop/getSetData",
            new HashMap<String,String>(),seed,today).response),44000088,4502990006L,45030434)
            .number(3,-1)==0,"Weekly stock did not refresh after second purchase");
        shop.respond(a,catalog,"/shop/buy",args(44000088,4502990006L,45030434,"weekly-next"),seed,today+8*86400L);
        check(a.optLong("rmb")==300,"Weekly stock reset failed");
        // An original num=0 product has a nostalgia-server one/day free cap.
        shop.respond(a,catalog,"/shop/buy",args(44000006,4502990002L,45030620,"unlimited-1"),seed,today);
        expectLimit(shop,a,catalog,args(44000006,4502990002L,45030620,"unlimited-2"),today);
        shop.respond(a,catalog,"/shop/buy",args(44000006,4502990002L,45030620,"unlimited-next"),seed,today+86400);
        check(a.getJSONObject("items").optLong("40350013")==100,
            "Unlimited-free daily cap reset failed");
        // The original type-82 goods map to monthcard.txt: ID 1 grants
        // 30 days of daily chest 40950003; ID 6 grants 15 days of 40950029.
        JSONObject monthly=player();
        Map<String,String> firstCard=args(44000022,4502990008L,45820001,"monthly-1");
        GiftShop.Action activated=shop.respond(monthly,catalog,"/shop/buy",firstCard,seed,today);
        check(activated.changed,"Monthly activation must change the save");
        ProtoWire cardLoot=ProtoWire.parse(ProtoWire.parse(activated.response).data(5));
        check(cardLoot.number(1,0)==82 && cardLoot.number(2,0)==1,
            "Monthly activation did not return the original card type");
        long day=Math.floorDiv(today+28800L,86400L);
        check(monthly.getJSONObject("items").optLong("40950003")==0&&
            monthly.getJSONObject("items").optLong("40330001")==0&&
            monthly.optLong("rmb")==0&&monthlyMailCount(monthly,1)==1,
            "Monthly purchase must queue one mail without direct inventory credit");
        JSONObject firstMail=monthlyMail(monthly,1,day);
        JSONArray firstAttachments=firstMail.getJSONArray("attachments");
        check(firstAttachments.length()==3&&
            firstAttachments.getJSONObject(0).getInt("type")==3&&
            firstAttachments.getJSONObject(0).getLong("id")==40330001&&
            firstAttachments.getJSONObject(0).getLong("count")==5&&
            firstAttachments.getJSONObject(1).getInt("type")==98&&
            firstAttachments.getJSONObject(1).getLong("count")==20&&
            firstAttachments.getJSONObject(2).getInt("type")==13&&
            firstAttachments.getJSONObject(2).getLong("count")==10000,
            "Normal monthly mail does not contain the original daily chest rewards");
        ProtoWire fetched=ProtoWire.parse(LocalMail.respond(monthly,catalog,"/mail/fetch",
            new HashMap<String,String>(),Math.multiplyExact(today,1000L)).response);
        check(fetched.fields.size()==1&&fetched.fields.get(0).number==2,
            "Original client must see monthly rewards as claimable special mail");
        ProtoWire role=new ProtoWire();shop.monthCardRole(role,monthly,today);
        check(role.integers(6).size()==13 && role.integers(6).get(0)==30 &&
            role.integers(7).get(0)==1,"Original month-card role fields missing");
        check(!shop.respond(monthly,catalog,"/shop/buy",firstCard,seed,today).changed,
            "Monthly retry delivered twice");
        expectLimit(shop,monthly,catalog,args(44000022,4502990008L,45820001,
            "monthly-still-active"),today+86400L);
        expectLimit(shop,monthly,catalog,args(44000022,4502990008L,45820001,
            "monthly-next-month-active"),today+5*86400L);
        check(shop.advanceMonthCards(monthly,catalog,today+86400L),
            "Next-day monthly chest not sent");
        check(!shop.advanceMonthCards(monthly,catalog,today+86400L) &&
            monthlyMailCount(monthly,1)==2&&monthlyMail(monthly,1,day+1)!=null&&
            monthly.getJSONObject("items").optLong("40330001")==0,
            "Monthly mail sent twice in a day or credited directly");
        shop.monthCardRole(role,monthly,today+86400L);
        check(role.integers(6).get(0)==29 && role.integers(7).get(0)==1,
            "Monthly remaining days did not decrease");
        // Offline days are queued exactly once when the account next appears.
        check(shop.advanceMonthCards(monthly,catalog,today+4*86400L) &&
            monthlyMailCount(monthly,1)==5&&
            monthlyMail(monthly,1,day+2)!=null&&monthlyMail(monthly,1,day+4)!=null,
            "Offline month-card days were not caught up");
        check(shop.advanceMonthCards(monthly,catalog,today+30*86400L)&&
            monthlyMailCount(monthly,1)==30&&monthlyMail(monthly,1,day+29)!=null&&
            monthlyMail(monthly,1,day+30)==null,
            "Expired month card must catch up only its thirty entitled days");
        check(!shop.advanceMonthCards(monthly,catalog,today+30*86400L),
            "Repeated expired-card catch-up duplicated mail");
        shop.respond(monthly,catalog,"/shop/buy",args(44000022,4502990008L,
            45820001,"monthly-renewed"),seed,today+30*86400L);
        check(monthlyMailCount(monthly,1)==31&&monthlyMail(monthly,1,day+30)!=null&&
            monthly.getJSONObject("items").optLong("40330001")==0,
            "Free monthly renewal after expiry did not queue current-day mail");
        shop.respond(monthly,catalog,"/shop/buy",args(44000022,4502990008L,
            45820006,"special-card"),seed,today);
        check(monthly.getJSONObject("items").optLong("40950029")==0&&
            monthly.getJSONObject("items").optLong("40510003")==0&&
            monthly.getJSONObject("items").optLong("40350003")==0&&
            monthlyMailCount(monthly,6)==1&&
            monthlyMail(monthly,6,day).getJSONArray("attachments").length()==4,
            "Advanced 15-day card did not queue its original daily rewards");
        expectLimit(shop,monthly,catalog,args(44000022,4502990008L,45820006,
            "special-again"),today+86400L);
        shop.advanceMonthCards(monthly,catalog,today+15*86400L);
        check(monthlyMailCount(monthly,6)==15&&
            findGift(ProtoWire.parse(shop.respond(monthly,catalog,"/shop/getSetData",
            new HashMap<String,String>(),seed,today+15*86400L).response),
            44000022L,4502990008L,45820006L).number(3,-1)==1,
            "Advanced card must be available again after its fifteen-day term");
        shop.respond(monthly,catalog,"/shop/buy",args(44000022,4502990008L,
            45820006,"special-renewed"),seed,today+15*86400L);
        check(monthlyMailCount(monthly,6)==16&&monthlyMail(monthly,6,day+15)!=null,
            "Advanced monthly renewal did not queue the new first-day mail");
        monthly.put("legacyRoleId",123L);
        Map<String,String> normalClaim=new HashMap<String,String>();
        normalClaim.put("roleid","123");
        normalClaim.put("mailids",firstMail.getString("id"));
        LocalMail.respond(monthly,catalog,"/mail/getAttachAndDelete",normalClaim,
            Math.multiplyExact(today,1000L));
        check(monthlyMail(monthly,1,day)==null&&
            monthly.getJSONObject("items").optLong("40330001")==5&&
            monthly.optLong("rmb")==20&&monthly.optLong("gold")==11000,
            "Normal monthly reward did not enter the bag only after mail claim");
        LocalMail.respond(monthly,catalog,"/mail/getAttachAndDelete",normalClaim,
            Math.multiplyExact(today,1000L));
        check(monthly.getJSONObject("items").optLong("40330001")==5,
            "Repeated mail claim credited normal monthly reward twice");
        Map<String,String> advancedClaim=new HashMap<String,String>();
        advancedClaim.put("roleid","123");
        advancedClaim.put("mailids",monthlyMail(monthly,6,day).getString("id"));
        LocalMail.respond(monthly,catalog,"/mail/getAttachAndDelete",advancedClaim,
            Math.multiplyExact(today,1000L));
        check(monthly.getJSONObject("items").optLong("40510003")==1&&
            monthly.getJSONObject("items").optLong("40350003")==1&&
            monthly.getJSONObject("items").optLong("40240039")==15&&
            monthly.optLong("gold")==21000,
            "Advanced monthly reward did not enter the bag after mail claim");
        long october1=Math.subtractExact(Math.multiplyExact(
            java.time.LocalDate.of(2026,10,1).toEpochDay(),86400L),28800L);
        JSONObject sameMonth=player();
        Map<String,String> advanced=args(44000022,4502990008L,45820006,"october-card");
        check(shop.respond(sameMonth,catalog,"/shop/buy",advanced,seed,october1).changed,
            "Advanced card could not be bought without the old activity flag");
        expectLimit(shop,sameMonth,catalog,args(44000022,4502990008L,45820006,
            "october-repeat"),october1+16*86400L);
        check(shop.advanceMonthCards(sameMonth,catalog,october1+31*86400L)&&
            monthlyMailCount(sameMonth,6)==15,
            "Advanced card did not catch up its whole term after month end");
        check(findGift(ProtoWire.parse(shop.respond(sameMonth,catalog,"/shop/getSetData",
            new HashMap<String,String>(),seed,october1+31*86400L).response),
            44000022L,4502990008L,45820006L).number(3,-1)==1,
            "Expired advanced card must become available in the next China month");
        JSONObject pending=player();
        shop.respond(pending,catalog,"/shop/buy",args(44000022,4502990008L,
            45820006,"pending-old"),seed,october1);
        JSONArray fullMailbox=new JSONArray();
        fullMailbox.put(monthlyMail(pending,6,
            Math.floorDiv(october1+28800L,86400L)));
        for(int i=0;i<199;i++)fullMailbox.put(new JSONObject()
            .put("id",Long.toString(2000+i)).put("attachments",new JSONArray()));
        pending.put("mailbox",fullMailbox);
        check(!shop.advanceMonthCards(pending,catalog,october1+31*86400L)&&
            monthlyMailCount(pending,6)==1,
            "Full mailbox must leave older advanced-card days pending");
        expectLimit(shop,pending,catalog,args(44000022,4502990008L,45820006,
            "pending-renew"),october1+31*86400L);
        pending.put("mailbox",new JSONArray().put(fullMailbox.getJSONObject(0)));
        check(shop.advanceMonthCards(pending,catalog,october1+31*86400L)&&
            monthlyMailCount(pending,6)==15,
            "Pending older card mail was not caught up after mailbox space opened");
        check(shop.respond(pending,catalog,"/shop/buy",args(44000022,4502990008L,
            45820006,"pending-renew"),seed,october1+31*86400L).changed&&
            monthlyMailCount(pending,6)==16,
            "Completed older card mail did not permit next-month renewal");
        check(findGift(ProtoWire.parse(shop.respond(b,catalog,"/shop/allShopSet",
            new HashMap<String,String>(),seed,today).response),44000022L,4502990008L,45820001L)
            .number(3,-1)==1,"Monthly-card availability leaked between accounts");
        JSONObject nativeSave=player();
        Map<String,String> nativeBuy=args(44000088,4502990006L,45030434,"unused");
        nativeBuy.remove("idempotency");
        check(shop.respond(nativeSave,catalog,"/shop/buy",nativeBuy,seed,today).changed,
            "Native four-field gift form was rejected");
        check(shop.respond(nativeSave,catalog,"/shop/buy",nativeBuy,seed,today).changed &&
            nativeSave.optLong("rmb")==200,
            "Native second purchase of a two-copy good was mistaken for a retry");
        expectLimit(shop,nativeSave,catalog,nativeBuy,today);
        check(GiftShop.giftPurchase(nativeBuy) &&
            !GiftShop.giftPurchase(args(44000001,4501010003L,45030124,"supply")),
            "Existing offline supply route must remain separate");
        JSONObject missingPlayer=player();
        shop.advanceMonthCards(missingPlayer,catalog,today);
        GiftShop.Action missing=shop.respond(missingPlayer,catalog,"/shop/buy",
            args(44000025,4502990011L,99999999,"missing-good"),seed,today);
        check(!missing.changed && "No This Goods".equals(new String(
            ProtoWire.parse(missing.response).data(1),StandardCharsets.UTF_8)),
            "Unknown gift must return the original no-goods status");
        JSONObject signedSave=player();
        Map<String,String> signed=args(44000025,4502990011L,45030435,"unused");
        signed.remove("idempotency");signed.put("time","1790380800000");
        signed.put("sign","0123456789abcdef0123456789abcdef");
        GiftShop.Action signedFirst=shop.respond(signedSave,catalog,"/shop/buy",signed,seed,today);
        String signedOnce=signedSave.toString();
        GiftShop.Action signedRetry=shop.respond(signedSave,catalog,"/shop/buy",signed,seed,today);
        ProtoWire signedRetryWire=ProtoWire.parse(signedRetry.response);
        check(signedFirst.changed && !signedRetry.changed && signedOnce.equals(signedSave.toString()) &&
            "Buy Success".equals(new String(ProtoWire.parse(signedFirst.response).data(1),
                StandardCharsets.UTF_8)) &&
            "Sold Out".equals(new String(signedRetryWire.data(1),StandardCharsets.UTF_8)) &&
            signedRetryWire.data(5).length==0,
            "No-ID single-copy retry must be sold out without local stock decrement or new loot");
        JSONObject signedWeekly=player();
        Map<String,String> sharedSignature=args(44000088,4502990006L,45030434,"unused");
        sharedSignature.remove("idempotency");
        sharedSignature.put("time","1790380800000");
        sharedSignature.put("sign","0123456789abcdef0123456789abcdef");
        check(shop.respond(signedWeekly,catalog,"/shop/buy",sharedSignature,seed,today).changed &&
            shop.respond(signedWeekly,catalog,"/shop/buy",sharedSignature,seed,today).changed &&
            signedWeekly.optLong("rmb")==200,
            "Shared native time/sign incorrectly suppressed a legitimate second purchase");
        expectLimit(shop,signedWeekly,catalog,sharedSignature,today);
        check(!GiftShop.handles("/shop/createOrder")&&!GiftShop.handles("/shop/checkPayment"),
            "Payment route must remain disconnected");
        System.out.println("GiftShopSelfTest passed: public gift purchases, both monthly cards, mail accrual/claim/catch-up, retries, and legacy migration");
    }
}
