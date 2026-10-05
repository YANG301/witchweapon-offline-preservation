package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.Map;

/** Restores the original story purchase that completes guide recID 13. */
final class LocalStarterStory {
    private static final long GROUP_ID=6010001L;
    private static final long STORY_ID=61100011006L;
    private static final String JOB_ID="509005009";

    private LocalStarterStory() {}

    private static boolean starter(JSONObject state){
        return state.optInt("starterProfile",0)==1;
    }

    private static int jobStatus(JSONObject state){
        JSONObject tasks=state.optJSONObject("tutorialTasks");
        return tasks==null?-1:tasks.optInt(JOB_ID,-1);
    }

    /** Fixed categories only: the request and saved identifier never enter logs. */
    private static String ridMismatchKind(String rid,long expected){
        if(rid==null)return "MISSING";
        if("0".equals(rid))return "ZERO";
        if(!rid.matches("[1-9][0-9]{0,18}"))return "FORMAT";
        try{
            long actual=Long.parseLong(rid);
            if(actual==((long)(double)expected))return "FLOAT_ROUNDING";
            if(actual>0 && Math.abs(actual-expected)<=1024)return "NEAR";
        }catch(NumberFormatException ignored){return "FORMAT";}
        return "OTHER";
    }

    /** Preserve the fixture except for the one story the first account must play. */
    static byte[] get(JSONObject state,byte[] seed) throws Exception {
        if(!starter(state) || jobStatus(state)>=0)return seed;
        ProtoWire stories=ProtoWire.parse(seed);
        int matches=0;
        for(ProtoWire.Field mapField:stories.fields){
            if(mapField.number!=1 || mapField.type!=2)continue;
            ProtoWire entry=ProtoWire.parse(mapField.data);
            if(entry.number(1,0)!=GROUP_ID)continue;
            ProtoWire group=ProtoWire.parse(entry.data(2));
            if(group.number(100,0)!=1)
                throw new IOException("Starter story group fixture is locked");
            for(ProtoWire.Field nodeField:group.fields){
                if(nodeField.number!=1 || nodeField.type!=2)continue;
                ProtoWire node=ProtoWire.parse(nodeField.data);
                if(node.number(100,0)!=STORY_ID)continue;
                if(node.number(102,0)!=1)
                    throw new IOException("Starter story fixture cannot unlock target");
                node.set(101,0);
                nodeField.data=node.bytes();
                matches++;
            }
            entry.set(2,group.bytes());
            mapField.data=entry.bytes();
        }
        if(matches!=1)throw new IOException("Starter story fixture has no unique target");
        return stories.bytes();
    }

    /** The authenticated account selects the save; the old client's rid is advisory. */
    static byte[] buy(JSONObject state,Map<String,String> args,byte[] seed,
                      byte[] storyFixture) throws Exception {
        if(!starter(state))return seed;
        if(!state.optBoolean("roleCreated",false)){
            System.err.println("STORY_BUY_REJECT ROLE_MISSING");
            throw new LocalDaily.InvalidRequest("Role required for starter story");
        }
        if(!String.valueOf(STORY_ID).equals(args.get("storyid"))){
            System.err.println("STORY_BUY_REJECT STORYID_MISMATCH");
            throw new LocalDaily.InvalidRequest("Unknown starter story");
        }
        if(state.optInt("tutorialWins_3150001006",0)<=0)
            throw new LocalDaily.Conflict("Starter story prerequisite is unfinished");
        String rid=args.get("rid");
        if(!String.valueOf(state.optLong("legacyRoleId",0)).equals(rid))
            System.err.println("STORY_BUY_COMPAT RID_KIND " +
                ridMismatchKind(rid,state.optLong("legacyRoleId",0)));
        // The original handler also parses ExtraInfo.Story before advancing
        // the lesson. Use the preserved complete Story response so no sibling
        // story or group disappears if the client replaces the received model.
        if(storyFixture==null || storyFixture.length==0)
            throw new IOException("Starter story fixture unavailable");
        ProtoWire originalStory=ProtoWire.parse(storyFixture);
        int unlockedTargets=0;
        for(ProtoWire.Field mapField:originalStory.fields){
            if(mapField.number!=1 || mapField.type!=2)continue;
            ProtoWire entry=ProtoWire.parse(mapField.data);
            if(entry.number(1,0)!=GROUP_ID)continue;
            ProtoWire group=ProtoWire.parse(entry.data(2));
            if(group.number(100,0)!=1)
                throw new IOException("Starter story fixture group is locked");
            for(ProtoWire.Field nodeField:group.fields){
                if(nodeField.number!=1 || nodeField.type!=2)continue;
                ProtoWire node=ProtoWire.parse(nodeField.data);
                if(node.number(100,0)==STORY_ID && node.number(101,0)==1)
                    unlockedTargets++;
            }
        }
        if(unlockedTargets!=1)
            throw new IOException("Starter story fixture has no unique unlocked target");

        int status=jobStatus(state);
        if(status<0){
            JSONObject tasks=state.optJSONObject("tutorialTasks");
            if(tasks==null){tasks=new JSONObject();state.put("tutorialTasks",tasks);}
            tasks.put(JOB_ID,0);
            status=0;
        }
        // BuyStory.ParseProtoBuf passes LootResult.ExtraInfo into the original
        // achievement handler before advancing the guide lesson. Report the
        // job in this same response, with its already claimed status on retry.
        ProtoWire response=ProtoWire.parse(seed);
        ProtoWire extra=ProtoWire.parse(response.data(2));
        ProtoWire achievement=ProtoWire.parse(extra.data(2));
        ProtoWire job=new ProtoWire().set(1,Long.parseLong(JOB_ID)).set(2,status)
            .set(3,1).text(4,"005").set(5,1);
        boolean found=false;
        for(ProtoWire.Field field:achievement.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire existing=ProtoWire.parse(field.data);
            if(existing.number(1,0)!=Long.parseLong(JOB_ID))continue;
            field.data=job.bytes();
            found=true;
        }
        if(!found)achievement.add(1,job.bytes());
        extra.set(2,achievement.bytes());
        extra.set(5,storyFixture);
        response.set(2,extra.bytes());
        return response.bytes();
    }
}
