package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;

/** Verify the actual server's role selection/growth preserves the combat fix. */
public final class CombatWeaponTypesSelfTest {
    private static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
    private static ProtoWire find(ProtoWire parent,int field,int idField,long id)throws Exception{
        for(ProtoWire.Field f:parent.fields)if(f.number==field && f.type==2){
            ProtoWire p=ProtoWire.parse(f.data);if(p.number(idField,0)==id)return p;
        }
        throw new AssertionError("Missing combat record "+id);
    }
    public static void main(String[] args)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog"),owned=new JSONObject();
        String[] servants={"10010101","10011401","10011501","10012701"};
        for(String id:servants)owned.put(id,catalog.getJSONObject("servants").getString(id));
        JSONObject state=new JSONObject().put("starterProfile",1).put("ownedServants",owned);
        Map<String,String> form=new LinkedHashMap<String,String>();
        form.put("servantcardids","10010101|10011401|10011501|10012701");
        form.put("weaponids","1701010102|1701140101|1701150102|1701270101");
        form.put("fashioncardid","70000001");
        byte[] seed=Base64.decode(responses.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        byte[] prepared=LocalEconomy.combat(state,form,seed,catalog);
        ProtoWire role=ProtoWire.parse(prepared),unit=ProtoWire.parse(role.data(102));
        for(long id:new long[]{91000030,91000290,91000291})
            check(find(unit,1,2,id).number(8,0)==4,"Weapon passive replaced the normal skill: "+id);
        for(long id:new long[]{95000030,95000031,95000290,95000291,95000320,95000321}){
            ProtoWire effect=find(unit,7,1,id);
            for(int old:new int[]{20,21,22})
                check(effect.number(old+3,0)==effect.number(old+8,0),"Old/new client coefficient mismatch: "+id);
            check(effect.number(31,0)==0,"Reserved silent argument is occupied");
        }
        for(long id:new long[]{2010311102,2010311402,2010311502,2010312701,
                90510111,90510114,90510115,90510127}){
            ProtoWire spell=find(unit,1,2,id);
            check(spell.number(25,0)==1 && spell.number(26,0)==1 &&
                spell.number(27,0)==1 && spell.number(31,0)==2,"Single summon selector drift: "+id);
        }
        check(role.fields.stream().filter(f->f.number==2&&f.type==2).count()==4,"Selected party changed");
        System.out.println("COMBAT_WEAPON_ROLE_PREPARATION_OK; actual role growth/selection retains passive types, compatible coefficients and single targets");
    }
}
