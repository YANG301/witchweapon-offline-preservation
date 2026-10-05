package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

/**
 * CN channel 22, permanent Tarot pool (publicity.txt, ID 0).
 * The 10,000 slots are the exact published category percentages. The source
 * does not disclose weights within equipment, Sephira, or shard categories;
 * those catalog-backed choices are deliberately uniform, not an original
 * server claim. Gold draws and event banners have different, unavailable data.
 */
final class NormalDrawRates {
    static final int SSR=0, SR=1, R=2, EQUIP=3, SEPHIRA=4, SHARD=5,
        JADE=6, ORE=7, SODA=8, BLACK_CARD=9;
    static final int[] WEIGHTS={70,350,5800,740,190,590,680,450,550,580};
    private static final long[][] WEAPONS={
        {1701430101L,1701010103L,1701080101L,1701010102L,1701020101L,
         1701050102L,1701110102L,1701140101L,1701150102L,1701270101L,
         1701370101L,1701380101L,1701410102L,1701410101L,1701100103L},
        {1701010101L,1701020102L,1701030101L,1701040102L,1701050101L,
         1701060101L,1701070102L,1701080102L,1701090101L,1701090102L,
         1701100101L,1701100102L,1701110101L,1701140102L,1701160101L,
         1701160102L,1701170101L,1701190101L,1701190102L,1701220101L,
         1701240101L,1701240102L,1701250101L,1701250102L,1701290101L,
         1701290102L,1701300101L,1701350101L,1701320101L},
        {1701000101L,1701000102L,1701030102L,1701040101L,1701060102L,
         1701070101L,1701120101L,1701120102L,1701130101L,1701150101L,
         1701180101L,1701180102L,1701220102L,1701300102L,1701310101L,
         1701330101L}
    };
    // Original Item rows: ordinary witch magic devices, not ServantEquip.
    private static final long[] MAGIC_DEVICES={
        40130001L,40130002L,40130003L,40130004L,40130005L,
        40130006L,40130007L,40130008L,40130009L,40130010L,
        40130011L,40130012L,40130013L,40130014L,40130015L,
        40130016L,40130017L,40130018L,40130019L,40130020L,
        40130023L,40130025L,40130026L,40130027L,40130029L,
        40130030L,40130031L,40130032L,40130033L,40130034L,
        40130035L,40130036L,40130037L,40130040L,
        40130042L,40130043L,40130044L,40130045L
    };

    private NormalDrawRates(){}

    static int category(int slot){
        if(slot<0||slot>=10000)throw new IllegalArgumentException("Draw slot outside [0,10000)");
        for(int i=0;i<WEIGHTS.length;i++){
            slot-=WEIGHTS[i];
            if(slot<0)return i;
        }
        throw new AssertionError("Published draw weights do not total 10000");
    }

    static int roll(Random random){return category(random.nextInt(10000));}

    static long weapon(int rarity,JSONObject catalog,Random random)throws IOException{
        List<Long> candidates=weaponPool(rarity,catalog);
        return candidates.get(random.nextInt(candidates.size()));
    }

    /** Shared disclosed permanent pool; shop exchanges do not roll category odds. */
    static List<Long> weaponPool(int rarity,JSONObject catalog)throws IOException{
        if(rarity<SSR||rarity>R)throw new IOException("Not a weapon draw category");
        JSONObject defs=catalog.optJSONObject("weapons"),servants=catalog.optJSONObject("servants");
        List<Long> candidates=new ArrayList<Long>();
        for(long id:WEAPONS[rarity]){
            JSONObject definition=defs==null?null:defs.optJSONObject(Long.toString(id));
            if(definition!=null&&servants!=null&&
                servants.has(Long.toString(definition.optLong("servant"))))candidates.add(id);
        }
        if(candidates.isEmpty())throw new IOException("Published rarity pool is absent from catalog");
        return candidates;
    }

    static long rewardId(int category,JSONObject catalog,Random random)throws IOException{
        JSONObject defs;
        List<Long> candidates=new ArrayList<Long>();
        if(category==EQUIP){
            defs=catalog.optJSONObject("items");
            for(long id:MAGIC_DEVICES)candidates.add(id);
        }else if(category==SEPHIRA){
            // Quality 1-4 ServantEquip rows have real names and icon assets.
            // Quality 5 is unused placeholder data (including "equipment201").
            defs=catalog.optJSONObject("equips");
            range(candidates,1411001L,1411018L);
            range(candidates,1421001L,1421015L);range(candidates,1422001L,1422016L);
            range(candidates,1431001L,1431019L);range(candidates,1432001L,1432011L);
            range(candidates,1433001L,1433012L);range(candidates,1441001L,1441038L);
            range(candidates,1442001L,1442011L);range(candidates,1443001L,1443010L);
            range(candidates,1444001L,1444011L);range(candidates,1445001L,1445011L);
        }else if(category==SHARD){
            defs=catalog.optJSONObject("items");
            range(candidates,40220001L,40220019L);range(candidates,40240001L,40240038L);
        }else if(category>=JADE&&category<=BLACK_CARD){
            long id=category==JADE?40240039L:category==ORE?40250038L:
                category==SODA?40340001L:40340002L;
            defs=catalog.optJSONObject("items");
            if(defs!=null&&defs.has(Long.toString(id)))candidates.add(id);
        }else throw new IOException("Not a non-weapon draw category");
        if(candidates.isEmpty())throw new IOException("Published reward category is absent from catalog");
        for(long id:candidates)if(defs==null||!defs.has(Long.toString(id)))
            throw new IOException("Permanent reward template missing: "+id);
        Collections.sort(candidates);
        return candidates.get(random.nextInt(candidates.size()));
    }

    private static void range(List<Long> ids,long first,long last){
        for(long id=first;id<=last;id++)ids.add(id);
    }
}
