package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

/** The original 10007 story purchase must unlock guide recID 50 exactly once. */
public final class StarterStorySelfTest {
    private static final long GROUP_ID=6010001L,STORY_ID=61100011006L,JOB_ID=509005009L;

    private static void require(boolean value,String message){
        if(!value)throw new AssertionError(message);
    }

    private static byte[] fixture(JSONObject responses,String path)throws Exception{
        return Base64.decode(responses.getJSONObject(path).getString("base64"),Base64.DEFAULT);
    }

    private static Map<String,String> form(String... values){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<values.length;i+=2)result.put(values[i],values[i+1]);
        return result;
    }

    private static JSONObject read(File directory)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(
            new File(directory,"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
    }

    private static ProtoWire story(byte[] payload)throws Exception{
        ProtoWire result=ProtoWire.parse(payload);
        for(ProtoWire.Field mapField:result.fields){
            if(mapField.number!=1 || mapField.type!=2)continue;
            ProtoWire entry=ProtoWire.parse(mapField.data);
            if(entry.number(1,0)!=GROUP_ID)continue;
            ProtoWire group=ProtoWire.parse(entry.data(2));
            require(group.number(100,0)==1,"Starter group was relocked");
            for(ProtoWire.Field field:group.fields){
                if(field.number!=1 || field.type!=2)continue;
                ProtoWire node=ProtoWire.parse(field.data);
                if(node.number(100,0)==STORY_ID)return node;
            }
        }
        throw new AssertionError("Target story missing");
    }

    private static void onlyTargetChanged(byte[] before,byte[] after)throws Exception{
        ProtoWire old=ProtoWire.parse(before),changed=ProtoWire.parse(after);
        require(old.fields.size()==changed.fields.size(),"Group count changed");
        for(int i=0;i<old.fields.size();i++){
            ProtoWire.Field a=old.fields.get(i),b=changed.fields.get(i);
            if(a.number!=1 || a.type!=2){require(Arrays.equals(a.data,b.data),"Top-level field changed");continue;}
            ProtoWire oldEntry=ProtoWire.parse(a.data),newEntry=ProtoWire.parse(b.data);
            if(oldEntry.number(1,0)!=GROUP_ID){
                require(Arrays.equals(a.data,b.data),"Unrelated group changed");
                continue;
            }
            ProtoWire oldGroup=ProtoWire.parse(oldEntry.data(2)),newGroup=ProtoWire.parse(newEntry.data(2));
            require(oldGroup.fields.size()==newGroup.fields.size(),"Starter group shape changed");
            for(int n=0;n<oldGroup.fields.size();n++){
                ProtoWire.Field x=oldGroup.fields.get(n),y=newGroup.fields.get(n);
                if(x.number!=1 || x.type!=2 ||
                        ProtoWire.parse(x.data).number(100,0)!=STORY_ID)
                    require(x.number==y.number && x.type==y.type &&
                        (x.type==0?x.value==y.value:Arrays.equals(x.data,y.data)),
                        "Unrelated starter story changed");
            }
        }
    }

    private static ProtoWire job(byte[] payload,boolean inLoot)throws Exception{
        ProtoWire result=ProtoWire.parse(payload);
        if(inLoot)result=ProtoWire.parse(ProtoWire.parse(result.data(2)).data(2));
        for(ProtoWire.Field field:result.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire item=ProtoWire.parse(field.data);
            if(item.number(1,0)==JOB_ID)return item;
        }
        throw new AssertionError("Story achievement missing");
    }

    private static void rejected(LocalSave save,File dir,JSONObject catalog,
                                 Map<String,String> request,byte[] seed,byte[] storySeed)throws Exception{
        byte[] before=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        try{
            save.respond("/story/buy",request,seed,catalog,storySeed);
            throw new AssertionError("Invalid story buy accepted: "+request.keySet());
        }catch(java.io.IOException expected){}
        require(Arrays.equals(before,Files.readAllBytes(
            new File(dir,"offline_save_v1.json").toPath())),
            "Rejected story purchase changed the account");
    }

    private static void rejected400WithoutLeaking(JSONObject state,Map<String,String> request,
                                                   byte[] seed,byte[] storySeed,
                                                   String category)throws Exception{
        String before=state.toString();
        ByteArrayOutputStream logged=new ByteArrayOutputStream();
        PrintStream original=System.err;
        try(PrintStream capture=new PrintStream(logged,true,"UTF-8")){
            System.setErr(capture);
            try{
                LocalStarterStory.buy(state,request,seed,storySeed);
                throw new AssertionError("Expected the 400-mapped InvalidRequest");
            }catch(LocalDaily.InvalidRequest expected){}
        }finally{
            System.setErr(original);
        }
        require(before.equals(state.toString()),"Rejected story purchase changed the account");
        require(("STORY_BUY_REJECT "+category+System.lineSeparator()).equals(
            logged.toString("UTF-8")),"Story rejection log included request data");
    }

    public static void main(String[] args)throws Exception{
        if(args.length!=2)throw new IllegalArgumentException("Arguments: responses.json empty-test-dir");
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(
            new File(args[0]).toPath()),StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        byte[] storySeed=fixture(responses,"/story/get"),buySeed=fixture(responses,"/story/buy");
        require(story(storySeed).number(101,-1)==1 && story(storySeed).number(102,-1)==1,
            "Preserved target fixture differs from inspected original");

        JSONObject uncreated=new JSONObject().put("starterProfile",1).put("roleCreated",false);
        JSONObject created=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("legacyRoleId",12345L);
        rejected400WithoutLeaking(uncreated,form("rid","987654321012345678",
            "storyid","61100011006"),buySeed,storySeed,"ROLE_MISSING");
        rejected400WithoutLeaking(created,form("rid","12345",
            "storyid","987654321012345678"),buySeed,storySeed,"STORYID_MISMATCH");

        File dir=new File(args[1]);
        require(dir.isDirectory(),"Fresh test directory required");
        LocalSave save=new LocalSave(dir);
        save.respond("/role/create",Collections.<String,String>emptyMap(),
            fixture(responses,"/role/create"),catalog);
        JSONObject state=read(dir);
        String rid=String.valueOf(state.getLong("legacyRoleId"));
        byte[] locked=save.respond("/story/get",Collections.<String,String>emptyMap(),storySeed,catalog);
        require(story(locked).number(101,-1)==0 && story(locked).number(102,-1)==1,
            "New starter story was not purchasable and locked");
        onlyTargetChanged(storySeed,locked);
        byte[] persisted=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        save.respond("/story/get",Collections.<String,String>emptyMap(),storySeed,catalog);
        require(Arrays.equals(persisted,Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath())),
            "Story read changed persisted state");

        rejected(save,dir,catalog,form("rid",rid,"storyid",String.valueOf(STORY_ID)),buySeed,storySeed);
        rejected(save,dir,catalog,form("roleid",rid,"storyid",String.valueOf(STORY_ID)),buySeed,storySeed);
        rejected(save,dir,catalog,form("rid",rid,"storyid","61100011005"),buySeed,storySeed);

        // Model the already-won 1006 battle without calling a second network route.
        state.put("tutorialWins_3150001006",1);
        Files.write(new File(dir,"offline_save_v1.json").toPath(),
            (state.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
        save=new LocalSave(dir);
        rejected(save,dir,catalog,form("rid",rid,"storyid","61100011007"),buySeed,storySeed);
        rejected(save,dir,catalog,form("rid",rid,"storyid",String.valueOf(STORY_ID)),buySeed,null);

        ByteArrayOutputStream compatibilityLog=new ByteArrayOutputStream();
        PrintStream originalErr=System.err;
        byte[] first;
        try(PrintStream capture=new PrintStream(compatibilityLog,true,"UTF-8")){
            System.setErr(capture);
            first=save.respond("/story/buy",form("rid","0","storyid",String.valueOf(STORY_ID)),
                buySeed,catalog,storySeed);
        }finally{System.setErr(originalErr);}
        require(("STORY_BUY_COMPAT RID_KIND ZERO"+System.lineSeparator()).equals(
            compatibilityLog.toString("UTF-8")),"Compatibility log included request data");
        ProtoWire firstJob=job(first,true);
        require(firstJob.number(2,-1)==0 && firstJob.number(3,0)==1 &&
            firstJob.number(5,0)==1 &&
            "005".equals(new String(firstJob.data(4),StandardCharsets.UTF_8)),
            "Story purchase did not immediately report original job 509005009");
        ProtoWire storyExtra=ProtoWire.parse(ProtoWire.parse(first).data(2));
        require(Arrays.equals(storySeed,storyExtra.data(5)) &&
            story(storyExtra.data(5)).number(101,-1)==1,
            "Story purchase did not immediately unlock the original client model");
        require(read(dir).getJSONObject("tutorialTasks").getInt(String.valueOf(JOB_ID))==0,
            "Story completion did not persist");
        require(job(save.respond("/task/all",Collections.<String,String>emptyMap(),
            fixture(responses,"/task/all"),catalog),false).number(2,-1)==0,
            "Task fetch omitted completed story job");
        require(Arrays.equals(storySeed,save.respond("/story/get",Collections.<String,String>emptyMap(),
            storySeed,catalog)),"Story remained locked after purchase");
        byte[] afterFirst=Files.readAllBytes(new File(dir,"offline_save_v1.json").toPath());
        byte[] replay=save.respond("/story/buy",form("rid",rid,"storyid",String.valueOf(STORY_ID)),
            buySeed,catalog,storySeed);
        require(Arrays.equals(first,replay) && Arrays.equals(afterFirst,Files.readAllBytes(
            new File(dir,"offline_save_v1.json").toPath())),
            "Repeated story purchase duplicated its effect");
        require(Arrays.equals(first,save.respond("/story/buy",
            form("storyid",String.valueOf(STORY_ID)),buySeed,catalog,storySeed)),
            "Authenticated account with missing advisory rid lost its story response");

        save.respond("/task/update",form("jobid",String.valueOf(JOB_ID)),
            fixture(responses,"/task/update"),catalog);
        byte[] claimed=save.respond("/story/buy",form("rid",rid,"storyid",String.valueOf(STORY_ID)),
            buySeed,catalog,storySeed);
        require(job(claimed,true).number(2,-1)==1 &&
            read(dir).getJSONObject("tutorialTasks").getInt(String.valueOf(JOB_ID))==1,
            "Story replay downgraded the already claimed job");

        JSONObject old=new JSONObject().put("starterProfile",0);
        require(Arrays.equals(storySeed,LocalStarterStory.get(old,storySeed)) &&
            Arrays.equals(buySeed,LocalStarterStory.buy(old,Collections.<String,String>emptyMap(),buySeed,storySeed)),
            "Legacy accounts no longer receive preserved story fixtures");
        System.out.println("StarterStorySelfTest passed");
    }
}
