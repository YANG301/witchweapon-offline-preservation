package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.io.File;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.Random;
import java.util.Collections;

/** Original in-game draw costs, free quotas, and replay behavior. */
public final class OnlineDrawSelfTest {
    private static void check(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    private static Map<String,String> form(String... fields){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<fields.length;i+=2)result.put(fields[i],fields[i+1]);
        return result;
    }
    private static JSONObject fresh(JSONObject catalog)throws Exception{
        JSONObject state=new JSONObject().put("starterProfile",1).put("gold",1000)
            .put("rmb",0).put("drawCount",0);
        LocalEconomy.init(state,catalog);
        return state;
    }
    private static void pairedLoot(byte[] response,JSONObject catalog,int pulls)throws Exception{
        ProtoWire draw=ProtoWire.parse(response);
        int seen=0;
        for(int index=0;index<draw.fields.size();index++){
            ProtoWire.Field field=draw.fields.get(index);
            check(field.number==1&&field.type==2,"Unexpected draw response field");
            ProtoWire reward=ProtoWire.parse(field.data);
            int type=(int)reward.number(1,0);
            if(type==1){
                check(++index<draw.fields.size(),"Servant draw has no paired weapon");
                ProtoWire.Field second=draw.fields.get(index);
                check(second.number==1&&second.type==2,"Missing weapon response field");
                ProtoWire weapon=ProtoWire.parse(second.data);
                String weaponId=Long.toString(weapon.number(2,0));
                JSONObject definition=catalog.getJSONObject("weapons").optJSONObject(weaponId);
                check(weapon.number(1,0)==4&&weapon.number(4,0)==1&&
                    reward.number(4,0)==1&&definition!=null&&
                    reward.number(2,0)==definition.getLong("servant"),
                    "Weapon draw cannot be paired for original UI");
            }else if(type==2||type==3){
                JSONObject definitions=catalog.getJSONObject(type==2?"equips":"items");
                check(definitions.has(Long.toString(reward.number(2,0)))&&reward.number(4,0)==1,
                    "Non-weapon draw references absent catalog reward");
            }else throw new AssertionError("Unsupported draw reward type "+type);
            seen++;
        }
        check(seen==pulls,"Draw response did not contain exactly one result per pull");
    }
    private static void denied(JSONObject state,JSONObject catalog,String path,
                               Map<String,String> args,long now)throws Exception{
        String snapshot=state.toString();
        try{
            LocalEconomy.draw(state,catalog,path,args,new Random(4),now);
            throw new AssertionError("Draw should be rejected: "+path);
        }catch(java.io.IOException expected){}
        check(snapshot.equals(state.toString()),"Rejected draw changed a save: "+path);
    }
    public static void main(String[] args)throws Exception{
        if(args.length<1||args.length>2)
            throw new IllegalArgumentException("Arguments: responses.json [fresh-test-dir]");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[0]).toPath()),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        long now=1700000000L;
        JSONObject state=fresh(catalog);
        byte[] freeGold=LocalEconomy.draw(state,catalog,"/draw/gold/single",
            form("idempotency","gold-free-1"),new Random(1),now);
        pairedLoot(freeGold,catalog,1);
        check(state.getLong("gold")==1000&&state.getInt("drawGoldFreeUsed")==1&&
            state.getLong("drawGoldFreeAt")==now+600&&state.getLong("drawCount")==1&&
            state.getLong("drawCurrency")==10,
            "First gold draw did not use original free quota/cooldown");
        String afterFree=state.toString();
        byte[] replay=LocalEconomy.draw(state,catalog,"/draw/gold/single",
            form("idempotency","gold-free-1"),new Random(2),now+3);
        check(Arrays.equals(freeGold,replay)&&afterFree.equals(state.toString()),
            "Retry changed reward, resources, or draw count");
        denied(state,catalog,"/draw/rmb/single",form("idempotency","gold-free-1"),now+4);
        denied(state,catalog,"/draw/gold/single",form("idempotency","gold-early"),now+10);
        LocalEconomy.draw(state,catalog,"/draw/gold/single",
            form("idempotency","gold-free-2"),new Random(2),now+601);
        check(state.getInt("drawGoldFreeUsed")==2&&state.getLong("gold")==1000&&
            state.getLong("drawCurrency")==20,
            "Second gold draw after cooldown should be free");
        JSONObject caphGold=fresh(catalog).put("gold",0).put("vipExp",1000)
            .put("drawFreeDay",LocalDaily.day(now)).put("drawGoldFreeUsed",5)
            .put("drawGoldFreeAt",now);
        LocalEconomy.draw(caphGold,catalog,"/draw/gold/single",
            form("idempotency","caph-gold-sixth"),new Random(24),now);
        check(caphGold.getInt("drawGoldFreeUsed")==6&&caphGold.getLong("gold")==0,
            "CAPH Lv1 sixth daily gold draw is free");
        JSONObject ordinaryGold=fresh(catalog).put("gold",0)
            .put("drawFreeDay",LocalDaily.day(now)).put("drawGoldFreeUsed",5)
            .put("drawGoldFreeAt",now);
        denied(ordinaryGold,catalog,"/draw/gold/single",
            form("idempotency","ordinary-sixth"),now);
        long saturday=now+3*86400L;
        JSONObject caphTarot=fresh(catalog).put("vipExp",7000)
            .put("drawFreeDay",LocalDaily.day(saturday)).put("drawDiamondFreeUsed",1);
        LocalEconomy.draw(caphTarot,catalog,"/draw/rmb/single",
            form("idempotency","caph-weekend-second"),new Random(25),saturday);
        check(caphTarot.getInt("drawDiamondFreeUsed")==2&&
            caphTarot.getJSONObject("items").optLong("40350003",0)==0,
            "CAPH Lv3 second weekend Tarot draw is free");
        JSONObject weekdayTarot=fresh(catalog).put("vipExp",7000)
            .put("drawFreeDay",LocalDaily.day(now)).put("drawDiamondFreeUsed",1);
        denied(weekdayTarot,catalog,"/draw/rmb/single",
            form("idempotency","caph-weekday-second"),now);
        LocalEconomy.draw(state,catalog,"/draw/rmb/single",
            form("idempotency","tarot-free"),new Random(3),now+610);
        check(state.getInt("drawDiamondFreeUsed")==1&&state.getLong("rmb")==0&&
            state.getLong("drawCurrency")==30,
            "Daily right-hand draw should be free and should not use cash wallet");
        JSONObject consecutive=fresh(catalog);
        consecutive.getJSONObject("items").put("40350003",2);
        LocalEconomy.draw(consecutive,catalog,"/draw/rmb/single",
            form("idempotency","click-1"),new Random(31),now);
        LocalEconomy.draw(consecutive,catalog,"/draw/rmb/single",
            form("idempotency","click-2"),new Random(32),now);
        check(consecutive.getLong("drawCount")==2&&
            consecutive.getJSONObject("items").getLong("40350003")==1,
            "Two completed right-pool clicks were merged or charged twice");
        String afterSecond=consecutive.toString();
        LocalEconomy.draw(consecutive,catalog,"/draw/rmb/single",
            form("idempotency","click-2"),new Random(33),now);
        check(afterSecond.equals(consecutive.toString()),
            "Uncertain retry of second right-pool draw charged again");
        LocalEconomy.draw(consecutive,catalog,"/draw/rmb/single",
            form("idempotency","click-3"),new Random(34),now);
        check(consecutive.getLong("drawCount")==3&&
            consecutive.getJSONObject("items").getLong("40350003")==0,
            "Third completed right-pool click did not consume its Tarot Card");
        denied(state,catalog,"/draw/rmb/single",form("idempotency","tarot-empty"),now+620);
        denied(state,catalog,"/draw/rmb/ten",form("idempotency","tarot-ten","times","10"),now+620);
        denied(state,catalog,"/draw/gold/ten",form("idempotency","gold-ten","times","10"),now+620);
        denied(state,catalog,"/draw/gold/single",form("times","10"),now+620);

        JSONObject gold=fresh(catalog).put("gold",150000);
        byte[] goldFive=LocalEconomy.draw(gold,catalog,"/draw/gold/ten",
            form("times","5","idempotency","gold-five"),new Random(4),now);
        pairedLoot(goldFive,catalog,5);
        check(gold.getLong("gold")==112000&&gold.getLong("drawCount")==5&&
            gold.getLong("drawCurrency")==50,
            "Five-draw original 38000 gold cost differs");
        byte[] goldTen=LocalEconomy.draw(gold,catalog,"/draw/gold/ten",
            form("times","10","idempotency","gold-ten"),new Random(5),now);
        pairedLoot(goldTen,catalog,10);
        check(gold.getLong("gold")==22000&&gold.getLong("drawCount")==15&&
            gold.getLong("drawCurrency")==150,
            "Ten-draw original 90000 gold cost differs");
        String settledGoldTen=gold.toString();
        check(Arrays.equals(goldTen,LocalEconomy.draw(gold,catalog,"/draw/gold/ten",
                form("times","10","idempotency","gold-ten"),new Random(51),now+1))&&
            settledGoldTen.equals(gold.toString()),
            "Gold ten-draw retry changed the original result or charged twice");
        JSONObject tarot=fresh(catalog);
        tarot.getJSONObject("items").put("40350003",6).put("40550010",5);
        byte[] tarotTen=LocalEconomy.draw(tarot,catalog,"/draw/rmb/ten",
            form("times","10","idempotency","tarot-ten"),new Random(6),now);
        pairedLoot(tarotTen,catalog,10);
        check(tarot.getJSONObject("items").getLong("40350003")==0&&
            tarot.getJSONObject("items").getLong("40550010")==1&&
            tarot.getLong("drawCount")==10&&tarot.getLong("rmb")==0&&
            tarot.getLong("drawCurrency")==100,
            "Ten-draw should consume ten in-game Tarot Cards atomically");
        String settledTarotTen=tarot.toString();
        check(Arrays.equals(tarotTen,LocalEconomy.draw(tarot,catalog,"/draw/rmb/ten",
                form("times","10","idempotency","tarot-ten"),new Random(61),now+1))&&
            settledTarotTen.equals(tarot.toString()),
            "Tarot ten-draw retry changed the original result or charged twice");
        if(args.length==2){
            File directory=new File(args[1]);
            check(directory.mkdir(),"Fresh integration test directory required");
            LocalSave save=new LocalSave(directory);
            save.respond("/role/create",Collections.<String,String>emptyMap(),new byte[0],catalog);
            save.respond("/backpack/item",Collections.<String,String>emptyMap(),new byte[0],catalog);
            byte[] response=save.respond("/draw/gold/single",form("idempotency","save-free"),
                new byte[0],catalog);
            JSONObject stored=new JSONObject(new String(Files.readAllBytes(new File(directory,
                "offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
            check(stored.getLong("gold")==1000&&stored.getInt("drawGoldFreeUsed")==1&&
                stored.getLong("drawCount")==1&&stored.getLong("drawCurrency")==10,
                "Free draw and its original prayer coins were not persisted exactly once");
            LocalSave reloaded=new LocalSave(directory);
            byte[] persisted=Files.readAllBytes(new File(directory,"offline_save_v1.json").toPath());
            byte[] replayed=reloaded.respond("/draw/gold/single",form("idempotency","save-free"),
                new byte[0],catalog);
            check(Arrays.equals(response,replayed)&&Arrays.equals(persisted,
                Files.readAllBytes(new File(directory,"offline_save_v1.json").toPath())),
                "Save reload did not preserve draw idempotency");
            ProtoWire time=ProtoWire.parse(reloaded.respond("/time/sync",
                Collections.<String,String>emptyMap(),new byte[0],null));
            ProtoWire roleTime=ProtoWire.parse(time.data(6));
            check(roleTime.number(3,-1)==1&&roleTime.number(4,0)>System.currentTimeMillis()/1000L&&
                roleTime.number(5,-1)==0,"RoleTimeInstance did not expose draw quota and cooldown");
            try{
                reloaded.respond("/draw/gold/ten",form("times","10","idempotency","poor"),
                    new byte[0],catalog);
                throw new AssertionError("Unfunded ten-draw accepted");
            }catch(java.io.IOException expected){}
            check(Arrays.equals(persisted,Files.readAllBytes(new File(directory,
                "offline_save_v1.json").toPath())),"Unfunded draw wrote a partial save");
        }
        System.out.println("ONLINE_DRAW_OK");
    }
}
