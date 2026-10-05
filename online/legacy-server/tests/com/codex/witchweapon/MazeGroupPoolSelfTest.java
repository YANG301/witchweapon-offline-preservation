package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import com.codex.witchweapon.host.Base64;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.io.IOException;

/** Native confirmed-group boundary with more owned cards than the twelve-card limit. */
public final class MazeGroupPoolSelfTest {
    private static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
    private static Map<String,String> form(String... values){Map<String,String> out=new LinkedHashMap<String,String>();
        for(int i=0;i<values.length;i+=2)out.put(values[i],values[i+1]);return out;}
    private static String ids(List<Long> ids){StringJoiner out=new StringJoiner("|");for(long id:ids)out.add(Long.toString(id));return out.toString();}
    private static JSONObject read(Path path)throws Exception{return new JSONObject(new String(Files.readAllBytes(path),StandardCharsets.UTF_8));}
    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("seed.json isolated-root");
        Class.forName("com.codex.witchweapon.StandaloneServer",true,MazeGroupPoolSelfTest.class.getClassLoader()).getDeclaredMethods();
        JSONObject seed=read(Paths.get(args[0])),catalog=seed.getJSONObject("_catalog");
        byte[] role=Base64.decode(seed.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        ArrayList<Long> all=new ArrayList<Long>();for(Iterator<String> it=catalog.getJSONObject("servants").keys();it.hasNext();)all.add(Long.parseLong(it.next()));Collections.sort(all);
        check(all.size()>=24,"Need original owned templates for 24-card case");
        int cases=0;
        for(int count:new int[]{1,4,12,13,24}){
            Path directory=Paths.get(args[1]).resolve("owned"+count);Files.createDirectories(directory);
            Path file=directory.resolve("offline_save_v1.json");check(!Files.exists(file),"Existing save forbidden");
            JSONObject owned=new JSONObject();for(int i=0;i<count;i++){String id=Long.toString(all.get(i));owned.put(id,catalog.getJSONObject("servants").getString(id));}
            JSONObject state=new JSONObject().put("version",1).put("roleCreated",true).put("starterProfile",1).put("name","GroupCheck")
                .put("ownedServants",owned).put("items",new JSONObject()).put("equips",new JSONObject()).put("gold",1000).put("rmb",0).put("exp",0)
                .put("stamina",200).put("mazeGroupVersion",1).put("mazeRosterLocked",false).put("mazeRound",7).put("mazeHP",0.4)
                .put("mazeWins",6).put("mazeEnergy_"+all.get(count-1),555);
            Files.write(file,(state.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            LocalSave save=new LocalSave(directory.toFile());
            ProtoWire info=ProtoWire.parse(save.respond("/csc/info",form(),role,catalog));
            check(info.integers(7).isEmpty(),"Unconfirmed owned pool became selected/locked group");
            check(info.integers(1).size()==count && info.integers(2).size()==count,"Full owned energy pool missing");
            int finalIndex=info.integers(1).indexOf(all.get(count-1));check(info.integers(2).get(finalIndex)==555,"Existing owned energy lost");
            check(info.number(24,0)==9 && read(file).getInt("mazeWins")==6 && read(file).getDouble("mazeHP")==0.4,"Info reset existing progress");
            // Choose a card outside a hypothetical first-twelve default pool.
            ArrayList<Long> group=new ArrayList<Long>();group.add(all.get(count-1));
            for(int i=0;i<count && group.size()<12;i++)if(!group.contains(all.get(i)))group.add(all.get(i));
            ProtoWire confirmed=ProtoWire.parse(save.respond("/csc/group",form("svcardids",ids(group)),role,catalog));
            check(confirmed.integers(7).equals(group) && confirmed.integers(7).size()<=12,"Confirmed full-inventory choice not preserved");
            check(read(file).getInt("mazeRound")==7 && read(file).getInt("mazeWins")==6,"Group confirmation reset maze progress");
            List<Long> battle=group.subList(0,Math.min(4,group.size()));
            ProtoWire prepared=ProtoWire.parse(save.respond("/csc/role",form("instid",Long.toString(BarrierLabyrinth.stageForRound(7)),"svcardids",ids(battle)),role,catalog));
            check(prepared.integers(1).equals(battle),"Native four-slot party was rejected or truncated");
            if(group.size()>4){
                try{save.respond("/csc/role",form("svcardids",ids(group.subList(0,5))),role,catalog);throw new AssertionError("Five-card battle accepted");}
                catch(IOException expected){}
            }
            StringJoiner energy=new StringJoiner("|");for(long id:battle)energy.add("600");
            byte[] response=save.respond("/csc/normal/commit",form("levelid",Long.toString(BarrierLabyrinth.stageForRound(7)),"state","0","hp",Long.toString(prepared.number(16,1)),"servantcardids",ids(battle),"energys",energy.toString()),role,catalog);
            check(ProtoWire.parse(response).data(1).length>0 && read(file).getInt("mazeRound")==7,"Four-card energy settlement failed");
            check(read(file).getJSONArray("mazeParty").length()==battle.size(),"Single party changed twelve-card roster");
            cases++;
        }
        JSONObject old=new JSONObject().put("ownedServants",catalog.getJSONObject("servants")).put("mazeRound",7)
            .put("mazeParty",new JSONArray(all.subList(0,4)));
        BarrierLabyrinth.migrateGroup(old);
        check(!old.optBoolean("mazeRosterLocked",true) && old.getJSONArray("mazeParty").length()==4 &&
            BarrierLabyrinth.selectedGroup(old).isEmpty(),"Old four-card battle team was mistaken for confirmed maze group");
        System.out.println(new JSONObject().put("result","MAZE_GROUP_POOL_SELF_TEST_OK").put("ownedCounts",new JSONArray(new int[]{1,4,12,13,24}))
            .put("cases",cases).put("unconfirmedField7Count",0).put("fullInventoryEnergyRetained",true).put("outsideFirstTwelveCanJoin",true)
            .put("fourCardPrepareAndSettlement",true).put("fiveCardRejected",true).put("legacyFourCardPartyMigrated",true).put("progressPreserved",true));
    }
}
