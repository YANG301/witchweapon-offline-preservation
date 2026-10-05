package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;

/** Isolated protocol/save regression; never connects to or runs the game. */
public final class MazeRepairSelfTest {
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
    private static Map<String,String> form(String... pairs){
        Map<String,String> result=new LinkedHashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)result.put(pairs[i],pairs[i+1]);return result;
    }
    private static JSONObject read(Path path)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(path),StandardCharsets.UTF_8));
    }
    private static JSONObject resource(String name)throws Exception{
        InputStream in=MazeRepairSelfTest.class.getResourceAsStream("/"+name);
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[8192];int n;
        try{while((n=in.read(buf))!=-1)out.write(buf,0,n);}finally{in.close();}
        return new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
    }
    private static void reject(LocalSave save,String path,Map<String,String> form,byte[] seed,JSONObject cat)
            throws Exception{
        try{save.respond(path,form,seed,cat);throw new AssertionError(path+" accepted invalid request");}
        catch(IOException expected){}
    }
    private static long lootAmount(ProtoWire loot,int type)throws Exception{
        long total=0;
        for(ProtoWire.Field f:loot.fields)if(f.number==1){
            ProtoWire item=ProtoWire.parse(f.data);
            if(item.number(1,0)==type)total+=item.number(3,0);
        }return total;
    }
    private static Set<String> statIds(Object object)throws Exception{
        Set<String> result=new HashSet<String>();
        if(object instanceof JSONArray){JSONArray a=(JSONArray)object;for(int i=0;i<a.length();i++)result.addAll(statIds(a.get(i)));}
        else if(object instanceof JSONObject){
            JSONObject value=(JSONObject)object;
            for(Iterator<String> it=value.keys();it.hasNext();){String key=it.next();
                if(key.equals("statID"))result.add(value.getString(key));else result.addAll(statIds(value.get(key)));
            }
        }return result;
    }
    private static void normalizeJson(Object node)throws Exception{
        if(node instanceof JSONArray){JSONArray a=(JSONArray)node;for(int i=0;i<a.length();i++)normalizeJson(a.get(i));}
        else if(node instanceof JSONObject){JSONObject object=(JSONObject)node;
            for(Iterator<String> it=object.keys();it.hasNext();){String key=it.next();
                if(key.equals("statID")){String raw=object.getString(key);object.put(key,raw.substring(0,raw.lastIndexOf('-')+1)+"1");}
                else normalizeJson(object.get(key));
            }
        }
    }
    private static void checkDynamics(JSONObject preserved)throws Exception{
        for(int player:new int[]{1,5,100})for(int round=1;round<=12;round++){
            int level=MazeRules.enemyLevel(player,round);
            JSONObject stage=preserved.getJSONObject("stages").getJSONObject(Long.toString(BarrierLabyrinth.stageForRound(round)));
            JSONObject original=stage.getJSONObject("combatJson");
            JSONObject dynamic=new JSONObject(new String(BarrierLabyrinth.dynamicJson(original.toString().getBytes(StandardCharsets.UTF_8),level),StandardCharsets.UTF_8));
            check(dynamic.getJSONObject("EnemyLayer").getInt("lvMin")==level &&
                dynamic.getJSONObject("EnemyLayer").getInt("lvMax")==level,"JSON enemy level mismatch");
            ProtoWire before=ProtoWire.parse(Base64.decode(stage.getString("combatMobInfo"),Base64.DEFAULT));
            ProtoWire after=ProtoWire.parse(BarrierLabyrinth.dynamicMob(before.bytes(),level));
            check(before.fields.size()==after.fields.size(),"Dynamic basket structure changed");
            Set<String> ids=new HashSet<String>();
            for(int i=0;i<before.fields.size();i++){
                ProtoWire.Field old=before.fields.get(i),now=after.fields.get(i);
                if(old.number!=5){check(Arrays.equals(old.data,now.data) && old.value==now.value,"Non-mob payload changed");continue;}
                ProtoWire oldMob=ProtoWire.parse(old.data),mob=ProtoWire.parse(now.data);
                check(mob.number(3,0)==level,"PB mob level mismatch");
                ids.add(mob.number(6,0)+"-"+mob.number(4,0)+"-"+level);
                for(int stat=30;stat<=34;stat++){
                    long value=oldMob.number(stat,0),scaled=mob.number(stat,0);
                    check(value==0?scaled==0:scaled>=value,"Dynamic growth changed zero or reduced positive stat");
                    oldMob.clear(stat);mob.clear(stat);
                }
                oldMob.clear(3);mob.clear(3);
                check(Arrays.equals(oldMob.bytes(),mob.bytes()),"Dynamic mob changed skills/type/identity");
            }
            check(ids.equals(statIds(dynamic)),"JSON stat IDs do not resolve against PB enemy catalog");
            JSONObject normalized=new JSONObject(dynamic.toString());normalizeJson(normalized);
            JSONObject normalizedOriginal=new JSONObject(original.toString());normalizeJson(normalizedOriginal);
            normalized.getJSONObject("EnemyLayer").put("lvMin",original.getJSONObject("EnemyLayer").getInt("lvMin"))
                .put("lvMax",original.getJSONObject("EnemyLayer").getInt("lvMax"));
            check(normalized.toString().equals(normalizedOriginal.toString()),"Dynamic level changed original layout/AI/waves");
        }
        check(MazeRules.enemyLevel(100,12)==105,"Level100 last maze enemy capped at100");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("seed.json isolated-save-directory");
        Class.forName("com.codex.witchweapon.StandaloneServer",true,MazeRepairSelfTest.class.getClassLoader()).getDeclaredMethods();
        JSONObject responses=read(Paths.get(args[0])),cat=responses.getJSONObject("_catalog");
        byte[] role=Base64.decode(responses.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        checkDynamics(resource("preserved_battle_catalog.json"));
        Path directory=Paths.get(args[1]);Files.createDirectories(directory);
        check(!Files.exists(directory.resolve("offline_save_v1.json")),"Test directory must have no existing save");
        LocalSave save=new LocalSave(directory.toFile());
        ProtoWire initial=ProtoWire.parse(save.respond("/csc/info",form(),role,cat));
        check(initial.integers(7).size()==0 && initial.integers(1).size()==4 &&
            initial.integers(2).size()==4,"Unselected group hides owned servants");
        check(initial.integers(3).size()==16 && initial.integers(4).size()==16 && initial.number(22,0)==1,
            "Initial sixteen-node map/player level wrong");
        ProtoWire grouped=ProtoWire.parse(save.respond("/csc/group",form("svcardids","10010001|10010101|10010201"),role,cat));
        check(grouped.integers(7).size()==3,"Challenge group was not returned");
        reject(save,"/csc/role",form("svcardids","10010301"),role,cat);
        reject(save,"/csc/role",form("svcardids","10010001|10010101|10010201|10010301"),role,cat);
        for(int round=1;round<=3;round++){
            long stage=BarrierLabyrinth.stageForRound(round);
            ProtoWire prepared=ProtoWire.parse(save.respond("/csc/role",form("instid",Long.toString(stage),"svcardids","10010001|10010101"),role,cat));
            check(prepared.integers(1).size()==2,"Single-battle team not separate from challenge group");
            ProtoWire preview=ProtoWire.parse(save.respond("/csc/loot",form(),role,cat));
            check(lootAmount(preview,13)==31272 && lootAmount(preview,3)>0 && lootAmount(preview,10)==5,"Original reward preview missing");
            JSONObject prior=read(directory.resolve("offline_save_v1.json"));
            Map<String,String> result=form("levelid",Long.toString(stage),"state","1","hp",Long.toString(prepared.number(16,1)),
                "servantcardids","10010001|10010101","energys","700|800");
            byte[] won=save.respond("/csc/normal/commit",result,role,cat);
            ProtoWire commit=ProtoWire.parse(won),loot=ProtoWire.parse(commit.data(2));
            check(Arrays.equals(preview.bytes(),loot.bytes()),"Reward preview differs from native CscCommit LootResult");
            JSONObject current=read(directory.resolve("offline_save_v1.json"));
            check(current.getLong("gold")==prior.getLong("gold")+31272 && current.getLong("exp")==prior.getLong("exp")+5,
                "Clear currencies not atomically credited");
            for(ProtoWire.Field f:loot.fields)if(f.number==1){ProtoWire item=ProtoWire.parse(f.data);
                if(item.number(1,0)==3){String id=Long.toString(item.number(2,0));
                    check(current.getJSONObject("items").getLong(id)==prior.getJSONObject("items").optLong(id,0)+1,"Clear item not credited");}
            }
            long revision=current.getLong("saveRevision");
            save=new LocalSave(directory.toFile());
            check(Arrays.equals(won,save.respond("/csc/normal/commit",result,role,cat)) &&
                read(directory.resolve("offline_save_v1.json")).getLong("saveRevision")==revision,"Clear retry double rewarded");
            reject(save,"/csc/group",form("svcardids","10010301"),role,cat);
        }
        ProtoWire chest=ProtoWire.parse(save.respond("/csc/loot",form(),role,cat));
        JSONObject beforeChest=read(directory.resolve("offline_save_v1.json"));
        byte[] claimed=save.respond("/csc/bonus/commit",form(),role,cat);
        check(Arrays.equals(chest.bytes(),ProtoWire.parse(claimed).data(2)),"Chest preview/settlement mismatch");
        JSONObject afterChest=read(directory.resolve("offline_save_v1.json"));
        check(afterChest.getLong("gold")==beforeChest.getLong("gold")+31272 && !afterChest.has("mazePendingBonus"),"Chest reward not credited");
        long revision=afterChest.getLong("saveRevision");
        check(Arrays.equals(claimed,save.respond("/csc/bonus/commit",form(),role,cat)) &&
            read(directory.resolve("offline_save_v1.json")).getLong("saveRevision")==revision,"Chest retry double rewarded");
        for(int round=4;round<=12;round++){
            long stage=BarrierLabyrinth.stageForRound(round);
            ProtoWire prepared=ProtoWire.parse(save.respond("/csc/role",form("instid",Long.toString(stage)),role,cat));
            ProtoWire preview=ProtoWire.parse(save.respond("/csc/loot",form(),role,cat));
            ProtoWire won=ProtoWire.parse(save.respond("/csc/normal/commit",form("levelid",Long.toString(stage),"state","1",
                "hp",Long.toString(prepared.number(16,1)),"servantcardids","","energys",""),role,cat));
            check(Arrays.equals(preview.bytes(),won.data(2)),"Later floor reward mismatch");
            if(round%3==0){
                byte[] bonusPreview=save.respond("/csc/loot",form(),role,cat);
                ProtoWire bonus=ProtoWire.parse(save.respond("/csc/bonus/commit",form(),role,cat));
                check(Arrays.equals(bonusPreview,bonus.data(2)),"Later chest reward mismatch");
            }
        }
        JSONObject complete=read(directory.resolve("offline_save_v1.json"));
        check(complete.getInt("mazeRound")==13 && complete.getInt("mazeCompletedRuns")==1 &&
            complete.getInt("mazeSupplyBoxes")==4 && complete.getLong("gold")==1000+16*31272L,
            "Completed run lost floor/chest rewards");
        check(ProtoWire.parse(save.respond("/csc/info",form(),role,cat)).number(24,0)==17 &&
            save.respond("/csc/loot",form(),role,cat).length==0,"Completed native maze cursor/reward preview incorrect");
        ProtoWire reset=ProtoWire.parse(save.respond("/csc/reset",form(),role,cat));
        check(reset.integers(7).size()==0 && reset.integers(1).size()==4 && reset.number(24,0)==1,"Reset does not reopen owned selection");
        JSONObject legacy=new JSONObject(afterChest.toString()).put("mazeRound",7).put("mazeParty",new JSONArray().put(10010001));
        legacy.remove("mazeRoster");legacy.remove("mazeRosterLocked");legacy.remove("mazeGroupVersion");
        BarrierLabyrinth.migrateGroup(legacy);
        check(BarrierLabyrinth.availableServants(legacy).size()==4 && legacy.getInt("mazeRound")==7 &&
            legacy.getJSONArray("mazeParty").getLong(0)==10010001,"Legacy small team migration lost progress or selectable servants");
        JSONObject migrated=BarrierLabyrinth.group(legacy,form("svcardids","10010101|10010201"),role,0,1).state;
        check(!migrated.has("mazeParty") && BarrierLabyrinth.selectBattleParty(migrated,null).size()==2 &&
            migrated.getInt("mazeRound")==7,"Legacy remembered team blocked a valid replacement challenge group");
        JSONObject maximum=new JSONObject().put("starterProfile",1).put("exp",Long.MAX_VALUE);
        check(MazeRules.roleLevel(maximum,cat)==100,"Enemy rules confuse player level with servant level");
        JSONObject pool=new JSONObject();ArrayList<Long> poolIds=new ArrayList<Long>();
        for(Iterator<String> it=cat.getJSONObject("servants").keys();it.hasNext() && poolIds.size()<13;){
            String id=it.next();pool.put(id,cat.getJSONObject("servants").getString(id));poolIds.add(Long.parseLong(id));
        }
        check(poolIds.size()==13,"Seed lacks enough servants for challenge-group cap test");
        JSONObject unlocked=new JSONObject().put("ownedServants",pool);
        check(BarrierLabyrinth.availableServants(unlocked).size()==13,"Unlocked selection is incorrectly capped at battle/group size");
        StringJoiner twelve=new StringJoiner("|");for(int i=0;i<12;i++)twelve.add(Long.toString(poolIds.get(i)));
        JSONObject twelveGroup=BarrierLabyrinth.group(unlocked,form("svcardids",twelve.toString()),role,0,1).state;
        check(BarrierLabyrinth.availableServants(twelveGroup).size()==12,"Twelve-card challenge group rejected");
        BarrierLabyrinth.selectBattleParty(twelveGroup,poolIds.get(9)+"|"+poolIds.get(10)+"|"+poolIds.get(11));
        check(twelveGroup.getJSONArray("mazeRoster").length()==12 && twelveGroup.getJSONArray("mazeParty").length()==3,
            "Single-battle selection overwrote twelve-card challenge group");
        try{
            BarrierLabyrinth.group(unlocked,form("svcardids",twelve+"|"+poolIds.get(12)),role,0,1);
            throw new AssertionError("Thirteen-card group accepted");
        }catch(IOException expected){}
        JSONObject vip=new JSONObject(complete.toString()).put("vipExp",13000).put("mazePreparedRoleLevel",1);
        long beforeVip=vip.getLong("gold");
        ProtoWire vipLoot=MazeRules.loot(vip,cat,3,true,true);
        check(lootAmount(vipLoot,13)==62544 && vip.getLong("gold")==beforeVip+62544 &&
            lootAmount(vipLoot,3)>0 && lootAmount(vipLoot,3)%2==0,"Original VIP double-chest benefit lost");
        JSONObject report=new JSONObject().put("result","MAZE_REPAIR_SELF_TEST_OK").put("dynamicCases",36)
            .put("nativeMapEntries",16).put("ownedSelection",true).put("challengeGroupAndBattleTeamSeparated",true)
            .put("legacyProgressPreserved",true).put("nativeRewardAndInventoryAgree",true).put("retrySafe",true)
            .put("completedRounds",12).put("checkpointClaims",4).put("vipDoubleChest",true)
            .put("standaloneServerClassVerified",true)
            .put("itemQuantityRule","original listed IDs, reconstructed one each");
        System.out.println(report.toString());
    }
}
