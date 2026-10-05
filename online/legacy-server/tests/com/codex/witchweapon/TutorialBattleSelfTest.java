package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Checks restored tutorial identities and persistence without a live account. */
public final class TutorialBattleSelfTest {
    private static void check(boolean success,String message){
        if(!success)throw new AssertionError(message);
    }
    private static Map<String,String> form(String... fields){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<fields.length;i+=2)result.put(fields[i],fields[i+1]);
        return result;
    }
    private static JSONObject state(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }
    private static void battle(LocalSave save,long stage,String request,boolean win)throws Exception{
        save.respond("/level/startBattle",form("instanceid",Long.toString(stage),
            "idempotency",request),new byte[0],null);
        save.respond("/level/pushGuideProgress",form("instanceid",Long.toString(stage),
            "pass",win?"1":"0"),new byte[0],null);
    }
    private static byte[] navigation(File file,String graph,int expectedSize,
            String label)throws Exception{
        // These mapinfo fixtures are byte-for-byte copies of the original APK.
        try(ZipFile zip=new ZipFile(file)){
            ZipEntry entry=zip.getEntry(graph);
            check(entry!=null && entry.getSize()==expectedSize,
                "Original "+label+" graph missing");
            byte[] data=new byte[(int)entry.getSize()];
            try(InputStream input=zip.getInputStream(entry)){
                int read=0;
                while(read<data.length){
                    int count=input.read(data,read,data.length-read);
                    check(count>0,"Truncated "+label+" graph");
                    read+=count;
                }
                check(input.read()==-1,label+" graph has trailing data");
            }
            return data;
        }
    }
    private static boolean fullyLinked(ByteBuffer nodes,int index){
        int offset=4+22*index;
        return (nodes.getInt(offset+4)&1)==1 &&
            (nodes.getShort(offset+20)&0x1ff)==0x1ff;
    }
    private static boolean[] connectedOverbridgeNodes(ByteBuffer nodes,int count){
        // Original graph0 metadata: width 56.1 / nodeSize 1.7 = 33 columns,
        // height 11.9 / nodeSize 1.7 = 7 rows. Traverse only nodes that
        // advertise all eight grid connections, a conservative subset.
        int width=33,height=7,birth=134;
        check(count==width*height && fullyLinked(nodes,birth),
            "Overbridge birth node or graph dimensions changed");
        boolean[] visited=new boolean[count];
        int[] queue=new int[count];
        int head=0,tail=0;
        queue[tail++]=birth;visited[birth]=true;
        int[][] directions={{-1,0},{1,0},{0,-1},{0,1}};
        while(head<tail){
            int current=queue[head++];
            int col=current%width,row=current/width;
            for(int[] direction:directions){
                int nextCol=col+direction[0],nextRow=row+direction[1];
                if(nextCol<0 || nextCol>=width || nextRow<0 || nextRow>=height)
                    continue;
                int next=nextRow*width+nextCol;
                if(!visited[next] && fullyLinked(nodes,next)){
                    visited[next]=true;queue[tail++]=next;
                }
            }
        }
        return visited;
    }
    private static void checkOverbridgeSpawns(JSONArray monsters,byte[] nav)throws Exception{
        ByteBuffer nodes=ByteBuffer.wrap(nav).order(ByteOrder.LITTLE_ENDIAN);
        int count=nodes.getInt(0);
        check(count==231 && nav.length==4+22*count,
            "Unexpected overbridge graph shape");
        boolean[] connected=connectedOverbridgeNodes(nodes,count);
        int[] expectedNodes={135,101,102,136,103};
        check(monsters.length()==expectedNodes.length,"Overbridge enemy count changed");
        double[] xs=new double[monsters.length()],zs=new double[monsters.length()];
        for(int i=0;i<monsters.length();i++){
            JSONArray prs=monsters.getJSONObject(i).getJSONArray("PRS");
            double x=prs.getDouble(0),z=prs.getDouble(1);
            xs[i]=x;zs[i]=z;
            check(x>=3.5 && x<=6.7 && z>=-7.8 && z<=-4.2,
                "Overbridge spawn left the collision-cleared birth area");
            double fromBirth=Math.hypot(x-2.74,z+5.5);
            check(fromBirth>=1.4 && fromBirth<=4.0,
                "Overbridge enemy too close to or far from the original birthPoint");
            int nearest=-1;double distance=Double.POSITIVE_INFINITY;
            for(int node=0;node<count;node++){
                int offset=4+22*node;
                double nx=nodes.getInt(offset+8)/1000.0;
                double nz=nodes.getInt(offset+16)/1000.0;
                double d=Math.hypot(x-nx,z-nz);
                if(d<distance){distance=d;nearest=node;}
            }
            check(nearest==expectedNodes[i] && distance<0.02,
                "Overbridge spawn does not match the selected original nav node");
            check(fullyLinked(nodes,nearest) && connected[nearest],
                "Overbridge spawn is unwalkable or disconnected from birth");
            for(int previous=0;previous<i;previous++)
                check(Math.hypot(x-xs[previous],z-zs[previous])>=1.6,
                    "Overbridge enemies overlap each other");
        }
        // The former first two placements at z=-1.5 were not walkable.
        for(int oldNode:new int[]{201,202}){
            int offset=4+22*oldNode;
            check((nodes.getInt(offset+4)&1)==0 &&
                (nodes.getShort(offset+20)&0xffff)==0,
                "Original overbridge nav control node changed");
        }
    }
    private static boolean[] connectedWalkableNodes(ByteBuffer nodes,int width,
            int height,int birth)throws Exception{
        int count=nodes.getInt(0);
        check(count==width*height,"Original nav grid dimensions changed");
        int offset=4+22*birth;
        check((nodes.getInt(offset+4)&1)==1,"Original nav entry is not walkable");
        boolean[] visited=new boolean[count];
        int[] queue=new int[count];int head=0,tail=0;
        visited[birth]=true;queue[tail++]=birth;
        int[][] directions={{-1,0},{1,0},{0,-1},{0,1}};
        while(head<tail){
            int current=queue[head++];int col=current%width,row=current/width;
            for(int[] direction:directions){
                int nc=col+direction[0],nr=row+direction[1];
                if(nc<0||nc>=width||nr<0||nr>=height)continue;
                int next=nr*width+nc,nextOffset=4+22*next;
                if(!visited[next] && (nodes.getInt(nextOffset+4)&1)==1 &&
                        (nodes.getShort(nextOffset+20)&0xffff)>0){
                    visited[next]=true;queue[tail++]=next;
                }
            }
        }
        return visited;
    }
    private static int nearestNode(ByteBuffer nodes,double x,double z)throws Exception{
        return nearestNode(nodes,x,z,0.45);
    }
    private static int nearestNode(ByteBuffer nodes,double x,double z,double tolerance)
            throws Exception{
        int nearest=-1;double distance=Double.POSITIVE_INFINITY;
        for(int node=0;node<nodes.getInt(0);node++){
            int offset=4+22*node;
            double nx=nodes.getInt(offset+8)/1000.0,nz=nodes.getInt(offset+16)/1000.0;
            double d=Math.hypot(x-nx,z-nz);
            if(d<distance){distance=d;nearest=node;}
        }
        check(nearest>=0 && distance<tolerance,
            "Combat position misses the original nav grid: x="+x+", z="+z+
                ", nearest="+nearest+", distance="+distance);
        return nearest;
    }
    private static void checkSmelterWaves(JSONArray zones,byte[] nav0,byte[] nav1)
            throws Exception{
        check(zones.length()==2,"First-show guide must contain two zones");
        check(zones.getJSONObject(0).getString("name").equals("Zone_0") &&
            zones.getJSONObject(1).getString("name").equals("Zone_1"),
            "Original lesson zone event numbering changed");
        JSONArray opening=zones.getJSONObject(0).getJSONArray("waves");
        JSONArray corridor=zones.getJSONObject(1).getJSONArray("waves");
        check(opening.length()==2 && corridor.length()==1,
            "Lesson01001 requires combat-field events 1102 and 1201");
        check(opening.getJSONObject(0).getString("name").equals("Wave_0") &&
            opening.getJSONObject(1).getString("name").equals("Wave_1") &&
            corridor.getJSONObject(0).getString("name").equals("Wave_0"),
            "Guide wave event numbering changed");
        check(opening.getJSONObject(0).getJSONArray("monsters").length()==2 &&
            opening.getJSONObject(1).getJSONArray("monsters").length()==1 &&
            corridor.getJSONObject(0).getJSONArray("monsters").length()==2,
            "Unexpected staged monster count");
        JSONArray[] waves={opening.getJSONObject(0).getJSONArray("monsters"),
            opening.getJSONObject(1).getJSONArray("monsters"),
            corridor.getJSONObject(0).getJSONArray("monsters")};
        for(JSONObject wave:new JSONObject[]{opening.getJSONObject(0),
                opening.getJSONObject(1),corridor.getJSONObject(0)}){
            JSONArray triggers=wave.getJSONArray("NextWaveTriggers");
            check(triggers.length()==1 &&
                triggers.getJSONObject(0).getString("type").equals("WaveClear"),
                "Guide wave must advance only after its enemies clear");
        }
        ByteBuffer graph0=ByteBuffer.wrap(nav0).order(ByteOrder.LITTLE_ENDIAN);
        ByteBuffer graph1=ByteBuffer.wrap(nav1).order(ByteOrder.LITTLE_ENDIAN);
        check(graph0.getInt(0)==280 && nav0.length==6164 &&
            graph1.getInt(0)==420 && nav1.length==9244,
            "Unexpected original smelter nav shape");
        boolean[] arenaConnected=connectedWalkableNodes(graph1,20,21,214);
        boolean[] corridorConnected=connectedWalkableNodes(graph0,8,35,276);
        int[][] expected={{212,217},{152},{227,245}};
        java.util.HashSet<String> identities=new java.util.HashSet<String>();
        for(int group=0;group<waves.length;group++){
            ByteBuffer nodes=group<2?graph1:graph0;
            boolean[] connected=group<2?arenaConnected:corridorConnected;
            for(int i=0;i<waves[group].length();i++){
                JSONObject monster=waves[group].getJSONObject(i);
                check(identities.add(monster.getString("statID")),
                    "One source monster appears in multiple guide waves");
                JSONArray prs=monster.getJSONArray("PRS");
                double x=prs.getDouble(0),z=prs.getDouble(1);
                int node=nearestNode(nodes,x,z);
                check(node==expected[group][i] && connected[node],
                    "Guide wave monster is off its connected original nav graph");
                if(group<2)check(x>=1 && x<=4.5 && z>=-7.5 && z<=-5.3,
                    "Opening wave left the original birth area");
                else check(x>=-1 && x<=1 && z>=-16.2 && z<=-14.0,
                    "Second zone left the smelter corridor");
            }
        }
        check(identities.size()==5,"First-show stage lost a source monster");
        JSONArray entry=zones.getJSONObject(1).getJSONArray("entryPR");
        JSONArray trigger=zones.getJSONObject(1).getJSONArray("triggers")
            .getJSONObject(0).getJSONArray("PRS");
        check(nearestNode(graph0,entry.getDouble(0),entry.getDouble(2))==268 &&
            Math.abs(trigger.getDouble(1)+11.4)<0.001,
            "Second-zone entrance misses the original corridor handoff");
        // The two graph meshes approach within 0.28 m at the seam. This
        // validates map placement, not an undocumented original A* link.
        check(Math.hypot(0.09-0.051,-11.44+11.167)<0.30,
            "Original smelter nav graph seam changed");
        int oldNode=354,offset=4+22*oldNode;
        check(graph1.getInt(offset+4)==131072 &&
            (graph1.getShort(offset+20)&0xffff)==0,
            "Original smelter nav control node changed");
    }
    private static void checkBasestationWaves(JSONArray zones,byte[] nav)
            throws Exception {
        // lesson00001 uses events 1201 and 1301/1302/1303. Those are the
        // first wave of Zone_1 and three successive waves of Zone_2.
        check(zones.length()==3,"Basestation lesson needs three combat zones");
        int[] waveCounts={1,1,3};
        for(int z=0;z<zones.length();z++){
            JSONObject zone=zones.getJSONObject(z);
            check(zone.getString("name").equals("Zone_"+z) &&
                zone.getJSONArray("waves").length()==waveCounts[z],
                "Basestation zone/wave event numbering changed");
            JSONArray waves=zone.getJSONArray("waves");
            for(int w=0;w<waves.length();w++){
                JSONObject wave=waves.getJSONObject(w);
                check(wave.getString("name").equals("Wave_"+w) &&
                    wave.getJSONArray("NextWaveTriggers").getJSONObject(0)
                        .getString("type").equals("WaveClear"),
                    "Basestation guide wave does not advance on clear");
            }
        }
        JSONArray second=zones.getJSONObject(1).getJSONArray("waves")
            .getJSONObject(0).getJSONArray("monsters");
        JSONArray third=zones.getJSONObject(2).getJSONArray("waves");
        check(second.getJSONObject(2).getString("name").equals("434 #4") &&
            third.getJSONObject(0).getJSONArray("monsters").getJSONObject(0)
                .getString("name").equals("432 #12") &&
            third.getJSONObject(1).getJSONArray("monsters").getJSONObject(0)
                .getString("name").equals("432 #18"),
            "lesson00001 CreateMobTap targets are missing");
        ByteBuffer graph=ByteBuffer.wrap(nav).order(ByteOrder.LITTLE_ENDIAN);
        check(graph.getInt(0)==714 && nav.length==4+22*714,
            "Original basestation graph shape changed");
        boolean[] connected=connectedWalkableNodes(graph,42,17,423);
        // The map's authored birthPoint is (0,0), 0.577 m from grid node 423.
        check(nearestNode(graph,0,0,0.70)==423 && connected[423],
            "Basestation birthPoint is not on the original connected graph");
        int[] entranceNodes={423,429,439};
        for(int z=0;z<zones.length();z++){
            JSONArray entry=zones.getJSONObject(z).getJSONArray("entryPR");
            int node=nearestNode(graph,entry.getDouble(0),entry.getDouble(2),
                z==0?0.70:0.45);
            check(node==entranceNodes[z] && connected[node],
                "Basestation zone entrance left the original walkable route");
        }
        int[] spawnNodes={425,390,392,391,360,361,362,364};
        int index=0;
        java.util.HashSet<String> sourceIds=new java.util.HashSet<String>();
        for(int z=0;z<zones.length();z++){
            JSONArray waves=zones.getJSONObject(z).getJSONArray("waves");
            for(int w=0;w<waves.length();w++){
                JSONArray mobs=waves.getJSONObject(w).getJSONArray("monsters");
                for(int m=0;m<mobs.length();m++){
                    JSONObject mob=mobs.getJSONObject(m);
                    sourceIds.add(mob.getString("statID").split("-")[0]);
                    JSONArray prs=mob.getJSONArray("PRS");
                    int node=nearestNode(graph,prs.getDouble(0),prs.getDouble(1));
                    check(index<spawnNodes.length && node==spawnNodes[index++] &&
                        connected[node],"Basestation spawn is off the original nav route");
                }
            }
        }
        check(index==spawnNodes.length && sourceIds.contains("331010343201") &&
            sourceIds.contains("331010344303") &&
            sourceIds.contains("331010240801") &&
            sourceIds.contains("331010344401") &&
            sourceIds.contains("331010343701") &&
            sourceIds.contains("332010343402") && sourceIds.size()==6,
            "Basestation lost a source monster or the scripted mob 434 target");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2 && args.length!=3)
            throw new IllegalArgumentException("Arguments: test-dir responses.json [mapinfo-zip]");
        File directory=new File(args[0]);
        check(directory.isDirectory()&&directory.list().length==0,"Empty test directory required");
        File mapInfo=args.length==3?new File(args[2]):new File(new File(args[1])
            .getParentFile(),"../tests/fixtures/mapinfo_1028_smelter.bytes");
        byte[] smelterNav0=navigation(mapInfo,"graph0_extra.binary",6164,"smelter corridor");
        byte[] smelterNav1=navigation(mapInfo,"graph1_extra.binary",9244,"smelter arena");
        File overbridgeInfo=new File(mapInfo.getParentFile(),
            "mapinfo_1000_overbridge.bytes");
        byte[] overbridgeNav=navigation(overbridgeInfo,
            "graph0_extra.binary",5086,"overbridge");
        File basestationInfo=new File(mapInfo.getParentFile(),
            "mapinfo_1020_basestation2.bytes");
        byte[] basestationNav=navigation(basestationInfo,
            "graph0_extra.binary",15712,"basestation");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[1]).toPath()),StandardCharsets.UTF_8));
        int originalCount=responses.length();
        TutorialBattleFixtures.install(responses);
        check(responses.length()==originalCount+8,"Four encounter fixture pairs expected");
        long[] fixtureStages={3150001001L,3150001004L,3150001005L,3150001006L};
        String[] scenes={"map_1020_basestation","map_1028_smelter",
            "map_1000_overbridge","map_1013_groofbroken"};
        int[] waveCounts={8,5,5,2},basketCounts={6,5,5,2};
        for(int i=0;i<fixtureStages.length;i++){
            String suffix="#"+fixtureStages[i];
            JSONObject level=new JSONObject(responses.getJSONObject("/combat/mob/json"+suffix)
                .getString("body"));
            check(level.getJSONObject("MapInfo").getString("sceneName").equals(scenes[i]),
                "Wrong tutorial map");
            check(level.getJSONObject("EnemyLayer").getString("levelID").equals(
                Long.toString(fixtureStages[i])),"Wrong level ID");
            JSONArray zones=level.getJSONObject("EnemyLayer").getJSONArray("areas")
                .getJSONObject(0).getJSONArray("zones");
            int monsterCount=0;
            for(int zone=0;zone<zones.length();zone++){
                JSONArray waves=zones.getJSONObject(zone).getJSONArray("waves");
                for(int wave=0;wave<waves.length();wave++)
                    monsterCount+=waves.getJSONObject(wave).getJSONArray("monsters").length();
            }
            check(monsterCount==waveCounts[i],"Wrong guide wave monster count");
            if(i==0)checkBasestationWaves(zones,basestationNav);
            if(i==1)checkSmelterWaves(zones,smelterNav0,smelterNav1);
            if(i==2)checkOverbridgeSpawns(zones.getJSONObject(0)
                .getJSONArray("waves").getJSONObject(0).getJSONArray("monsters"),overbridgeNav);
            ProtoWire basket=ProtoWire.parse(Base64.decode(responses
                .getJSONObject("/combat/mob/info"+suffix).getString("base64"),Base64.DEFAULT));
            int mobCount=0,typeCount=0;
            for(ProtoWire.Field field:basket.fields){
                if(field.number==5){mobCount++;
                    ProtoWire mob=ProtoWire.parse(field.data);
                    check(mob.number(6,0)>0&&mob.data(9).length>0,"Missing mob identity");
                }
                if(field.number==6)typeCount++;
            }
            check(mobCount==basketCounts[i]&&typeCount==basketCounts[i],
                "Basket does not cover the source monster list");
        }
        long[] stages={3150001001L,3150001005L,3150001006L};
        LocalSave save=new LocalSave(directory);
        save.roleSummary();
        byte[] beforeStart=Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath());
        try{
            save.respond("/level/pushGuideProgress",form("pass","1"),new byte[0],null);
            throw new AssertionError("Unstarted guide battle settled");
        }catch(java.io.IOException expected){}
        check(Arrays.equals(beforeStart,Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath())),
            "Rejected guide settlement changed the save");
        save.respond("/level/startBattle",form("instanceid",Long.toString(stages[0]),
            "idempotency","guide-1"),new byte[0],null);
        try{
            save.respond("/level/pushGuideProgress",form("instanceid",Long.toString(stages[1]),
                "pass","1"),new byte[0],null);
            throw new AssertionError("Another guide stage settled the active battle");
        }catch(java.io.IOException expected){}
        save.respond("/level/pushGuideProgress",form("instanceid",Long.toString(stages[0]),
            "pass","1"),new byte[0],null);
        JSONObject afterFirst=state(directory);
        check(afterFirst.getInt("tutorialWins_"+stages[0])==1,"First guide win missing");
        check(afterFirst.getLong("exp")==5,"Guide battle should grant only five experience");
        byte[] beforeRetry=Files.readAllBytes(new File(directory,"offline_save_v1.json").toPath());
        save.respond("/level/pushGuideProgress",form("instanceid",Long.toString(stages[0]),
            "pass","1"),new byte[0],null);
        check(Arrays.equals(beforeRetry,Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath())),
            "Duplicate guide result changed the save");
        try{
            save.respond("/level/startBattle",form("instanceid",Long.toString(stages[0]),
                "idempotency","guide-1-replay"),new byte[0],null);
            throw new AssertionError("One-time opening battle was replayed after victory");
        }catch(java.io.IOException expected){}
        check(Arrays.equals(beforeRetry,Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath())),
            "Rejected opening-battle replay changed the save");
        LocalSave loaded=new LocalSave(directory);
        loaded.respond("/level/pushGuideProgress",form("instanceid",Long.toString(stages[0]),
            "pass","1"),new byte[0],null);
        check(state(directory).getInt("tutorialWins_"+stages[0])==1,
            "Restart replay awarded a second guide win");
        battle(loaded,stages[1],"guide-2-loss",false);
        check(state(directory).optInt("tutorialWins_"+stages[1])==0,
            "Failed guide battle counted as a win");
        battle(loaded,stages[1],"guide-2-win",true);
        battle(loaded,stages[2],"guide-3-win",true);
        JSONObject completedCombats=state(directory);
        check(completedCombats.getInt("tutorialWins_"+stages[1])==1 &&
            completedCombats.getInt("tutorialWins_"+stages[2])==1,
            "Guide wins did not persist independently");
        check(completedCombats.getLong("exp")==15 &&
            completedCombats.optBoolean("namePending",true),
            "Three guide steps skipped naming or advanced levels too early");
        loaded.respond("/level/startBattle",form("instanceid",Long.toString(LocalSave.STAGE),
            "idempotency","before-name"),new byte[0],null);
        loaded.respond("/level/pushMainLineProgress",form(
            "instanceid",Long.toString(LocalSave.STAGE),"pass","1","stars","3"),
            new byte[0],null);
        check(state(directory).getLong("exp")==20,
            "Catch-up experience was granted before guide naming");
        loaded.respond("/role/create",form(),Base64.decode(
            responses.getJSONObject("/role/create").getString("base64"),Base64.DEFAULT),
            responses.getJSONObject("_catalog"));
        loaded.respond("/role/rename",form("rolename","教程完成玩家"),new byte[0],
            responses.getJSONObject("_catalog"));
        loaded.respond("/level/startBattle",form("instanceid",Long.toString(LocalSave.STAGE),
            "idempotency","after-name"),new byte[0],null);
        loaded.respond("/level/pushMainLineProgress",form(
            "instanceid",Long.toString(LocalSave.STAGE),"pass","1","stars","3"),
            new byte[0],null);
        check(state(directory).getLong("exp")==25,
            "Post-guide battle experience did not follow guide battles and naming");
        System.out.println("TutorialBattleSelfTest OK");
    }
}
