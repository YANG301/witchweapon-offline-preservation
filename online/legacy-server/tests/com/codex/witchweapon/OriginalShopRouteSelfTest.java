package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

/** Exercises real LocalSave shop routing, persistence and concurrent clicks. */
public final class OriginalShopRouteSelfTest {
    private static int checks;
    private static void check(boolean okay,String message){
        checks++;
        if(!okay)throw new AssertionError(message);
    }
    private static Map<String,String> buy(String id){
        Map<String,String> fields=new HashMap<String,String>();
        fields.put("setid","44000070");fields.put("shopid","4501500009");
        fields.put("goodsid","45030168");fields.put("count","2");
        fields.put("idempotency",id);
        return fields;
    }
    private static String status(byte[] result)throws Exception{
        return new String(ProtoWire.parse(result).data(1),StandardCharsets.UTF_8);
    }
    private static void initial(Path dir,long role)throws Exception{
        Files.createDirectories(dir);
        JSONObject save=new JSONObject().put("version",1).put("roleCreated",true)
            .put("legacyRoleId",role).put("starterProfile",1).put("name","shop-test")
            .put("gold",1000).put("rmb",100).put("stamina",200).put("exp",0);
        Files.write(dir.resolve("offline_save_v1.json"),
            save.toString().getBytes(StandardCharsets.UTF_8));
    }
    private static JSONObject persisted(Path dir)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(
            dir.resolve("offline_save_v1.json")),StandardCharsets.UTF_8));
    }
    public static void main(String[] args)throws Exception{
        JSONObject fixtures=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),
            StandardCharsets.UTF_8));
        JSONObject catalog=fixtures.getJSONObject("_catalog");
        byte[] seed=Base64.decode(fixtures.getJSONObject("/shop/allShopSet")
            .getString("base64"),Base64.DEFAULT);
        Path directory=Files.createTempDirectory("original-shop-route-");
        ExecutorService pool=Executors.newFixedThreadPool(2);
        try{
            Path a=directory.resolve("a"),b=directory.resolve("b");
            initial(a,11);initial(b,12);
            final LocalSave first=new LocalSave(a.toFile());
            final CountDownLatch start=new CountDownLatch(1);
            Callable<byte[]> left=()->{start.await();return first.respond(
                "/shop/buy",buy("click-1"),seed,catalog);};
            Callable<byte[]> right=()->{start.await();return first.respond(
                "/shop/buy",buy("click-2"),seed,catalog);};
            Future<byte[]> f1=pool.submit(left),f2=pool.submit(right);
            start.countDown();
            String s1=status(f1.get()),s2=status(f2.get());
            check(("Buy Success".equals(s1)&&"Sold Out".equals(s2))||
                  ("Sold Out".equals(s1)&&"Buy Success".equals(s2)),
                "Concurrent purchases must serialize to one original success");
            JSONObject save=persisted(a);
            check(save.getLong("rmb")==80,"Only one debit persisted");
            check(save.getJSONObject("items").getLong("40130022")==2,
                "Only one original item reward persisted");
            check(save.getJSONObject("originalShopClaims").getJSONObject(
                "44000070:4501500009:45030168").getInt("count")==2,
                "Original stock ledger persisted");
            check(status(first.respond("/shop/buy",buy("click-1"),seed,catalog))
                .equals(s1),"First request ID replays original result");
            check(persisted(a).getLong("rmb")==80,"Retry never debits again");
            LocalSave reopened=new LocalSave(a.toFile());
            ProtoWire all=ProtoWire.parse(reopened.respond("/shop/allShopSet",
                new HashMap<String,String>(),seed,catalog));
            int original=0,gifts=0;
            for(ProtoWire.Field field:all.fields)if(field.number==1&&field.type==2){
                long set=ProtoWire.parse(field.data).number(1,0);
                if(set==44000070L)original++;
                if(set==44000025L)gifts++;
            }
            check(original==1&&gifts==1,
                "Combined original exchange and gift sets absent after restart");
            LocalSave other=new LocalSave(b.toFile());
            check("Buy Success".equals(status(other.respond(
                "/shop/buy",buy("other-1"),seed,catalog))),
                "Second account cannot purchase its independent 7# item");
            check(persisted(b).getLong("rmb")==80&&
                persisted(a).getLong("rmb")==80,
                "Cross-account shop balance changed");
            System.out.println("OriginalShopRouteSelfTest: "+checks+" checks passed");
        }finally{
            pool.shutdownNow();
            try(java.util.stream.Stream<Path> paths=Files.walk(directory)){
                paths.sorted(java.util.Comparator.reverseOrder()).forEach(path->{
                    try{Files.deleteIfExists(path);}catch(Exception ignored){}
                });
            }
        }
    }
}
