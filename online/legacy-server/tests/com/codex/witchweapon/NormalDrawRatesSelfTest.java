package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.math.BigDecimal;

/** Published CN permanent Tarot category boundaries and atomic draw results. */
public final class NormalDrawRatesSelfTest {
    private static void check(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    private static final class Slots extends Random {
        private final int[] rolls;
        private int cursor;
        Slots(int... rolls){this.rolls=rolls;}
        @Override public int nextInt(int bound){
            if(bound==10000){
                check(cursor<rolls.length,"Extra category roll");
                return rolls[cursor++];
            }
            return 0;
        }
        int consumed(){return cursor;}
    }
    private static Map<String,String> form(){
        Map<String,String> values=new HashMap<String,String>();
        values.put("times","10");values.put("idempotency","published-rates-ten");
        return values;
    }
    public static void main(String[] args)throws Exception{
        check(args.length==2,"Pass offline_responses.json and original publicity.txt");
        String[] labels={"SSR兵器","SR兵器","R兵器","魔导器","原质道具",
            "原质裂片","玉钢","拉伯雷矿晶","浓缩汽水","莉琉的黑卡"};
        String original=new String(Files.readAllBytes(new File(args[1]).toPath()),
            StandardCharsets.UTF_8);
        int[] disclosure=new int[labels.length];
        for(String line:original.split("\\r?\\n")){
            if(!line.startsWith("0,22,"))continue;
            String[] fields=line.split(",",-1);
            if(fields.length<9||!fields[8].endsWith("%"))continue;
            for(int index=0;index<labels.length;index++)if(labels[index].equals(fields[6]))
                disclosure[index]=new BigDecimal(fields[8].substring(0,fields[8].length()-1))
                    .movePointRight(2).intValueExact();
        }
        check(Arrays.equals(disclosure,NormalDrawRates.WEIGHTS),
            "CN channel 22, pool 0 probabilities differ from original disclosure");
        int[] observed=new int[NormalDrawRates.WEIGHTS.length];
        for(int slot=0;slot<10000;slot++)observed[NormalDrawRates.category(slot)]++;
        check(Arrays.equals(observed,NormalDrawRates.WEIGHTS),
            "Published 0.70/3.50/58.00/7.40/1.90/5.90/6.80/4.50/5.50/5.80 rates differ");
        for(int bad:new int[]{-1,10000}){
            try{NormalDrawRates.category(bad);throw new AssertionError("Bad slot accepted");}
            catch(IllegalArgumentException expected){}
        }
        JSONObject catalog=new JSONObject(new String(Files.readAllBytes(new File(args[0]).toPath()),
            StandardCharsets.UTF_8)).getJSONObject("_catalog");
        int[] disclosedWeaponCounts={15,29,16};
        for(int rarity=0;rarity<disclosedWeaponCounts.length;rarity++){
            Set<Long> actual=new HashSet<Long>();
            for(int index=0;index<disclosedWeaponCounts[rarity];index++){
                final int pick=index;
                long id=NormalDrawRates.weapon(rarity,catalog,new Random(){
                    @Override public int nextInt(int bound){
                        check(pick<bound,"Published weapon missing from active catalog");
                        return pick;
                    }
                });
                check(catalog.getJSONObject("weapons").getJSONObject(Long.toString(id))
                    .getInt("rare")==4-rarity,"Published weapon has incorrect rarity");
                actual.add(id);
            }
            check(actual.size()==disclosedWeaponCounts[rarity],
                "Published weapon was omitted or duplicated");
        }
        JSONObject state=new JSONObject().put("starterProfile",1).put("gold",0).put("rmb",0);
        LocalEconomy.init(state,catalog);
        state.getJSONObject("items").put("40350003",10);
        Slots sequence=new Slots(0,70,420,6220,6960,7150,7740,8420,8870,9420);
        byte[] reply=LocalEconomy.draw(state,catalog,"/draw/rmb/ten",form(),sequence,1700000000L);
        check(sequence.consumed()==10,"Expected exactly ten independent probability rolls");
        ProtoWire result=ProtoWire.parse(reply);
        check(result.fields.size()==13,"Three weapon pairs and seven material rewards expected");
        for(int pull=0;pull<3;pull++){
            ProtoWire witch=ProtoWire.parse(result.fields.get(2*pull).data);
            ProtoWire weapon=ProtoWire.parse(result.fields.get(2*pull+1).data);
            long id=weapon.number(2,0);
            JSONObject def=catalog.getJSONObject("weapons").getJSONObject(Long.toString(id));
            check(witch.number(1,0)==1&&weapon.number(1,0)==4&&
                def.getInt("rare")==4-pull&&witch.number(2,0)==def.getLong("servant"),
                "Published SSR/SR/R boundary selected incorrect rarity");
        }
        long[] knownItems={40130001L,1411001L,40220001L,40240039L,40250038L,40340001L,40340002L};
        for(int i=0;i<7;i++){
            ProtoWire reward=ProtoWire.parse(result.fields.get(6+i).data);
            check(reward.number(1,0)==(i==1?2:3)&&reward.number(4,0)==1,
                "Material/equipment draw returned incorrect loot type");
            check(reward.number(2,0)==knownItems[i],
                "Catalog-backed published item was not granted");
            String id=Long.toString(reward.number(2,0));
            JSONObject bag=state.getJSONObject(i==1?"equips":"items");
            check(bag.getLong(id)>=1,"Draw result was not added to authoritative inventory");
        }
        int[] categories={NormalDrawRates.EQUIP,NormalDrawRates.SEPHIRA,NormalDrawRates.SHARD};
        int[] sizes={38,172,57};
        for(int c=0;c<categories.length;c++){
            final int size=sizes[c];Set<Long> rewards=new HashSet<Long>();
            for(int pick=0;pick<size;pick++){
                final int position=pick;
                long id=NormalDrawRates.rewardId(categories[c],catalog,new Random(){
                    @Override public int nextInt(int bound){check(bound==size,"Original ordinary reward pool size");return position;}
                });
                check(rewards.add(id),"Duplicate ordinary reward candidate");
                if(c==0)check(catalog.getJSONObject("items").getJSONObject(Long.toString(id)).getInt("item_type")==1,
                    "Magic device category returned a different item type");
                if(c==1)check(id<1450000L,"Placeholder orange equipment entered permanent pool");
                if(c==2)check(id<40250000L,"Placeholder orange shard entered permanent pool");
            }
            check(!rewards.contains(1451029L)&&!rewards.contains(40250029L)&&!rewards.contains(40930001L),
                "Blank equipment201 or unknown voucher in permanent pool");
        }
        check(state.getLong("drawCount")==10&&state.getJSONObject("items").getLong("40350003")==0,
            "Ten Tarot draw did not charge exactly ten cards");
        String before=state.toString();
        byte[] replay=LocalEconomy.draw(state,catalog,"/draw/rmb/ten",form(),new Slots(9999),
            1700000001L);
        check(Arrays.equals(reply,replay)&&before.equals(state.toString()),
            "Idempotent replay changed published rewards or inventory");
        System.out.println("NormalDrawRatesSelfTest: PASS");
    }
}
