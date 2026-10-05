package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Check actual role preparation against independently read original CSV cases. */
public final class OriginalCombatRulesSelfTest {
    private static void check(boolean yes,String reason){if(!yes)throw new AssertionError(reason);}
    private static JSONObject json(String path)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(Paths.get(path)),StandardCharsets.UTF_8));
    }
    private static ProtoWire find(ProtoWire parent,int field,int idField,long id)throws Exception{
        ProtoWire found=null;
        for(ProtoWire.Field f:parent.fields)if(f.number==field&&f.type==2){
            ProtoWire value=ProtoWire.parse(f.data);
            if(value.number(idField,0)==id){check(found==null,"Duplicate record "+id);found=value;}
        }
        check(found!=null,"Missing record "+id);return found;
    }
    private static void levels(ProtoWire unit,JSONArray ids,int field,int idField,long level)throws Exception{
        for(int i=0;i<ids.length();i++)
            check(find(unit,field,idField,ids.getLong(i)).number(1,0)==level,"Wrong effect level: "+ids.getLong(i));
    }
    public static void main(String[] args)throws Exception{
        JSONObject fixture=json(args[0]),cases=json(args[1]),catalog=fixture.getJSONObject("_catalog");
        byte[] seed=Base64.decode(fixture.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        JSONArray rows=cases.getJSONArray("cases");
        for(int i=0;i<rows.length();i++){
            JSONObject c=rows.getJSONObject(i);long sid=c.getLong("servant"),wid=c.getLong("weapon");
            ProtoWire saved=LocalEconomy.decode(catalog.getJSONObject("servants").getString(Long.toString(sid)));
            saved.set(4,c.getLong("rank")).set(12,c.getLong("weaponLevel"));
            JSONObject owned=new JSONObject().put(Long.toString(sid),LocalEconomy.encode(saved));
            JSONObject state=new JSONObject().put("starterProfile",1).put("exp",c.getLong("accountExp"))
                .put("ownedServants",owned).put("curFashion",70000001L);
            String before=state.toString();
            Map<String,String> form=new LinkedHashMap<String,String>();
            form.put("servantcardids",Long.toString(sid));form.put("weaponids",Long.toString(wid));
            form.put("fashioncardid","70000001");
            ProtoWire role=ProtoWire.parse(LocalEconomy.combat(state,form,seed,catalog));
            check(state.toString().equals(before),"Battle preparation changed account progress");
            check(role.number(100,0)==c.getLong("accountLevel"),"Role level remained a static seed value");
            ProtoWire sv=find(role,2,1,sid),unit=ProtoWire.parse(role.data(102));
            long[] energy=LocalEconomy.packedInts(sv,9,4,-1);JSONArray expected=c.getJSONArray("energy");
            for(int n=0;n<4;n++)check(energy[n]==expected.getLong(n),"Original energy mismatch for "+sid+" position "+n);
            levels(unit,c.getJSONArray("spells"),1,2,c.getLong("weaponLevel"));
            levels(unit,c.getJSONArray("triggers"),4,2,c.getLong("weaponLevel"));
            levels(unit,c.getJSONArray("buffs"),2,3,c.getLong("weaponLevel"));
            ProtoWire originalSv=find(ProtoWire.parse(seed),2,14,wid);
            check(Arrays.equals(sv.data(12),originalSv.data(12)),"Unverified durability was modified");
            for(int n=0;n<c.getJSONArray("spells").length();n++)
                check(find(unit,1,2,c.getJSONArray("spells").getLong(n)).number(8,0)==4,"Weapon effect captured currentSkill");
        }
        // Different weapon levels in the same party must stay separate.
        JSONObject owned=new JSONObject();Map<String,String> form=new LinkedHashMap<String,String>();
        String[] sids={"10010101","10011401","10012401"};long[] lv={7,23,49};
        for(int i=0;i<sids.length;i++){
            ProtoWire sv=LocalEconomy.decode(catalog.getJSONObject("servants").getString(sids[i]));
            sv.set(12,lv[i]);owned.put(sids[i],LocalEconomy.encode(sv));
        }
        JSONObject state=new JSONObject().put("starterProfile",1).put("exp",0).put("ownedServants",owned);
        form.put("servantcardids","10010101|10011401|10012401");
        form.put("weaponids","1701010102|1701140101|1701240102");
        form.put("fashioncardid","70000001");
        ProtoWire role=ProtoWire.parse(LocalEconomy.combat(state,form,seed,catalog));
        ProtoWire unit=ProtoWire.parse(role.data(102));
        long[] spells={91000030L,91000290L,91000491L},buffs={93000030L,93000290L,93000490L};
        for(int i=0;i<3;i++){
            check(find(unit,1,2,spells[i]).number(1,0)==lv[i],"Party weapon levels leaked between members");
            check(find(unit,2,3,buffs[i]).number(1,0)==lv[i],"Party buff level leaked between members");
        }
        check(find(unit,1,2,91000000L).number(1,0)==5,"Unused weapon effect changed");
        System.out.println("ORIGINAL_COMBAT_RULES_OK cases="+rows.length()+"; CSV energy, account levels, passive levels, mixed party and unchanged durability/saves");
    }
}
