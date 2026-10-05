package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;

/** Optional original-layout resource. Absence preserves the existing game. */
final class PreservedBattleCatalog {
    private final JSONObject stages;
    private static final class Holder {
        static final PreservedBattleCatalog INSTANCE=load();
    }
    private PreservedBattleCatalog(JSONObject document)throws Exception {
        stages=new JSONObject();
        if(document==null)return;
        if(document.optInt("schemaVersion",0)!=1 ||
            !"preserved-layouts-v1".equals(document.optString("mode")))
            throw new IOException("Unsupported preserved battle catalog");
        JSONObject entries=document.getJSONObject("stages");
        if(entries.length()!=247 || document.getJSONArray("missingStageIds").length()!=50)
            throw new IOException("Incomplete preserved battle catalog");
        int main=0,daily=0,furnace=0,slate=0,maze=0;
        for(Iterator<String> it=entries.keys();it.hasNext();){
            String key=it.next();
            if(!key.matches("31[0-3][0-9]{7}"))throw new IOException("Invalid preserved stage ID");
            long id=Long.parseLong(key);
            JSONObject row=entries.getJSONObject(key);
            if(row.getLong("id")!=id)throw new IOException("Preserved stage ID mismatch");
            JSONObject battle=row.getJSONObject("combatJson");
            if(!key.equals(battle.getJSONObject("EnemyLayer").getString("levelID")) ||
                battle.getJSONObject("EnemyLayer").getJSONArray("areas").length()==0)
                throw new IOException("Invalid original layout");
            JSONObject source=row.getJSONObject("source");
            String scene=source.getString("sceneName");
            if(!scene.matches("map_[0-9]{4}_[a-zA-Z0-9_]+") ||
                !scene.equals(battle.getJSONObject("MapInfo").getString("sceneName")) ||
                !source.getString("sha256").matches("[a-f0-9]{64}"))
                throw new IOException("Invalid original layout provenance");
            if(Base64.decode(row.getString("combatMobInfo"),Base64.DEFAULT).length==0)
                throw new IOException("Empty original enemy parameter packet");
            String kind=row.getString("kind");
            if(kind.equals("主线") && id>=3110001001L && id<=3110013015L)main++;
            else if(kind.equals("日常检视") && id>=3120001001L && id<=3120006006L)daily++;
            else if(kind.equals("刻印熔炉") && id>=3120007001L && id<=3120007004L)furnace++;
            else if(kind.equals("石板挑战") && id>=3100005001L && id<=3100005005L)slate++;
            else if(kind.equals("结界迷宫") && BarrierLabyrinth.supports(id))maze++;
            else throw new IOException("Original battle belongs to an unsupported route");
            stages.put(key,row);
        }
        if(main!=190 || daily!=36 || furnace!=4 || slate!=5 || maze!=12)
            throw new IOException("Preserved battle mode counts mismatch");
        JSONArray missing=document.getJSONArray("missingStageIds");
        for(int i=0;i<missing.length();i++)
            if(stages.has(Long.toString(missing.getLong(i))))
                throw new IOException("Preserved battle overlaps missing fallback");
    }
    private static PreservedBattleCatalog load(){
        try(InputStream in=PreservedBattleCatalog.class.getResourceAsStream("/preserved_battle_catalog.json")){
            if(in==null)return new PreservedBattleCatalog(null);
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1){
                if(out.size()+n>64*1024*1024)throw new IOException("Preserved battle resource too large");
                out.write(buffer,0,n);
            }
            return new PreservedBattleCatalog(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
        }catch(Exception ex){throw new IllegalStateException("Invalid preserved battle resource",ex);}
    }
    static int count(){return Holder.INSTANCE.stages.length();}
    static boolean contains(long id){return Holder.INSTANCE.stages.has(Long.toString(id));}

    /** Match mainline metadata to the actual scene, preserving unlocks and rewards. */
    static void applyMainline(JSONObject document)throws Exception {
        JSONObject current=document.getJSONObject("stages");
        JSONObject source=Holder.INSTANCE.stages;
        for(Iterator<String> it=source.keys();it.hasNext();){
            String key=it.next();JSONObject row=source.getJSONObject(key);
            if(!"主线".equals(row.getString("kind")))continue;
            JSONObject stage=current.getJSONObject(key);
            JSONObject metadata=row.getJSONObject("source");
            stage.put("combatJson",new JSONObject(row.getJSONObject("combatJson").toString()));
            stage.put("combatMobInfo",new JSONObject().put("type","application/octet-stream")
                .put("base64",row.getString("combatMobInfo")));
            stage.put("mapId",metadata.getInt("mapId"));
            stage.put("sceneName",metadata.getString("sceneName"));
            stage.put("battleSource","preserved-2019");
            stage.put("layoutReconstructed",false);
            stage.put("enemyStatsSource","2019-editor-tables");
            stage.put("localReconstruction",row.getJSONObject("enemyParameterProvenance")
                .getJSONArray("gaps").length()>0);
            stage.put("preservedBattleProvenance",new JSONObject(metadata.toString()));
        }
    }

    /** Install last so maze balancing and temporary daily fixtures cannot overwrite originals. */
    static void install(JSONObject responses)throws Exception {
        JSONObject source=Holder.INSTANCE.stages;
        for(Iterator<String> it=source.keys();it.hasNext();){
            String key=it.next();JSONObject row=source.getJSONObject(key);
            responses.put("/combat/mob/json#"+key,new JSONObject()
                .put("type","application/json").put("body",row.getJSONObject("combatJson").toString()));
            responses.put("/combat/mob/info#"+key,new JSONObject()
                .put("type","application/octet-stream").put("base64",row.getString("combatMobInfo")));
        }
    }
}
