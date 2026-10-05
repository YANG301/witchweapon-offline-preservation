package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** Original level/drop display tables; one listed item per clear is a local reconstruction. */
final class MazeRules {
    private static JSONObject data;
    private MazeRules() {}
    private static synchronized JSONObject data()throws Exception{
        if(data!=null)return data;
        InputStream in=MazeRules.class.getResourceAsStream("/maze_rules.json");
        if(in==null)throw new IOException("Maze rules missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1){
                if(out.size()+n>128*1024)throw new IOException("Maze rules too large");
                out.write(buffer,0,n);
            }
            JSONObject rules=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            if(rules.getInt("schemaVersion")!=1 || rules.getJSONObject("roleLevels").length()!=100 ||
               rules.getJSONObject("mobGrowth").length()!=105)
                throw new IOException("Incomplete maze rules");
            data=rules;return rules;
        }finally{in.close();}
    }
    static int roleLevel(JSONObject state,JSONObject catalog)throws Exception{
        if(catalog==null)throw new IOException("Maze player level catalog unavailable");
        return WeaponFurnace.roleLevel(state,catalog);
    }
    static int enemyLevel(int roleLevel,int round)throws Exception{
        if(round<1 || round>12)throw new IOException("Invalid maze round");
        return data().getJSONObject("roleLevels").getJSONObject(Integer.toString(roleLevel))
            .getJSONArray("levels").getInt(round-1);
    }
    static double growth(int level,int type)throws Exception{
        if(level<1 || level>105 || type<0 || type>=10)throw new IOException("Invalid maze growth index");
        double value=data().getJSONObject("mobGrowth").getJSONArray(Integer.toString(level)).getDouble(type);
        if(!Double.isFinite(value) || value<=0)throw new IOException("Missing maze growth coefficient");
        return value;
    }
    static ProtoWire loot(JSONObject state,JSONObject catalog,int round,boolean bonus,boolean grant)
            throws Exception{
        int level=bonus || state.optInt("mazePreparedRound",0)==round?
            state.optInt("mazePreparedRoleLevel",0):0;
        if(level<1 || level>100)level=roleLevel(state,catalog);
        JSONObject row=data().getJSONObject("roleLevels").getJSONObject(Integer.toString(level));
        if(round<1 || round>12 || bonus && round%3!=0)throw new IOException("Invalid maze reward round");
        int lootId=row.getJSONArray(bonus?"bonuses":"loots").getInt(bonus?round/3-1:round-1);
        JSONObject def=data().getJSONObject("loots").getJSONObject(Integer.toString(lootId));
        long multiplier=bonus?VipSystem.mazeSupplyMultiplier(state):1;
        long gold=Math.multiplyExact(def.getLong("gold"),multiplier);
        ProtoWire result=new ProtoWire().add(1,new ProtoWire().set(1,13).set(3,gold).set(4,gold).bytes());
        if(grant)state.put("gold",Math.addExact(state.getLong("gold"),gold));
        JSONArray items=def.getJSONArray("items");
        for(int i=0;i<items.length();i++){
            long id=items.getLong(i);
            if(!catalog.getJSONObject("items").has(Long.toString(id)))
                throw new IOException("Unknown original maze reward item");
            if(grant){
                LocalEconomy.grantItemReward(state,catalog,new JSONObject().put("type",3)
                    .put("id",id).put("value",multiplier).put("count",0),1);
            }
            result.add(1,new ProtoWire().set(1,3).set(2,id).set(3,multiplier).set(4,multiplier).bytes());
        }
        if(grant && items.length()>0)
            state.put("inventoryRevision",Math.addExact(state.optLong("inventoryRevision",0),1));
        return result;
    }
}
