package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.Iterator;
import java.util.Map;

/** Verified, permanent original achievement chains that award Kanban 3/4/5.
 * Achievement.asset channel_group 0 and CN 25 supplies thresholds, predecessor
 * IDs and complete rewards. Limited-time Activity rows are intentionally absent.
 */
final class CosmeticAchievements {
    private static final class Reward {
        final int type; final long id,amount;
        Reward(int type,long id,long amount){this.type=type;this.id=id;this.amount=amount;}
        JSONObject json()throws Exception{return new JSONObject().put("type",type)
            .put("id",id).put("value",type==3?0:amount)
            .put("count",type==3?amount:0);}
        ProtoWire wire(){ProtoWire result=new ProtoWire().set(1,type);
            if(id>0)result.set(2,id);
            return type==3?result.set(4,amount):result.set(3,amount).set(4,amount);}
    }
    private static final class Quest {
        final long id,front; final int questType,targetCount,targetLevel;
        final String type; final Reward[] rewards;
        Quest(long id,long front,int questType,String type,int targetCount,int targetLevel,
              Reward...rewards){this.id=id;this.front=front;this.questType=questType;
            this.type=type;this.targetCount=targetCount;this.targetLevel=targetLevel;
            this.rewards=rewards;}
    }
    private static Reward gold(long n){return new Reward(13,0,n);}
    private static Reward diamond(long n){return new Reward(99,0,n);}
    private static Reward item(long id,long n){return new Reward(3,id,n);}
    private static Reward board(long id){return new Reward(84,0,id);}
    private static Reward head(long id){return new Reward(80,0,id);}
    private static final Reward TOKEN=item(40240039L,30), TAROT=item(40350003L,1);
    private static final Quest[] QUESTS={
        // Achievement.asset 502001001..010: role levels 5,20,..60.
        new Quest(502001001L,0,6,"001",1,5,gold(10000),TOKEN,TAROT),
        new Quest(502001002L,502001001L,6,"001",1,20,gold(10000),TOKEN,TAROT),
        new Quest(502001003L,502001002L,6,"001",1,25,gold(10000),head(7),TOKEN,TAROT),
        new Quest(502001004L,502001003L,6,"001",1,30,gold(10000),TOKEN,TAROT),
        new Quest(502001005L,502001004L,6,"001",1,35,gold(10000),TOKEN),
        new Quest(502001006L,502001005L,6,"001",1,40,gold(10000),TOKEN),
        new Quest(502001007L,502001006L,6,"001",1,45,gold(10000),TOKEN),
        new Quest(502001008L,502001007L,6,"001",1,50,gold(10000),TOKEN),
        new Quest(502001009L,502001008L,6,"001",1,55,gold(10000),TOKEN),
        new Quest(502001010L,502001009L,6,"001",1,60,gold(10000),TOKEN,board(3)),
        // Achievement.asset 502060002..008: one weapon at each listed level.
        new Quest(502060002L,0,6,"060",1,2,diamond(10),gold(10000),TAROT,TOKEN),
        new Quest(502060003L,502060002L,6,"060",1,10,diamond(10),gold(10000),TAROT,TOKEN),
        new Quest(502060004L,502060003L,6,"060",1,20,diamond(10),gold(10000),TAROT,TOKEN),
        new Quest(502060005L,502060004L,6,"060",1,30,diamond(10),board(5),TAROT,TOKEN),
        new Quest(502060006L,502060005L,6,"060",1,40,diamond(10),gold(10000),TOKEN),
        new Quest(502060007L,502060006L,6,"060",1,50,diamond(10),gold(10000),TOKEN),
        new Quest(502060008L,502060007L,6,"060",1,60,diamond(10),gold(10000),TOKEN),
        // Achievement.asset channel 25, 501060001..002: 1 then 12 weapons Lv60.
        new Quest(501060001L,0,1,"060",1,60,diamond(20),gold(20000)),
        new Quest(501060002L,501060001L,1,"060",12,60,diamond(50),gold(20000),board(4))
    };

    private CosmeticAchievements(){}

