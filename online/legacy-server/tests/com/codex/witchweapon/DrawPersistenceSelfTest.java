package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.Random;

/** Actual draw receipts, duplicate stacks, star promotion and disk/retry boundaries. */
public final class DrawPersistenceSelfTest {
    private static int checks;
    private static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);return result;
    }
    private static JSONObject read(File file)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
    }
    private static JSONObject role(JSONObject cat)throws Exception{
        JSONObject result=new JSONObject().put("version",1).put("starterProfile",1).put("roleCreated",true)
            .put("name","PersistenceTest").put("gold",10000000L).put("rmb",0).put("exp",0)
            .put("ownedServants",new JSONObject()).put("items",new JSONObject()).put("equips",new JSONObject());
        LocalEconomy.init(result,cat);result.getJSONObject("items").put("40350003",1000);return result;
    }
    private static Random weaponRoll(final int category,final int index){
        return new Random(){@Override public int nextInt(int bound){
            if(bound==10000)return category==0?0:category==1?70:420;
            return index;
        }};
    }
    private static void own(JSONObject state,JSONObject cat,long wid)throws Exception{
        LocalEconomy.grantItemReward(state,cat,new JSONObject().put("type",4).put("id",wid).put("value",1).put("count",1),1);
    }
    private static void delta(JSONObject before,JSONObject after,JSONObject expected)throws Exception{
        for(Iterator<String> keys=expected.keys();keys.hasNext();){String id=keys.next();
            check(after.optLong(id)-before.optLong(id)==expected.getLong(id),"Authoritative duplicate reward missing: "+id);
        }
    }
    private static JSONObject expected(JSONObject cat,JSONObject rules,long weapon,boolean duplicate)throws Exception{
        JSONObject def=cat.getJSONObject("weapons").getJSONObject(Long.toString(weapon));
        JSONObject result=new JSONObject();String fragment=Long.toString(rules.getJSONObject("servantPieces")
            .getLong(Long.toString(def.getLong("servant"))));
        result.put(fragment,rules.getJSONObject("fragmentCounts").getLong(Integer.toString(def.getInt("rare"))));
        if(duplicate){
            JSONObject reward=rules.getJSONObject("decomposition").getJSONObject(Long.toString(weapon));
            JSONArray materials=reward.getJSONArray("materials");
            for(int i=0;i<=materials.length();i++){
                JSONArray item=i==materials.length()?reward.getJSONArray("knifeStone"):materials.getJSONArray(i);
                String id=Long.toString(item.getLong(0));result.put(id,result.optLong(id)+item.getLong(1));
            }
        }
        return result;
    }
    public static void main(String[] args)throws Exception{
        check(args.length==3,"Pass responses, prayer rules and fresh temporary directory");
        JSONObject cat=read(new File(args[0])).getJSONObject("_catalog"),rules=read(new File(args[1]));
        long now=1700000000L;
        // Every permanent weapon: first acquisition, real duplicate, original
        // two-entry display and an uncertain retry which never grants twice.
        for(int category=0;category<3;category++){
            java.util.List<Long> pool=NormalDrawRates.weaponPool(category,cat);
            for(int index=0;index<pool.size();index++){
                long wid=pool.get(index);JSONObject s=role(cat);
                LocalEconomy.draw(s,cat,"/draw/rmb/single",form("idempotency","first"),weaponRoll(category,index),now);
                check(PrayerShop.ownedWeapons(s).contains(wid),"First weapon not owned");
                long sid=cat.getJSONObject("weapons").getJSONObject(Long.toString(wid)).getLong("servant");
                String fragment=Long.toString(rules.getJSONObject("servantPieces").getLong(Long.toString(sid)));
                check(s.getJSONObject("items").optLong(fragment)==0,"First witch unexpectedly decomposed");
                JSONObject before=new JSONObject(s.getJSONObject("items").toString());
                byte[] reply=LocalEconomy.draw(s,cat,"/draw/rmb/single",form("idempotency","duplicate"),weaponRoll(category,index),now+1);
                check(ProtoWire.parse(reply).fields.size()==2,"Duplicate changed the number of displayed draws");
                delta(before,s.getJSONObject("items"),expected(cat,rules,wid,true));
                String snapshot=s.toString();
                check(Arrays.equals(reply,LocalEconomy.draw(s,cat,"/draw/rmb/single",form("idempotency","duplicate"),new Random(0),now+2))&&
                    snapshot.equals(s.toString()),"Duplicate replay awarded/charged twice");
            }
        }
        JSONObject ten=role(cat);long weapon=1701000101L;own(ten,cat,weapon);
        JSONObject before=new JSONObject(ten.getJSONObject("items").toString());
        byte[] tenReply=LocalEconomy.draw(ten,cat,"/draw/rmb/ten",form("idempotency","ten","times","10"),weaponRoll(2,0),now);
        check(ProtoWire.parse(tenReply).fields.size()==20,"Ten duplicates must display exactly ten weapon pairs");
        JSONObject expected=expected(cat,rules,weapon,true);
        for(Iterator<String> keys=expected.keys();keys.hasNext();){String id=keys.next();expected.put(id,10*expected.getLong(id));}
        delta(before,ten.getJSONObject("items"),expected);
        // Another weapon of a known witch also gives witch fragments, but
        // never materials for a weapon which is actually being unlocked.
        JSONObject second=role(cat);own(second,cat,weapon);
        JSONObject secondBefore=new JSONObject(second.getJSONObject("items").toString());
        LocalEconomy.draw(second,cat,"/draw/rmb/single",form("idempotency","second-weapon"),weaponRoll(2,1),now);
        delta(secondBefore,second.getJSONObject("items"),expected(cat,rules,1701000102L,false));
        check(second.getJSONObject("items").optLong("40240042")==0,"New weapon incorrectly decomposed");
        // Persist a real server draw through LocalSave, not a JSON-only mock.
        File directory=new File(args[2]);check(directory.mkdir(),"Fresh test directory required");
        JSONObject all=role(cat);
        for(int c=0;c<3;c++)for(long wid:NormalDrawRates.weaponPool(c,cat))own(all,cat,wid);
        File saveFile=new File(directory,"offline_save_v1.json");
        Files.write(saveFile.toPath(),all.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave save=new LocalSave(directory);boolean found=false;
        for(int attempt=0;attempt<100&&!found;attempt++){
            JSONObject prior=read(saveFile);String key="disk-draw-"+attempt;
            byte[] reply=save.respond("/draw/rmb/single",form("idempotency",key),new byte[0],cat);
            ProtoWire draw=ProtoWire.parse(reply);JSONObject stored=read(saveFile);
            if(draw.fields.size()>=2&&ProtoWire.parse(draw.fields.get(0).data).number(1,0)==1){
                long wid=ProtoWire.parse(draw.fields.get(1).data).number(2,0);
                delta(prior.getJSONObject("items"),stored.getJSONObject("items"),expected(cat,rules,wid,true));found=true;
            }
            byte[] snapshot=Files.readAllBytes(saveFile.toPath());LocalSave reload=new LocalSave(directory);
            check(Arrays.equals(reply,reload.respond("/draw/rmb/single",form("idempotency",key),new byte[0],cat))&&
                Arrays.equals(snapshot,Files.readAllBytes(saveFile.toPath())),"Draw restart replay changed disk contents");
        }
        check(found,"No deterministic coverage of persisted weapon reward");
        // Promote using earned fragments and verify failure/commit/restart.
        JSONObject promotion=ten;String sid="10010001";
        ProtoWire servant=LocalEconomy.decode(promotion.getJSONObject("ownedServants").getString(sid));
        servant.set(5,0);promotion.getJSONObject("ownedServants").put(sid,LocalEconomy.encode(servant));
        Files.write(saveFile.toPath(),promotion.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave growth=new LocalSave(directory);
        byte[] promoted=growth.respond("/servant/star",form("servantcardids",sid,"idempotency","star-first"),new byte[0],cat);
        JSONObject afterStar=read(saveFile);
        check(LocalEconomy.decode(afterStar.getJSONObject("ownedServants").getString(sid)).number(5,0)==1&&
            afterStar.getJSONObject("items").getLong("40130001")==10&&afterStar.getLong("gold")==9998000L,
            "Earned fragments did not persist a correct star promotion");
        byte[] snapshot=Files.readAllBytes(saveFile.toPath());growth=new LocalSave(directory);
        check(Arrays.equals(promoted,growth.respond("/servant/star",form("servantcardids",sid,"idempotency","star-first"),new byte[0],cat))&&
            Arrays.equals(snapshot,Files.readAllBytes(saveFile.toPath())),"Star restart retry charged twice");
        try{growth.respond("/servant/star",form("servantcardids",sid,"idempotency","star-insufficient"),new byte[0],cat);
            throw new AssertionError("Insufficient real fragments accepted");
        }catch(java.io.IOException correct){check(Arrays.equals(snapshot,Files.readAllBytes(saveFile.toPath())),"Failed star consumed real materials");}
        System.out.println("DrawPersistenceSelfTest: "+checks+" checks passed; all 60 weapons, ten duplicates, disk reload, promotion and replay");
    }
}
