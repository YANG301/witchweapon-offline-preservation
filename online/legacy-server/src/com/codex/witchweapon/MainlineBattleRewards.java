package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;

/** Account-local rewards for the temporarily simplified mainline encounters. */
final class MainlineBattleRewards {
    // The original Instance table lists possible drops, but no probability or
    // guaranteed quantity. One listed item per clear, rotated by clear count,
    // is an explicit preservation-server rule rather than an original rate.
    private static final long SERVANT_EXP_PER_BATTLE=50;
    private static final int PARTY_LIMIT=4;
    private MainlineBattleRewards(){}

    private static String partyArgument(Map<String,String> args){
        String value=args.get("servantcardids");
        if(value==null)value=args.get("svcardids");
        return value;
    }

    private static List<Long> validateParty(JSONObject account,String raw)throws Exception{
        List<Long> party=new ArrayList<Long>();
        if(raw==null || raw.isEmpty())return party;
        JSONObject owned=account.optJSONObject("ownedServants");
        if(owned==null)throw new IOException("Servant inventory unavailable");
        HashSet<Long> seen=new HashSet<Long>();
        for(String part:raw.split("[|,;]",-1)){
            if(!part.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid battle servant ID");
            long id;
            try{id=Long.parseLong(part);}catch(NumberFormatException bad){throw new IOException("Invalid battle servant ID",bad);}
            if(!seen.add(id) || !owned.has(Long.toString(id)))
                throw new IOException("Unowned or duplicate battle servant");
            party.add(id);
            if(party.size()>PARTY_LIMIT)throw new IOException("Too many battle servants");
        }
        return party;
    }

    private static String encodeParty(List<Long> party){
        StringBuilder text=new StringBuilder();
        for(long id:party){if(text.length()>0)text.append('|');text.append(id);}
        return text.toString();
    }

    static void rememberParty(JSONObject account,Map<String,String> args,long now)throws Exception{
        String raw=partyArgument(args);
        if(raw==null || raw.isEmpty())return;
        String selected=encodeParty(validateParty(account,raw));
        long stage=0;
        String rawStage=args.get("instanceid");
        if(rawStage!=null && rawStage.matches("[1-9][0-9]{0,18}")){
            try{stage=Long.parseLong(rawStage);}catch(NumberFormatException ignored){}
        }
        if(stage==0 && account.optBoolean("active",false))
            stage=account.optLong("activeStage",0);
        account.put("preparedBattleServants",selected).put("preparedBattleServantsAt",now)
            .put("preparedBattleStage",stage);
        if(account.optBoolean("active",false) &&
            (stage==0 || stage==account.optLong("activeStage",0)))
            account.put("activeBattleServants",selected);
    }

    static void beginBattle(JSONObject account,Map<String,String> args,long now)throws Exception{
        account.remove("activeBattleServants");
        String raw=partyArgument(args);
        if(raw!=null && !raw.isEmpty()){
            rememberParty(account,args,now);
            return;
        }
        long preparedAt=account.optLong("preparedBattleServantsAt",0);
        long preparedStage=account.optLong("preparedBattleStage",0);
        if(preparedAt>0 && now>=preparedAt && now-preparedAt<=3600 &&
           (preparedStage==0 || preparedStage==account.optLong("activeStage",0))){
            String selected=account.optString("preparedBattleServants","");
            if(!selected.isEmpty())
                account.put("activeBattleServants",encodeParty(validateParty(account,selected)));
        }
    }

    private static JSONObject originalInstance(JSONObject stage)throws Exception{
        JSONObject source=stage.optJSONObject("source");
        JSONObject instance=source==null?null:source.optJSONObject("instance");
        if(instance==null)throw new IOException("Original stage item list unavailable");
        return instance;
    }

    private static final class Drop {
        final int type;
        final long id;
        Drop(int type,long id){this.type=type;this.id=id;}
    }

    private static List<Drop> originalDropCandidates(JSONObject stage)throws Exception{
        JSONObject row=originalInstance(stage);
        List<Drop> candidates=new ArrayList<Drop>();
        for(int i=1;i<=3;i++)addCandidate(candidates,2,row.optString("instance_loot_equip"+i,""));
        for(int i=1;i<=6;i++)addCandidate(candidates,3,row.optString("instance_loot_item"+i,""));
        if(candidates.isEmpty())throw new IOException("Mainline stage has no original loot candidate");
        return candidates;
    }

    private static void addCandidate(List<Drop> out,int type,String raw)throws Exception{
        if(raw==null || raw.isEmpty())return;
        if(!raw.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid original loot ID");
        long id;
        try{id=Long.parseLong(raw);}catch(NumberFormatException bad){throw new IOException("Invalid original loot ID",bad);}
        out.add(new Drop(type,id));
    }

    static ProtoWire grantListedDrop(JSONObject account,JSONObject catalog,JSONObject stage,
                                     long priorClears)throws Exception{
        if(priorClears<0)throw new IOException("Invalid mainline clear count");
        List<Drop> candidates=originalDropCandidates(stage);
        Drop chosen=candidates.get((int)(priorClears%candidates.size()));
        JSONObject reward=new JSONObject().put("type",chosen.type).put("id",chosen.id)
            .put("value",1).put("count",0);
        LocalEconomy.grantItemReward(account,catalog,reward,1);
        account.put("inventoryRevision",Math.addExact(account.optLong("inventoryRevision",0),1));
        return new ProtoWire().set(1,chosen.type).set(2,chosen.id).set(3,1).set(4,1);
    }

    static ProtoWire grantPartyExperience(JSONObject account,JSONObject catalog)throws Exception{
        String selected=account.optString("activeBattleServants","");
        if(selected.isEmpty())return null;
        List<Long> party=validateParty(account,selected);
        JSONObject owned=account.getJSONObject("ownedServants");
        boolean changed=false;
        for(long id:party){
            String key=Long.toString(id);
            ProtoWire servant=LocalEconomy.decode(owned.getString(key));
            if(servant.number(2,1)>=65)continue;
            LocalEconomy.levelUp(servant,2,3,SERVANT_EXP_PER_BATTLE,
                catalog.getJSONObject("levels"));
            owned.put(key,LocalEconomy.encode(servant));
            changed=true;
        }
        if(!changed)return null;
        account.put("collectionRevision",Math.addExact(account.optLong("collectionRevision",0),1));
        return new ProtoWire().set(1,11).set(3,SERVANT_EXP_PER_BATTLE)
            .set(4,SERVANT_EXP_PER_BATTLE);
    }
}
