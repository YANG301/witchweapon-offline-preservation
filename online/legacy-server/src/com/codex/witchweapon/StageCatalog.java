package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Original Instance rows paired with locally reconstructed, stage-specific combat data. */
final class StageCatalog {
    static final long MAZE_TRIAL=3130001026L;
    static final long FORMER_MAZE_ENTRY=3110001003L;
    private static final String RESOURCE="/stage_catalog.json";
    private final Map<Long,JSONObject> stages=new LinkedHashMap<Long,JSONObject>();
    private final Map<Long,List<Long>> chapterStages=new LinkedHashMap<Long,List<Long>>();
    private final Map<Long,Long> prerequisites=new HashMap<Long,Long>();
    private final String profile;

    static StageCatalog bundled() throws Exception {
        InputStream in=StageCatalog.class.getResourceAsStream(RESOURCE);
        if(in==null)throw new IOException("Bundled mainline stage catalog missing");
        try {
            ByteArrayOutputStream output=new ByteArrayOutputStream();
            byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1){
                if(output.size()+n>8*1024*1024)throw new IOException("Stage catalog too large");
                output.write(buffer,0,n);
            }
            JSONObject document=new JSONObject(new String(output.toByteArray(),StandardCharsets.UTF_8));
            PreservedBattleCatalog.applyMainline(document);
            return new StageCatalog(document);
        } finally {in.close();}
    }

    StageCatalog(JSONObject document) throws Exception {
        if(document.optInt("schemaVersion",0)!=1)throw new IOException("Unsupported stage catalog schema");
        JSONObject entries=document.getJSONObject("stages");
        if(entries.length()!=235)throw new IOException("Expected 235 original mainline stages");
        String mode=document.optString("mode", "reconstructed");
        if(!mode.equals("reconstructed") && !mode.equals("simple-campaign-v1"))
            throw new IOException("Unknown mainline stage profile");
        profile=mode;
        int expectedSupported=mode.equals("simple-campaign-v1")?235:220;
        int supported=0,normal=0,elite=0;
        for(Iterator<String> it=entries.keys();it.hasNext();){
            String key=it.next();
            if(!key.matches("311[0-9]{7}"))throw new IOException("Invalid stage catalog ID");
            long id=Long.parseLong(key);
            JSONObject stage=entries.getJSONObject(key);
            if(stage.getLong("id")!=id)throw new IOException("Stage catalog ID mismatch");
            int type=stage.getInt("type");
            if(type!=2 && type!=3)throw new IOException("Non-mainline stage in catalog");
            if(type==2)normal++;else elite++;
            long chapter=stage.getLong("chapterId");
            if(chapter<3010001 || chapter>3010016)throw new IOException("Invalid mainline chapter");
            List<Long> ids=chapterStages.get(chapter);
            if(ids==null){ids=new ArrayList<Long>();chapterStages.put(chapter,ids);}
            ids.add(id);
            if(stage.getBoolean("supported")){
                supported++;
                JSONObject combat=stage.getJSONObject("combatJson");
                JSONObject enemy=combat.getJSONObject("EnemyLayer");
                if(!Long.toString(id).equals(enemy.getString("levelID")) ||
                    enemy.getJSONArray("areas").length()==0)
                    throw new IOException("Invalid stage combat layout");
                JSONObject mob=stage.getJSONObject("combatMobInfo");
                if(!"application/octet-stream".equals(mob.getString("type")) ||
                    Base64.decode(mob.getString("base64"),Base64.DEFAULT).length==0)
                    throw new IOException("Invalid stage mob protobuf");
            }else if(chapter!=3010016)
                throw new IOException("Unexpected unavailable mainline stage");
            stages.put(id,stage);
        }
        if(normal!=160 || elite!=75 || supported!=expectedSupported)
            throw new IOException("Mainline stage counts do not match original table");
        for(Map.Entry<Long,List<Long>> chapter:chapterStages.entrySet()){
            List<Long> ids=chapter.getValue();
            Collections.sort(ids,new Comparator<Long>(){public int compare(Long a,Long b){
                JSONObject sa=stages.get(a),sb=stages.get(b);
                int type=sa.optInt("type")-sb.optInt("type");
                if(type!=0)return type;
                int order=sa.optInt("order")-sb.optInt("order");
                return order!=0?order:a.compareTo(b);
            }});
            int expected=chapter.getKey()==3010001L?10:15;
            if(ids.size()!=expected)throw new IOException("Incomplete mainline chapter");
            for(int i=0;i<ids.size();i++){
                long id=ids.get(i);
                JSONArray fromMapPoint=stages.get(id).getJSONArray("predecessorIds");
                if(fromMapPoint.length()>1)throw new IOException("Ambiguous stage prerequisite");
                if(fromMapPoint.length()==1){
                    long previous=fromMapPoint.getLong(0);
                    if(!stages.containsKey(previous))throw new IOException("Unknown stage prerequisite");
                    prerequisites.put(id,previous);
                }else if(i==0 && chapter.getKey()>3010001L){
                    List<Long> previous=chapterStages.get(chapter.getKey()-1);
                    if(previous==null || previous.size()<10)throw new IOException("Missing preceding chapter");
                    prerequisites.put(id,previous.get(9));
                }else if(i>0)throw new IOException("Missing internal stage prerequisite");
            }
        }
    }

    JSONObject stage(long id){return stages.get(id);}
    String profile(){return PreservedBattleCatalog.count()>0?"preserved-layouts-v1":profile;}
    /** Temporary playable profile: preserve prerequisites as metadata only. */
    boolean openAllMainline(){return "simple-campaign-v1".equals(profile);}
    int supportedCount(){int count=0;for(JSONObject stage:stages.values())if(stage.optBoolean("supported",false))count++;return count;}
    boolean contains(long id){return stages.containsKey(id);}
    boolean supported(long id){JSONObject stage=stages.get(id);return stage!=null && stage.optBoolean("supported",false);}
    Long prerequisite(long id){return prerequisites.get(id);}
    List<Long> stagesForChapter(long chapter){
        List<Long> ids=chapterStages.get(chapter);
        return ids==null?Collections.<Long>emptyList():ids;
    }
    long chapterOf(long id){JSONObject stage=stages.get(id);return stage==null?0:stage.optLong("chapterId",0);}
    List<Long> unlockedAfter(long cleared){
        if(openAllMainline())return Collections.<Long>emptyList();
        List<Long> result=new ArrayList<Long>();
        for(Map.Entry<Long,Long> link:prerequisites.entrySet())
            if(link.getValue()==cleared && supported(link.getKey()))result.add(link.getKey());
        Collections.sort(result);
        return result;
    }

    /** Keep the old twelve-wave encounter, but stop hijacking mainline 1-3. */
    void install(JSONObject responses) throws Exception {
        List<String> oldKeys=new ArrayList<String>();
        for(Iterator<String> it=responses.keys();it.hasNext();){
            String key=it.next();
            if(key.startsWith("/combat/mob/json#"+FORMER_MAZE_ENTRY) ||
               key.startsWith("/combat/mob/info#"+FORMER_MAZE_ENTRY))oldKeys.add(key);
        }
        int copied=0;
        for(String key:oldKeys){
            JSONObject former=responses.getJSONObject(key);
            JSONObject copy=new JSONObject(former.toString());
            if(key.startsWith("/combat/mob/json#")){
                JSONObject battle=new JSONObject(copy.getString("body"));
                battle.getJSONObject("EnemyLayer").put("levelID",Long.toString(MAZE_TRIAL));
                copy.put("body",battle.toString());
            }
            responses.put(key.replace("#"+FORMER_MAZE_ENTRY,"#"+MAZE_TRIAL),copy);
            copied++;
        }
        if(copied!=26)throw new IOException("Preserved maze fixtures incomplete");
        for(Map.Entry<Long,JSONObject> entry:stages.entrySet()){
            JSONObject stage=entry.getValue();
            if(!stage.optBoolean("supported",false))continue;
            String suffix="#"+entry.getKey();
            responses.put("/combat/mob/json"+suffix,new JSONObject()
                .put("type","application/json")
                .put("body",stage.getJSONObject("combatJson").toString()));
            JSONObject mob=stage.getJSONObject("combatMobInfo");
            responses.put("/combat/mob/info"+suffix,new JSONObject()
                .put("type","application/octet-stream")
                .put("base64",mob.getString("base64")));
        }
    }
}