    static boolean handlesJob(String raw){
        if(raw==null)return false;
        for(Quest q:QUESTS)if(Long.toString(q.id).equals(raw))return true;
        return false;
    }
    private static Quest quest(String raw)throws IOException{
        for(Quest q:QUESTS)if(Long.toString(q.id).equals(raw))return q;
        throw new IOException("Unknown cosmetic achievement");
    }
    private static JSONObject claims(JSONObject state)throws Exception{
        JSONObject claimed=state.optJSONObject("cosmeticAchievementClaims");
        if(claimed==null){claimed=new JSONObject();state.put("cosmeticAchievementClaims",claimed);}
        return claimed;
    }
    private static int roleLevel(JSONObject state,JSONObject catalog){
        int level=state.optInt("starterProfile",0)==1?1:5;
        long exp=state.optLong("exp",0);
        JSONObject costs=catalog.optJSONObject("roleLevels");
        while(costs!=null&&level<100){
            long cost=costs.optLong(String.valueOf(level),Long.MAX_VALUE);
            if(cost<=0||exp<cost)break;
            exp-=cost;level++;
        }
        return level;
    }
    private static int weaponCount(JSONObject state,int level)throws Exception{
        JSONObject owned=state.optJSONObject("ownedServants");
        if(owned==null)return 0;
        int count=0;
        for(Iterator<String> it=owned.keys();it.hasNext();){
            ProtoWire servant=LocalEconomy.decode(owned.getString(it.next()));
            if(servant.number(12,0)>=level)count++;
        }
        return count;
    }
    private static int progress(JSONObject state,JSONObject catalog,Quest q)throws Exception{
        return q.type.equals("001")?roleLevel(state,catalog):weaponCount(state,q.targetLevel);
    }
    private static int target(Quest q){return q.type.equals("001")?q.targetLevel:q.targetCount;}
    private static boolean ready(JSONObject state,JSONObject catalog,Quest q,JSONObject claimed)
            throws Exception{
        if(!state.optBoolean("roleCreated",false) ||
           q.front!=0&&!claimed.optBoolean(Long.toString(q.front),false)&&
           !ProgressionTasks.permanentClaimed(state,q.front))return false;
        return progress(state,catalog,q)>=target(q);
    }
    static byte[] taskList(JSONObject state,JSONObject catalog,byte[] seed)throws Exception{
        ProtoWire result=ProtoWire.parse(seed);
        JSONObject claimed=state.optJSONObject("cosmeticAchievementClaims");
        if(claimed==null)claimed=new JSONObject();
        // Replace our own seed rows so a fixture cannot retain stale claims.
        for(Iterator<ProtoWire.Field> it=result.fields.iterator();it.hasNext();){
            ProtoWire.Field field=it.next();
            if((field.number==1||field.number==2)&&field.type==2){
                long id=ProtoWire.parse(field.data).number(field.number==1?1:3,0);
                if(handlesJob(Long.toString(id)))it.remove();
            }
        }
        for(Quest q:QUESTS){
            int status=(claimed.optBoolean(Long.toString(q.id),false)||
                q.questType==1&&ProgressionTasks.permanentClaimed(state,q.id))?1:
                ready(state,catalog,q,claimed)?0:-1;
            result.add(1,new ProtoWire().set(1,q.id).set(2,status).set(3,1)
                .text(4,q.type).bytes());
            result.add(2,new ProtoWire().set(1,q.questType).text(2,q.type)
                .set(3,q.id).set(4,Math.min(target(q),progress(state,catalog,q))).bytes());
        }
        return result.bytes();
    }
    private static byte[] loot(Quest quest){
        ProtoWire result=new ProtoWire();
        for(Reward reward:quest.rewards)result.add(1,reward.wire().bytes());
        return result.bytes();
    }
    static byte[] claim(JSONObject state,JSONObject catalog,Map<String,String> args)throws Exception{
        LocalDaily.requireRole(state,args);
        Quest q=quest(args.get("jobid"));
        // These are the same original IDs, conditions and rewards as the
        // permanent achievement catalog. Both routes use its one claim ledger.
        if(q.questType==1)return ProgressionTasks.bundled().claim(state,catalog,args);
        JSONObject claimed=claims(state);
        if(claimed.optBoolean(Long.toString(q.id),false))return loot(q);
        if(!ready(state,catalog,q,claimed))throw new IOException("Achievement incomplete");
        LocalEconomy.init(state,catalog);
        boolean inventory=false;
        for(Reward reward:q.rewards){
            LocalEconomy.grantItemReward(state,catalog,reward.json(),1);
            if(reward.type==3)inventory=true;
        }
        if(inventory)state.put("inventoryRevision",
            Math.addExact(state.optLong("inventoryRevision",0),1));
        claimed.put(Long.toString(q.id),true);
        return loot(q);
    }
}
