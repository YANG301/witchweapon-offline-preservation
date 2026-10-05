package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;

/** Original permanent Kanban achievement thresholds, rewards and isolation. */
public final class CosmeticAchievementsSelfTest {
    private static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    private static Map<String,String> args(long role,long id){
        Map<String,String> result=new HashMap<String,String>();
        result.put("roleid",Long.toString(role));result.put("jobid",Long.toString(id));return result;
    }
    private static JSONObject account(long id,JSONObject catalog)throws Exception{
        JSONObject state=new JSONObject().put("starterProfile",1).put("cosmeticProfile",1)
            .put("roleCreated",true).put("legacyRoleId",id).put("gold",1000)
            .put("rmb",0).put("exp",0);
        LocalEconomy.init(state,catalog);
        return state;
    }
    private static long atLevel(JSONObject catalog,int level)throws Exception{
        long exp=0;
        for(int i=1;i<level;i++)exp=Math.addExact(exp,
            catalog.getJSONObject("roleLevels").getLong(Integer.toString(i)));
        return exp;
    }
    private static int status(JSONObject state,JSONObject catalog,byte[] seed,long id)throws Exception{
        ProtoWire list=ProtoWire.parse(CosmeticAchievements.taskList(state,catalog,seed));
        for(ProtoWire.Field field:list.fields)if(field.number==1&&field.type==2){
            ProtoWire job=ProtoWire.parse(field.data);
            if(job.number(1,0)==id)return (int)job.number(2,-99);
        }
        throw new AssertionError("Achievement absent: "+id);
    }
    private static void blocked(JSONObject state,JSONObject catalog,long id)throws Exception{
        String before=state.toString();
        try{
            CosmeticAchievements.claim(new JSONObject(before),catalog,
                args(state.getLong("legacyRoleId"),id));
            throw new AssertionError("Premature reward accepted: "+id);
        }catch(java.io.IOException expected){
            check(before.equals(state.toString()),"Rejected claim mutated account");
        }
    }
    private static void weaponLevels(JSONObject state,JSONObject catalog,int count,int level)
            throws Exception{
        JSONObject owned=state.getJSONObject("ownedServants"),templates=catalog.getJSONObject("servants");
        Iterator<String> it=templates.keys();int written=0;
        while(it.hasNext()&&written<count){
            String id=it.next();ProtoWire servant=LocalEconomy.decode(templates.getString(id));
            servant.set(12,level);owned.put(id,LocalEconomy.encode(servant));written++;
        }
        check(written==count,"Not enough original servant templates");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=1)throw new IllegalArgumentException("Arguments: offline_responses.json");
        JSONObject source=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),
            StandardCharsets.UTF_8)),catalog=source.getJSONObject("_catalog");
        byte[] seed=Base64.decode(source.getJSONObject("/task/all").getString("base64"),Base64.DEFAULT);
        JSONObject first=account(101,catalog),second=account(202,catalog);
        check(status(first,catalog,seed,502001010L)==-1,"Level 60 board ready at level 1");
        blocked(first,catalog,502001010L);
        blocked(first,catalog,502060005L);
        first.put("exp",atLevel(catalog,60));
        blocked(first,catalog,502001010L); // Original front_achievement chain.
        for(long id=502001001L;id<=502001010L;id++){
            check(status(first,catalog,seed,id)==0,"Level chain did not become ready: "+id);
            CosmeticAchievements.claim(first,catalog,args(101,id));
            check(status(first,catalog,seed,id)==1,"Level reward not marked claimed: "+id);
        }
        check(CosmeticUnlocks.ownsBoard(first,3),"Level 60 did not award board 3");
        check(!CosmeticUnlocks.ownsBoard(second,3),"Another account inherited board 3");
        String prior=first.toString();
        byte[] retry=CosmeticAchievements.claim(first,catalog,args(101,502001010L));
        check(prior.equals(first.toString()) && retry.length>0,
            "Achievement retry changed the save or lost its reward response");

        weaponLevels(first,catalog,1,30);
        for(long id=502060002L;id<=502060005L;id++){
            check(status(first,catalog,seed,id)==0,"Weapon chain did not become ready: "+id);
            CosmeticAchievements.claim(first,catalog,args(101,id));
        }
        check(CosmeticUnlocks.ownsBoard(first,5),"Weapon Lv30 did not award board 5");
        blocked(first,catalog,501060002L);
        weaponLevels(first,catalog,12,60);
        CosmeticAchievements.claim(first,catalog,args(101,501060001L));
        CosmeticAchievements.claim(first,catalog,args(101,501060002L));
        check(CosmeticUnlocks.ownsBoard(first,4),"12 weapons Lv60 did not award board 4");
        check(!CosmeticUnlocks.ownsBoard(first,2) && !CosmeticUnlocks.ownsBoard(first,6),
            "Unknown board 2 or limited-time event board was fabricated");
        check(status(second,catalog,seed,502001010L)==-1 &&
            !CosmeticUnlocks.ownsBoard(second,4) && !CosmeticUnlocks.ownsBoard(second,5),
            "Achievements leaked across accounts");
        JSONObject priorOnline=account(303,catalog);priorOnline.remove("cosmeticProfile");
        check(status(priorOnline,catalog,seed,502001001L)==-1,
            "Shared original StoryQuest row is missing from an existing account");
        System.out.println("COSMETIC_ACHIEVEMENTS_SELF_TEST_OK");
    }
}
