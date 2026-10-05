package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import org.json.JSONObject;

/** Real preserved combat templates, with isolated pre-starter account saves. */
public final class CombatWeaponSelectionSelfTest {
    private static int requests;
    private static void check(boolean yes,String message) {
        if(!yes)throw new AssertionError(message);
    }
    private static Map<String,String> form(String... values) {
        Map<String,String> result=new LinkedHashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }
    private static List<ProtoWire> rows(byte[] role)throws Exception {
        List<ProtoWire> result=new ArrayList<ProtoWire>();
        for(ProtoWire.Field field:ProtoWire.parse(role).fields)
            if(field.number==2&&field.type==2)result.add(ProtoWire.parse(field.data));
        return result;
    }
    private static String joined(List<ProtoWire> selection,int field,String separator) {
        StringBuilder value=new StringBuilder();
        for(ProtoWire row:selection) {
            if(value.length()>0)value.append(separator);
            value.append(row.number(field,0));
        }
        return value.toString();
    }
    private static String model(ProtoWire row) {
        return new String(row.data(5),StandardCharsets.UTF_8);
    }
    private static byte[] request(LocalSave save,List<ProtoWire> selection,
            byte[] seed,JSONObject catalog,String label)throws Exception {
        return request(save,selection,seed,catalog,label,"|");
    }
    private static byte[] request(LocalSave save,List<ProtoWire> selection,
            byte[] seed,JSONObject catalog,String label,String separator)throws Exception {
        requests++;
        byte[] result=save.respond("/combat/role/info",form("rid","1",
            "servantcardids",joined(selection,1,separator),
            "weaponids",joined(selection,14,separator),
            "fashioncardid","70000001"),seed,catalog);
        List<ProtoWire> actual=rows(result);
        check(actual.size()==selection.size(),label+": wrong party size "+actual.size());
        for(int i=0;i<actual.size();i++) {
            ProtoWire expected=selection.get(i),row=actual.get(i);
            check(row.number(1,0)==expected.number(1,0),label+": party order "+i);
            check(row.number(14,0)==expected.number(14,0),label+": weapon field14 "+i);
            check(Arrays.equals(row.data(5),expected.data(5)),label+": model field5 "+i);
            check(row.number(7,0)==expected.number(7,0),label+": attack spell "+i);
            check(row.number(10,0)==expected.number(10,0),label+": servant spell "+i);
            check(Arrays.equals(row.data(8),expected.data(8)),label+": attack spell list "+i);
        }
        return result;
    }
    private static JSONObject readSave(File directory)throws Exception {
        return new JSONObject(new String(Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }
    private static void begin(LocalSave save,JSONObject catalog,String label)throws Exception {
        save.respond("/level/startBattle",form("instanceid",Long.toString(LocalSave.STAGE),
            "idempotency",label),new byte[0],catalog);
    }
    private static void diagnostic(LocalSave save,Map<String,String> args,
            byte[] seed,JSONObject catalog,String label)throws Exception {
        List<ProtoWire> actual=rows(save.respond("/combat/role/info",args,seed,catalog));
        check(!actual.isEmpty(),label+": unexpectedly empty response");
        System.out.println(label+" rows="+actual.size()+" first-servant="+
            actual.get(0).number(1,0)+" first-weapon="+actual.get(0).number(14,0));
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=2)throw new IllegalArgumentException("Arguments: empty-dir responses.json");
        System.out.println("LOADED_LOCAL_SAVE="+LocalSave.class.getProtectionDomain()
            .getCodeSource().getLocation());
        System.out.println("LOADED_LOCAL_ECONOMY="+LocalEconomy.class.getProtectionDomain()
            .getCodeSource().getLocation());
        File directory=new File(args[0]);
        check(directory.isDirectory()&&directory.list().length==0,
            "An empty isolated save directory is required");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[1]).toPath()),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        byte[] seed=Base64.decode(responses.getJSONObject("/combat/role/info")
            .getString("base64"),Base64.DEFAULT);
        check(seed.length>1000,"Real combat fixture unavailable");

