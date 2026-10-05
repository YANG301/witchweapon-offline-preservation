package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

/**
 * Owner-approved nostalgia gold pool, not undisclosed original server odds.
 * Original Item / ServantEquip rows restrict non-weapon rewards to ordinary
 * low-tier materials. Limited tokens, cosmetics and event weapons are absent.
 */
final class GoldDrawRates {
    static final int SSR=0, SR=1, R=2, EQUIP=3, SHARD=4, SODA=5,
        WEAPON_MATERIAL=6, SERVANT_TOKEN=7;
    static final int[] WEIGHTS={1,100,1000,3000,2000,2000,899,1000};
    private static final long[] TOKENS={
        40130001L,40130002L,40130003L,40130004L,40130005L,
        40130006L,40130007L,40130008L,40130009L,40130010L,
        40130011L,40130012L,40130013L,40130014L,40130015L,
        40130016L,40130017L,40130018L,40130019L,40130020L,
        40130023L,40130025L,40130026L,40130027L,40130029L,
        40130030L,40130031L,40130032L,40130033L,40130034L,
        40130035L,40130036L,40130037L,40130040L,
        40130042L,40130043L,40130044L,40130045L
    };

    private GoldDrawRates(){}

    static int category(int slot){
        if(slot<0||slot>=10000)throw new IllegalArgumentException("Gold draw slot outside [0,10000)");
        for(int i=0;i<WEIGHTS.length;i++){
            slot-=WEIGHTS[i];
            if(slot<0)return i;
        }
        throw new AssertionError("Gold weights do not total 10000");
    }

    static int roll(Random random){return category(random.nextInt(10000));}

    /** Validate the entire allowlist before charging, rather than silently shrinking it. */
    static List<List<Long>> pools(JSONObject catalog)throws IOException{
        List<List<Long>> pools=new ArrayList<List<Long>>();
        for(int rarity=SSR;rarity<=R;rarity++){
            List<Long> weapons=NormalDrawRates.weaponPool(rarity,catalog);
            if(weapons.size()!=new int[]{15,29,16}[rarity])
                throw new IOException("Permanent gold weapon template is missing");
            pools.add(Collections.unmodifiableList(weapons));
        }
        List<Long> equips=new ArrayList<Long>();
        range(equips,1411001L,1411018L);
        range(equips,1421001L,1421015L);
        range(equips,1431001L,1431019L);
        pools.add(validated(catalog,"equips",equips));
        List<Long> shards=new ArrayList<Long>();
        range(shards,40220001L,40220019L);
        pools.add(validated(catalog,"items",shards));
        pools.add(validated(catalog,"items",ids(40310001L,40320001L,40330001L)));
        pools.add(validated(catalog,"items",ids(40220020L,40230001L)));
        pools.add(validated(catalog,"items",ids(TOKENS)));
        return Collections.unmodifiableList(pools);
    }

    static long rewardId(int category,List<List<Long>> pools,Random random){
        List<Long> choices=pools.get(category);
        return choices.get(random.nextInt(choices.size()));
    }

    private static List<Long> validated(JSONObject catalog,String type,List<Long> ids)
            throws IOException{
        JSONObject definitions=catalog.optJSONObject(type);
        for(long id:ids)if(definitions==null||!definitions.has(Long.toString(id)))
            throw new IOException("Gold reward template missing: "+id);
        return Collections.unmodifiableList(ids);
    }

    private static List<Long> ids(long... ids){
        List<Long> result=new ArrayList<Long>();
        for(long id:ids)result.add(id);
        return result;
    }

    private static void range(List<Long> ids,long first,long last){
        for(long id=first;id<=last;id++)ids.add(id);
    }
}
