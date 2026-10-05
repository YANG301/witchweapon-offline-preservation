package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;

/** Exact approved odds, reward ownership, replay and non-event gold rewards. */
public final class GoldDrawRatesSelfTest {
    private static void check(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    private static final class Slots extends Random {
        private final int[] rolls;
        private int cursor;
        Slots(int... rolls){this.rolls=rolls;}
        @Override public int nextInt(int bound){
            if(bound==10000){
                check(cursor<rolls.length,"Unexpected probability roll");
                return rolls[cursor++];
            }
            return 0;
        }
    }
    private static JSONObject state(JSONObject catalog)throws Exception{
        JSONObject state=new JSONObject().put("starterProfile",1).put("gold",100000)
            .put("rmb",0);
        LocalEconomy.init(state,catalog);
        state.put("items",new JSONObject());
        return state;
    }
    private static Map<String,String> ten(String key){
        Map<String,String> form=new HashMap<String,String>();
        form.put("times","10");form.put("idempotency",key);
        return form;
    }
    private static void checkReply(JSONObject state,JSONObject catalog,byte[] bytes,
                                   int[] categories,List<List<Long>> pools)throws Exception{
        ProtoWire reply=ProtoWire.parse(bytes);
        Map<String,Integer> grants=new HashMap<String,Integer>();
        int cursor=0;
        for(int category:categories){
            ProtoWire loot=ProtoWire.parse(reply.fields.get(cursor++).data);
            if(category<=GoldDrawRates.R){
                ProtoWire weapon=ProtoWire.parse(reply.fields.get(cursor++).data);
                long id=weapon.number(2,0);
                JSONObject definition=catalog.getJSONObject("weapons").getJSONObject(Long.toString(id));
                check(loot.number(1,0)==1&&weapon.number(1,0)==4&&
                    definition.getInt("rare")==4-category&&
                    loot.number(2,0)==definition.getLong("servant"),"Gold weapon/witch pair is invalid");
                check(state.getJSONObject("ownedServants").has(Long.toString(loot.number(2,0))),
                    "Drawn witch was not owned after settlement");
                ProtoWire owned=LocalEconomy.decode(state.getJSONObject("ownedServants")
                    .getString(Long.toString(loot.number(2,0))));
                boolean hasWeapon=false;
                for(ProtoWire.Field field:owned.fields)if(field.number==13&&field.type==2&&
                    ProtoWire.parse(field.data).number(1,0)==id)hasWeapon=true;
                check(hasWeapon,"Drawn weapon was not owned after settlement");
                check(id==pools.get(category).get(0),"Selected weapon changed because of ownership");
            }else{
                long id=loot.number(2,0);
                int type=category==GoldDrawRates.EQUIP?2:3;
                check(loot.number(1,0)==type&&loot.number(4,0)==1&&
                    pools.get(category).contains(id),"Gold material has the wrong loot type or pool");
                String bag=type==2?"equips":"items",key=bag+":"+id;
                grants.put(key,grants.containsKey(key)?grants.get(key)+1:1);
            }
        }
        check(cursor==reply.fields.size(),"Extra or missing gold result entries");
        for(Map.Entry<String,Integer> grant:grants.entrySet()){
            String[] key=grant.getKey().split(":");
            // Magic devices can also come from real witch decomposition in
            // this same draw; those stacks are checked separately by the
            // exhaustive duplicate persistence test.
            boolean device=key[0].equals("items")&&catalog.getJSONObject("items")
                .getJSONObject(key[1]).optInt("item_type")==1;
            long actual=state.getJSONObject(key[0]).getLong(key[1]);
            check(device?actual>=grant.getValue():actual==grant.getValue(),
                "Displayed gold material does not match the authoritative grant");
        }
    }
    public static void main(String[] args)throws Exception{
        check(args.length==1,"Pass offline_responses.json");
        JSONObject catalog=new JSONObject(new String(Files.readAllBytes(new File(args[0]).toPath()),
            StandardCharsets.UTF_8)).getJSONObject("_catalog");
        int[] approved={1,100,1000,3000,2000,2000,899,1000};
        int[] actual=new int[approved.length];
        for(int slot=0;slot<10000;slot++)actual[GoldDrawRates.category(slot)]++;
        check(Arrays.equals(approved,actual),"Approved SSR 0.01 / SR 1 / R 10 odds differ");
        for(int bad:new int[]{-1,10000}){
            try{GoldDrawRates.category(bad);throw new AssertionError("Invalid slot accepted");}
            catch(IllegalArgumentException expected){}
        }
        List<List<Long>> pools=GoldDrawRates.pools(catalog);
        int[] counts={15,29,16,52,19,3,2,38};
        Set<Long> banned=new HashSet<Long>(Arrays.asList(40130021L,40130022L,40130024L,
            40130028L,40130038L,40130039L,40130041L,40130046L,40130047L,
            40340001L,40350001L,40240039L,40250038L));
        for(int category=0;category<counts.length;category++){
            List<Long> ids=pools.get(category);
            check(ids.size()==counts[category]&&new HashSet<Long>(ids).size()==counts[category],
                "Gold allowlist is incomplete or duplicated");
            for(long id:ids)check(!banned.contains(id),"Limited/high-tier material entered gold pool");
        }
        int[] rolls={0,1,101,1101,4101,6101,8101,9000,9999,1100};
        int[] categories={0,1,2,3,4,5,6,7,7,2};
        for(boolean online:new boolean[]{true,false}){
            JSONObject state=state(catalog);
            if(!online)state.remove("starterProfile");
            byte[] result=LocalEconomy.draw(state,catalog,"/draw/gold/ten",ten("gold-all-types"),
                new Slots(rolls),1700000000L);
            checkReply(state,catalog,result,categories,pools);
            check(state.getLong("drawCount")==10,"Gold draw counter is wrong");
            if(online)check(state.getLong("gold")==10000&&state.getLong("drawCurrency")==100,
                "Gold ten did not cost 90000 or granted wish currency more than once");
            String before=state.toString();
            byte[] replay=LocalEconomy.draw(state,catalog,"/draw/gold/ten",ten("gold-all-types"),
                new Slots(),1700000001L);
            check(Arrays.equals(result,replay)&&before.equals(state.toString()),
                "Gold replay rolled, charged or granted twice");
        }
        JSONObject repeated=state(catalog);
        byte[] repeatedReply=LocalEconomy.draw(repeated,catalog,"/draw/gold/ten",ten("gold-repeat"),
            new Slots(101,101,101,101,101,101,101,101,101,101),1700000000L);
        checkReply(repeated,catalog,repeatedReply,new int[]{2,2,2,2,2,2,2,2,2,2},pools);
        JSONObject incomplete=new JSONObject(catalog.toString());
        incomplete.getJSONObject("items").remove("40330001");
        JSONObject safe=state(catalog);String before=safe.toString();
        try{
            LocalEconomy.draw(safe,incomplete,"/draw/gold/ten",ten("bad-catalog"),
                new Slots(6101),1700000000L);
            throw new AssertionError("Incomplete gold catalog accepted");
        }catch(java.io.IOException expected){}
        check(before.equals(safe.toString()),"Invalid gold catalog charged or changed save");
        System.out.println("GoldDrawRatesSelfTest: PASS (10000 slots; online/local; grants; replay; duplicates)");
    }
}