        JSONObject old=new JSONObject().put("version",1).put("name","WeaponTest")
            .put("roleCreated",true).put("legacyRoleId",1L)
            .put("gold",1000000L).put("rmb",0L).put("exp",0L)
            .put("stamina",200L).put("activityStamina",0L)
            .put("wins",0).put("attempts",0).put("stage",LocalSave.STAGE)
            .put("stars",0).put("curFashion",70000001L)
            .put("ownedServants",new JSONObject(catalog.getJSONObject("servants").toString()));
        LocalEconomy.init(old,catalog);
        check(!old.has("starterProfile"),"Fixture must exercise the old save path");
        Files.write(new File(directory,"offline_save_v1.json").toPath(),
            old.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave save=new LocalSave(directory);
        save.respond("/backpack/item",form(),new byte[0],catalog);

        Map<Long,List<ProtoWire>> groups=new TreeMap<Long,List<ProtoWire>>();
        int templateCount=0;
        for(ProtoWire row:rows(seed)) {
            long sid=row.number(1,0),wid=row.number(14,0);
            check(catalog.getJSONObject("weapons").getJSONObject(Long.toString(wid))
                .getLong("servant")==sid,"Catalog owner differs from combat template");
            if(!groups.containsKey(sid))groups.put(sid,new ArrayList<ProtoWire>());
            List<ProtoWire> variants=groups.get(sid);
            boolean repeated=false;
            for(ProtoWire variant:variants)if(variant.number(14,0)==wid)repeated=true;
            if(!repeated)variants.add(row);
            templateCount++;
        }
        List<List<ProtoWire>> multiple=new ArrayList<List<ProtoWire>>();
        for(Map.Entry<Long,List<ProtoWire>> group:groups.entrySet()) {
            if(group.getValue().size()>1)multiple.add(group.getValue());
        }
        check(!multiple.isEmpty(),"No same-servant multi-weapon fixtures");
        List<ProtoWire> pair=multiple.get(0);
        ProtoWire first=pair.get(0),second=pair.get(1);
        System.out.println("SWITCH_PAIR servant="+first.number(1,0)+
            " first="+first.number(14,0)+"/model="+model(first)+
            " second="+second.number(14,0)+"/model="+model(second));
        begin(save,catalog,"first-entry");
        request(save,Collections.singletonList(first),seed,catalog,"first weapon");
        request(save,Collections.singletonList(second),seed,catalog,"second weapon");
        request(save,Collections.singletonList(first),seed,catalog,"back to first");
        begin(save,catalog,"second-entry");
        request(save,Collections.singletonList(second),seed,catalog,"second re-entry");
        save=new LocalSave(directory);
        request(save,Collections.singletonList(second),seed,catalog,"reopened LocalSave second");
        begin(save,catalog,"third-entry");
        request(save,Collections.singletonList(first),seed,catalog,"reopened first re-entry");

        int variants=0,sharedModels=0;
        for(List<ProtoWire> group:multiple) {
            for(ProtoWire variant:group) {
                request(save,Collections.singletonList(variant),seed,catalog,"template variant");
                variants++;
            }
            for(int i=1;i<group.size();i++)
                if(Arrays.equals(group.get(i).data(5),group.get(0).data(5)))sharedModels++;
        }
        List<ProtoWire> party=new ArrayList<ProtoWire>();
        for(int i=0;i<Math.min(4,multiple.size());i++) {
            List<ProtoWire> group=multiple.get(i);
            party.add(group.get(i%group.size()));
        }
        request(save,party,seed,catalog,"four-servant order");
        Collections.reverse(party);
        request(save,party,seed,catalog,"reversed four-servant order");
        Collections.rotate(party,1);
        request(save,party,seed,catalog,"rotated four-servant order");
        request(save,party,seed,catalog,"comma list",",");
        request(save,party,seed,catalog,"semicolon list",";");
        String[] separators={"|",",",";"};
        Map<String,String> mixed=form("rid","1","fashioncardid","70000001");
        StringBuilder servantIds=new StringBuilder(),weaponIds=new StringBuilder();
        for(int i=0;i<party.size();i++) {
            if(i>0){servantIds.append(separators[(i-1)%3]);weaponIds.append(separators[(i-1)%3]);}
            servantIds.append(party.get(i).number(1,0));
            weaponIds.append(party.get(i).number(14,0));
        }
        mixed.put("servantcardids",servantIds.toString());mixed.put("weaponids",weaponIds.toString());
        List<ProtoWire> mixedRows=rows(save.respond("/combat/role/info",mixed,seed,catalog));
        for(int i=0;i<party.size();i++)check(mixedRows.get(i).number(14,0)==party.get(i).number(14,0),
            "Mixed separators shifted party weapon pairing");

        List<ProtoWire> omitted=rows(save.respond("/combat/role/info",form(
            "servantcardids",Long.toString(second.number(1,0)),
            "fashioncardid","70000001"),seed,catalog));
        check(omitted.size()==1,"Missing weapon list unexpectedly changed party size");
        System.out.println("MISSING_WEAPON_DEFAULT servant="+omitted.get(0).number(1,0)+
            " weapon="+omitted.get(0).number(14,0)+" model="+model(omitted.get(0)));
        List<ProtoWire> empty=rows(save.respond("/combat/role/info",form(),seed,catalog));
        check(empty.size()==templateCount,"Missing party must preserve current seed behavior");
        System.out.println("MISSING_PARTY_ROWS="+empty.size());
        // Field-name compatibility is observed separately from real canonical
        // ARM64 requests; a diagnostic outcome is not evidence of their cause.
        String sid=Long.toString(second.number(1,0)),wid=Long.toString(second.number(14,0));
        diagnostic(save,form("svcardids",sid,"wpids",wid),seed,catalog,"ORDINARY_ALIASES");
        diagnostic(save,form("servantcardids",sid,"wpids",wid),seed,catalog,
            "MIXED_CANONICAL_PARTY_ALIAS_WEAPONS");
        diagnostic(save,form("svcardids",sid,"weaponids",wid),seed,catalog,
            "MIXED_ALIAS_PARTY_CANONICAL_WEAPONS");
        JSONObject finalSave=readSave(directory);
        check(!finalSave.has("starterProfile"),"Old save was unexpectedly converted to starter");
        check(finalSave.getJSONObject("ownedServants").toString()
            .equals(old.getJSONObject("ownedServants").toString()),
            "Battle weapon selection changed owned inventory");
        System.out.println("TEMPLATE_ROWS="+templateCount+" SERVANTS="+groups.size()+
            " MULTI_WEAPON_SERVANTS="+multiple.size()+" CHECKED_VARIANTS="+variants+
            " SAME_FIELD5_VARIANTS="+sharedModels+" CANONICAL_REQUESTS="+requests);
        System.out.println("COMBAT_WEAPON_SELECTION_PASS");
    }
}
