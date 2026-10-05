package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashMap;
import java.util.Map;

/** Original title ownership, selection, retries, and persistence boundaries. */
public final class TitleSelectionSelfTest {
    private static int checks;
    private static void check(boolean value,String why){checks++;if(!value)throw new AssertionError(why);}
    private static Map<String,String> form(String role,String title){
        Map<String,String> result=new HashMap<String,String>();
        result.put("roleid",role);result.put("title",title);return result;
    }
    private static JSONObject read(File file)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
    }
    private static void blocked(LocalSave save,File file,Map<String,String> args,byte[] seed)throws Exception{
        byte[] before=Files.readAllBytes(file.toPath());
        try{save.changeTitle(args,seed);throw new AssertionError("Invalid title accepted: "+args);}
        catch(java.io.IOException expected){}
        check(java.util.Arrays.equals(before,Files.readAllBytes(file.toPath())),"Rejected title changed progress");
    }
    public static void main(String[] args)throws Exception{
        check(args.length==2,"Pass original responses and a fresh test directory");
        JSONObject responses=read(new File(args[0])),catalog=responses.getJSONObject("_catalog");
        byte[] seed=Base64.decode(responses.getJSONObject("/role/role").getString("base64"),0);
        File dir=new File(args[1]);check(dir.mkdir(),"Fresh test directory required");
        File file=new File(dir,"offline_save_v1.json");
        JSONObject initial=new JSONObject().put("version",1).put("starterProfile",1)
            .put("roleCreated",true).put("legacyRoleId",101).put("name","TitleTest")
            .put("gold",1000).put("rmb",0).put("exp",0).put("saveRevision",1)
            .put("roleUnlocks",new JSONObject().put("3",new JSONObject().put("9",true).put("10",1)));
        Files.write(file.toPath(),initial.toString().getBytes(StandardCharsets.UTF_8));
        LocalSave save=new LocalSave(dir);
        save.changeTitle(form("101","9"),seed);
        JSONObject selected=read(file);
        check(selected.getInt("curTitle")==9,"Selected title was not saved");
        check(selected.getLong("gold")==1000&&selected.getLong("rmb")==0,"Title consumed currency");
        check(selected.getJSONObject("roleUnlocks").toString().equals(initial.getJSONObject("roleUnlocks").toString()),
            "Selecting a title changed ownership");
        byte[] before=Files.readAllBytes(file.toPath());
        save.changeTitle(form("101","9"),seed);
        check(java.util.Arrays.equals(before,Files.readAllBytes(file.toPath())),"Same-title retry rewrote progress");
        LocalSave reopened=new LocalSave(dir);
        ProtoWire role=ProtoWire.parse(ProtoWire.parse(reopened.respond("/role/role",new HashMap<String,String>(),seed,catalog)).data(1));
        check(role.number(123,-1)==9,"Role lookup lost the selected title after reopening the save");
        check(role.integers(3).get(8)==1&&role.integers(3).get(9)==1,"Title ownership flags use the wrong indexes");
        check(role.integers(3).get(0)==0,"Title lookup unlocked an unearned title");
        for(String invalid:new String[]{"0","-1","25","hello","9.0","09","9223372036854775808",""})
            blocked(reopened,file,form("101",invalid),seed);
        blocked(reopened,file,form("102","9"),seed);
        blocked(reopened,file,form("101","1"),seed);
        reopened.changeTitle(form("101","10"),seed);
        check(read(file).getInt("curTitle")==10,"Numeric ownership flag was ignored");
        // Preserve titles granted by an original packed flag array too.
        ProtoWire reply=ProtoWire.parse(seed),instance=ProtoWire.parse(reply.data(1));
        instance.clear(3).set(3,new byte[]{1});reply.set(1,instance.bytes());
        reopened.changeTitle(form("101","1"),reply.bytes());
        check(read(file).getInt("curTitle")==1,"Packed original title flag was ignored");
        System.out.println("TITLE_SELECTION_PASS checks="+checks);
    }
}
