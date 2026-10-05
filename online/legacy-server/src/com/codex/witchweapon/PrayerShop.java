package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Random;
import java.util.Set;

/** Original random/special R/SR/SSR weapon exchanges, never inventory vouchers. */
final class PrayerShop {
    private static PrayerShop singleton;
    private final JSONObject decomposition;
    private final JSONObject servantPieces;
    private final JSONObject fragmentCounts;

    static synchronized PrayerShop bundled()throws Exception{
        if(singleton!=null)return singleton;
        InputStream input=PrayerShop.class.getResourceAsStream("/prayer_shop_catalog.json");
        if(input==null)throw new IOException("Original prayer decomposition missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] block=new byte[4096];int n;
            while((n=input.read(block))!=-1){
                if(out.size()+n>65536)throw new IOException("Prayer catalog too large");
                out.write(block,0,n);
            }
            singleton=new PrayerShop(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }finally{input.close();}
    }

    PrayerShop(JSONObject config)throws Exception{
        if(config.getInt("schemaVersion")!=1)throw new IOException("Unsupported prayer catalog");
        decomposition=config.getJSONObject("decomposition");
        servantPieces=config.getJSONObject("servantPieces");
        fragmentCounts=config.getJSONObject("fragmentCounts");
        if(decomposition.length()!=60)throw new IOException("Incomplete permanent prayer pool");
    }

    static boolean isSet(long set){return set==44000015L;}

    static int rarity(long good)throws IOException{
        if(good<45030152L||good>45030157L)throw new IOException("Unknown prayer exchange");
        return NormalDrawRates.R-(int)((good-45030152L)%3);
    }

    private static long item(long good)throws IOException{
        rarity(good);
        return new long[]{40330085L,40340007L,40350014L,40330086L,40340008L,40350015L}
            [(int)(good-45030152L)];
    }

    static Set<Long> ownedWeapons(JSONObject state)throws Exception{
        Set<Long> result=new HashSet<Long>();JSONObject owned=state.getJSONObject("ownedServants");
        for(Iterator<String> it=owned.keys();it.hasNext();){
            ProtoWire servant=LocalEconomy.decode(owned.getString(it.next()));
            for(ProtoWire.Field field:servant.fields)if(field.number==13&&field.type==2)
                result.add(ProtoWire.parse(field.data).number(1,0));
        }
        return result;
    }

    List<ProtoWire> exchange(JSONObject state,JSONObject catalog,JSONObject good,
                             long count,Random random)throws Exception{
        long goodID=good.getLong("id");int category=rarity(goodID);
        if(count!=1||good.getInt("type")!=3||good.getLong("itemId")!=item(goodID)||good.getLong("value")!=1)
            throw new IOException("Invalid original prayer exchange terms");
        List<Long> pool=NormalDrawRates.weaponPool(category,catalog);
        Set<Long> have=ownedWeapons(state);
        List<Long> choices=new ArrayList<Long>(pool);
        if(goodID>=45030155L){
            choices.clear();for(long weapon:pool)if(!have.contains(weapon))choices.add(weapon);
            if(choices.isEmpty())choices.addAll(pool);
        }
        long weapon=choices.get(random.nextInt(choices.size()));
        return grantWeapon(state,catalog,weapon,true);
    }

    /** Settle the same original duplicate rewards for both draws and exchanges. */
    List<ProtoWire> grantWeapon(JSONObject state,JSONObject catalog,long weapon,
                               boolean includeStoneLoot)throws Exception{
        Set<Long> have=ownedWeapons(state);
        JSONObject definition=catalog.getJSONObject("weapons").getJSONObject(Long.toString(weapon));
        long servant=definition.getLong("servant");
        boolean knownServant=state.getJSONObject("ownedServants").has(Long.toString(servant));
        if(knownServant){
            long fragment=servantPieces.getLong(Long.toString(servant));
            LocalEconomy.addItem(state.getJSONObject("items"),catalog,Long.toString(fragment),
                fragmentCounts.getLong(Integer.toString(definition.getInt("rare"))));
        }
        JSONArray stone=null;
        if(have.contains(weapon)){
            JSONObject duplicate=decomposition.getJSONObject(Long.toString(weapon));
            JSONArray materials=duplicate.getJSONArray("materials");
            for(int i=0;i<materials.length();i++){
                JSONArray reward=materials.getJSONArray(i);
                LocalEconomy.addItem(state.getJSONObject("items"),catalog,Long.toString(reward.getLong(0)),reward.getLong(1));
            }
            stone=duplicate.getJSONArray("knifeStone");
            LocalEconomy.addItem(state.getJSONObject("items"),catalog,Long.toString(stone.getLong(0)),stone.getLong(1));
        }else{
            LocalEconomy.grantItemReward(state,catalog,new JSONObject().put("type",4)
                .put("id",weapon).put("value",1).put("count",1),1);
        }
        // The original client reads ownership BEFORE AddLoot. This pair feeds
        // its existing new-weapon / servant / duplicate presentation and cache.
        List<ProtoWire> result=new ArrayList<ProtoWire>();
        result.add(new ProtoWire().set(1,1).set(2,servant).set(4,1));
        result.add(new ProtoWire().set(1,4).set(2,weapon).set(4,1));
        // AddLoot already derives the witch fragments and three duplicate
        // materials from the pair. Only the fourth, knife-stone reward needs
        // its own loot entry; sending the others would duplicate client counts.
        // A draw must remain one displayed result per pull. Its knife stone
        // is persisted here; the normal inventory query exposes the balance.
        if(stone!=null&&includeStoneLoot)result.add(new ProtoWire().set(1,3).set(2,stone.getLong(0)).set(4,stone.getLong(1)));
        return result;
    }
}
