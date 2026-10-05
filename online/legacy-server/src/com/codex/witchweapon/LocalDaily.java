package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.IOException;
import java.util.*;

/** Original activity/quest protobuf data backed by one account's save. */
final class LocalDaily {
    private static final long DAY_OFFSET = 8L * 3600L;
    private static final long STREAK_ID = 26;
    private static final long TOTAL_ID = 25;
    private static final long STAMINA_ID = 999;
    private static final int[] STREAK_TYPE = {13, 3, 99, 3, 13, 20, 3};
    private static final long[] STREAK_ITEM = {0, 40220020L, 0, 40320001L, 0, 0, 40350003L};
    private static final long[] STREAK_AMOUNT = {500, 5, 10, 5, 1500, 50, 1};
    // These are the 15 quest_type=2 rows in the preserved achievement.txt.
    private static final long[] TASK_IDS = {
        502006001L,502018001L,502022001L,502022002L,502022003L,
        502022004L,502022005L,502022007L,502031001L,502034001L,
        502040001L,502043004L,502071002L,502074001L,502083001L
    };
    private static final int[] TASK_TYPES = {
        6,18,22,22,22,22,22,22,31,34,40,43,71,74,83
    };
    private static final int[] TASK_TARGETS = {
        12,1,10,1,1,1,1,1,1,1,1,400,1,1,1
    };
    // Original CN/25 daily rows; channel 22 has the same daily rewards.
    // Rows whose gameplay is not recovered remain visible and unfinished.
    private static final long[] ACTIVE_TASKS = TASK_IDS;
    private static final long[] LEGACY_ACTIVE_TASKS = {
        502018001L,502022001L,502022005L,502031001L,502034001L,502083001L
    };
    private static final int[][] ACTIVE_REWARD_TYPES = {
        {99},{18,10,21},{18,10,20,21},{18,10,20,21},{18,10,20,21},
        {18,10,20,21},{18,10,20,21},{18,10,20,21},{18,10,20,21},
        {18,10,20,21},{18,10,20,21},{18,21,20,3},
        {18,10,20,21},{18,10,20,21},{18,10,21}
    };
    private static final long[][] ACTIVE_REWARD_AMOUNTS = {
        {10},{4,100,40},{6,100,50,50},{6,100,50,50},{3,100,45,40},
        {3,100,50,50},{6,200,80,75},{3,100,50,50},{3,50,30,30},
        {3,100,50,50},{3,100,30,30},{5,50,70,1},
        {3,100,50,50},{2,100,50,40},{3,100,20}
    };
    private static final int TASK_REWARD_VERSION = 2;
    // Preserved daily-task UI: joining a guild grants 30 guild reputation
    // after each daily task. This is distinct from guild donation vitality.
    private static final long GUILD_REPUTATION_PER_TASK = 30;
    // The preserved task seed marks these original guide jobs as already
    // claimed. New online accounts must start them unfinished instead.
    // achievement.ab contains no item rewards for these guide jobs. The
    // preserved basestation stage 1001 uses job 509005002, while the later
    // smelter opening 1004 uses 509021001; they must not complete each other.
    private static final long[] GUIDE_TASK_IDS = {
        509005002L,509005003L,509005004L,509005005L,509005006L,509005009L,
        509005010L,509005011L,509021001L,509021002L,509021003L
    };
    private static final long[] GUIDE_STAGE_IDS = {
        3150001001L,3150001004L,3150001005L,3150001006L
    };
    private static final long[] GUIDE_STAGE_TASK_IDS = {
        509005002L,509021001L,509021002L,509021003L
    };

    /** The original battle callback reads BattleResult.ExtraInfo immediately. */
    static byte[] guideBattleResult(JSONObject state,long stage,byte[] seed) throws Exception {
        long jobId=0;
        for(int i=0;i<GUIDE_STAGE_IDS.length;i++)
            if(GUIDE_STAGE_IDS[i]==stage){jobId=GUIDE_STAGE_TASK_IDS[i];break;}
        if(jobId==0)throw new InvalidRequest("Unknown guide battle stage");
        ProtoWire battle=ProtoWire.parse(seed);
        ProtoWire extra=ProtoWire.parse(battle.data(4));
        ProtoWire achieve=ProtoWire.parse(extra.data(2));
        // Reaching and winning the 1005 encounter proves that the original
        // recID 5/6/7 story sequence has already played. The preserved client
        // stored those lesson breaks only in PlayerPrefs, so restore their
        // account-level jobs with the battle milestone as well.
        if(stage==3150001005L)for(long storyJob:new long[]{
                509005004L,509005005L,509005006L})
            completeBattleJob(achieve,storyJob,"005",
                Math.max(0,guideStatus(state,storyJob)));
        completeBattleJob(achieve,jobId,"021",Math.max(0,guideStatus(state,jobId)));
        extra.set(2,achieve.bytes());
        battle.set(4,extra.bytes());
        return battle.bytes();
    }

    private static void completeBattleJob(ProtoWire achievement,long id,String type,int status)
            throws Exception {
        boolean found=false;
        for(ProtoWire.Field field:achievement.fields)if(field.number==1&&field.type==2){
            ProtoWire existing=ProtoWire.parse(field.data);
            if(existing.number(1,0)!=id)continue;
            existing.set(2,status).set(3,1).text(4,type).set(5,1);
            field.data=existing.bytes();
            found=true;
        }
        if(!found)achievement.add(1,new ProtoWire().set(1,id).set(2,status)
            .set(3,1).text(4,type).set(5,1).bytes());
    }

    /** Attach the corresponding original achievement to a tutorial draw. */
    static byte[] guideDrawResult(JSONObject state,int serial,byte[] seed) throws Exception {
        if(serial!=1&&serial!=2)throw new InvalidRequest("Invalid guide draw serial");
        long jobId=serial==1?509005010L:509005011L;
        String type=serial==1?"030":"033";
        guideReady(state,jobId);
        ProtoWire result=ProtoWire.parse(seed);
        ProtoWire extra=ProtoWire.parse(result.data(2));
        ProtoWire achievement=ProtoWire.parse(extra.data(2));
        completeBattleJob(achievement,jobId,type,Math.max(0,guideStatus(state,jobId)));
        extra.set(2,achievement.bytes());
        result.set(2,extra.bytes());
        return result.bytes();
    }

    static boolean hasGuideDrawJob(byte[] response,int serial) throws Exception {
        long jobId=serial==1?509005010L:509005011L;
        ProtoWire result=ProtoWire.parse(response);
        ProtoWire extra=ProtoWire.parse(result.data(2));
        ProtoWire achievement=ProtoWire.parse(extra.data(2));
        for(ProtoWire.Field field:achievement.fields)if(field.number==1&&field.type==2)
            if(ProtoWire.parse(field.data).number(1,0)==jobId)return true;
        return false;
    }

    static final class InvalidRequest extends IOException {
        InvalidRequest(String message) { super(message); }
    }
    static final class Conflict extends IOException {
        Conflict(String message) { super(message); }
    }

    private LocalDaily() {}

    static long day(long unixSeconds) {
        return Math.floorDiv(Math.addExact(unixSeconds, DAY_OFFSET), 86400L);
    }

    static boolean claimRoute(String path) {
        return path.equals("/activity/sign/continuitygain") ||
            path.equals("/activity/sign/autogain");
    }

    static boolean dailyTask(String jobId) {
        if (jobId == null) return false;
        for (long id : TASK_IDS) if (String.valueOf(id).equals(jobId)) return true;
        return false;
    }
    static boolean guideTask(String jobId) {
        if(jobId==null)return false;
        for(long id:GUIDE_TASK_IDS)if(String.valueOf(id).equals(jobId))return true;
        return false;
    }
    private static boolean starter(JSONObject state) {
        return state.optInt("starterProfile",0)==1;
    }
    private static JSONObject guideStatuses(JSONObject state) throws Exception {
        JSONObject statuses=state.optJSONObject("tutorialTasks");
        if(statuses==null){statuses=new JSONObject();state.put("tutorialTasks",statuses);}
        return statuses;
    }
    private static int guideStatus(JSONObject state,long id) {
        JSONObject statuses=state.optJSONObject("tutorialTasks");
        return statuses==null?-1:statuses.optInt(String.valueOf(id),-1);
    }
    private static void guideReady(JSONObject state,long id) throws Exception {
        JSONObject statuses=guideStatuses(state);
        String key=String.valueOf(id);
        if(statuses.optInt(key,-1)<0)statuses.put(key,0);
    }
    private static void reconcileOpeningTasks(JSONObject state) throws Exception {
        long baseWins=state.optLong("tutorialWins_3150001001",0);
        long smelterWins=state.optLong("tutorialWins_3150001004",0);
        if(baseWins>0)guideReady(state,509005002L);
        if(smelterWins>0)guideReady(state,509021001L);
        // A short-lived server version incorrectly awarded the 1004 job for
        // 1001. Only its mistaken task status is removed; battle wins remain.
        if(baseWins>0 && smelterWins==0)
            guideStatuses(state).remove("509021001");
        if(state.optLong("tutorialWins_3150001005",0)>0)
            for(long storyJob:new long[]{509005004L,509005005L,509005006L})
                guideReady(state,storyJob);
    }
    /** A completed guide job has no configured item reward; claim changes status only. */
    static byte[] claimGuideTask(JSONObject state,String jobId,byte[] seed) throws Exception {
        if(!starter(state)||!guideTask(jobId))throw new InvalidRequest("Unknown guide job");
        if(!state.optBoolean("roleCreated",false))throw new InvalidRequest("Role required");
        long id=Long.parseLong(jobId);
        if(id==509005002L){
            if(state.optLong("tutorialWins_3150001001",0)<=0)
                throw new Conflict("Basestation guide job is not complete");
            guideReady(state,id);
        }
        if(id==509021001L && state.optLong("tutorialWins_3150001004",0)<=0)
            throw new Conflict("Smelter guide job is not complete");
        int status=guideStatus(state,id);
        if(status<0)throw new Conflict("Guide job is not complete");
        if(status==0)guideStatuses(state).put(jobId,1);
        return seed;
    }

    static void requireRole(JSONObject state, Map<String,String> args) throws InvalidRequest {
        if (!state.optBoolean("roleCreated", false)) throw new InvalidRequest("Role required");
        String role = args.get("roleid");
        if (role == null || !role.matches("[1-9][0-9]{0,18}") ||
                !role.equals(String.valueOf(state.optLong("legacyRoleId",0))))
            throw new InvalidRequest("Wrong roleid");
    }

    /** Calling activity/list/get records this account's first opening today. */
    static void refresh(JSONObject state, long now) throws Exception {
        long today = day(now);
        JSONObject login = state.optJSONObject("dailyLogin");
        if (login == null) login = new JSONObject();
        long last = login.optLong("day", Long.MIN_VALUE);
        if (today < last) throw new IOException("Server day moved backwards");
        if (today > last) {
            int total = Math.addExact(login.optInt("totalDays",0), 1);
            int streak = today - last == 1 ? login.optInt("streakDays",0) + 1 : 1;
            if (streak > 7) streak = 1;
            login.put("day", today).put("totalDays", total).put("streakDays", streak);
            login.put("lastOpenAt", now);
            state.put("dailyLogin", login);
        }
        JSONObject tasks = state.optJSONObject("dailyTasks");
        if (tasks == null || tasks.optLong("day",Long.MIN_VALUE) != today) {
            tasks = new JSONObject();
            tasks.put("day",today).put("progress",new JSONObject()).put("claimed",new JSONObject());
            state.put("dailyTasks",tasks);
        }
    }

    /** Appends IDs 25, 26 and 999 to ActivityListLua.repeated field 1. */
    static void appendTo(ProtoWire list, JSONObject state, long now) throws Exception {
        refresh(state,now);
        JSONObject login = state.getJSONObject("dailyLogin");
        long today = login.getLong("day");
        int total = login.getInt("totalDays"), streak = login.getInt("streakDays");
        boolean totalCan = total > 0 && total % 15 == 0 &&
            login.optLong("totalClaimDay",Long.MIN_VALUE) != today;
        boolean streakCan = streak > 0 &&
            login.optLong("streakClaimDay",Long.MIN_VALUE) != today;
        ProtoWire totalData = new ProtoWire().set(1,total).set(2,
            Math.max(0,total / 15 - (totalCan ? 1 : 0))).set(3,totalCan ? 1 : 0);
        ProtoWire streakData = new ProtoWire().set(1,streak).set(2,login.optLong("lastOpenAt",now))
            .set(3,streakCan ? 1 : 0);
        list.add(1,new ProtoWire().set(1,14).set(2,TOTAL_ID).set(107,totalData.bytes()).bytes());
        list.add(1,new ProtoWire().set(1,15).set(2,STREAK_ID).set(108,streakData.bytes()).bytes());
        // Original main-scene Lua dereferences activity 999 unconditionally.
        list.add(1,new ProtoWire().set(1,7).set(2,STAMINA_ID)
            .set(105,new ProtoWire().set(3,0).bytes()).bytes());
    }

    private static ProtoWire loot(int type,long item,long amount) {
        ProtoWire object = new ProtoWire().set(1,type);
        if (item > 0) object.set(2,item);
        if (type == 3) object.set(4,amount);
        else object.set(3,amount).set(4,amount);
        return new ProtoWire().add(1,object.bytes());
    }

    private static void grant(JSONObject state, JSONObject catalog,
                              int type,long item,long amount,long now) throws Exception {
        LocalEconomy.init(state,catalog);
        if (grantTaskResource(state,type,amount,now)) {
            return;
        }
        LocalEconomy.grantItemReward(state,catalog,new JSONObject()
            .put("type",type).put("id",item).put("value",type==3?0:amount)
            .put("count",type==3?amount:0),1);
    }

    private static boolean grantTaskResource(JSONObject state,int type,long amount,long now) throws Exception {
        String key;
        if(type==18)key="activeCurrencyGreen";
        else if(type==10)key="exp";
        else if(type==20) {
            VipSystem.grantFreeExp(state,amount,now);
            return true;
        }
        else if(type==21)key="vipPoint";
        else return false;
        LocalEconomy.addResource(state,key,0,amount);
        return true;
    }

    private static ProtoWire taskLoot(int index,boolean guildRewarded) {
        ProtoWire result=new ProtoWire();
        for(int i=0;i<ACTIVE_REWARD_TYPES[index].length;i++) {
            int type=ACTIVE_REWARD_TYPES[index][i];
            long amount=ACTIVE_REWARD_AMOUNTS[index][i];
            long item=taskRewardItem(index,type);
            ProtoWire reward=new ProtoWire().set(1,type).set(4,amount);
            if(item>0)reward.set(2,item);
            if(type!=3)reward.set(3,amount);
            result.add(1,reward.bytes());
        }
        if(guildRewarded)result.add(1,new ProtoWire().set(1,19)
            .set(3,GUILD_REPUTATION_PER_TASK).set(4,GUILD_REPUTATION_PER_TASK).bytes());
        return result;
    }

    private static void grantGuildReputation(JSONObject state)throws Exception {
        long next=Math.addExact(state.optLong("guildCurrency",0),GUILD_REPUTATION_PER_TASK);
        if(next>Integer.MAX_VALUE)throw new IOException("Guild currency exceeds protocol limit");
        state.put("guildCurrency",next);
    }

    private static long taskRewardItem(int index,int type){
        return TASK_IDS[index]==502043004L&&type==3?40330099L:0;
    }
    private static void grantTaskRewards(JSONObject state,JSONObject catalog,int index,
                                         boolean includeGreen,long now) throws Exception {
        boolean inventory=false;
        for(int i=0;i<ACTIVE_REWARD_TYPES[index].length;i++) {
            int type=ACTIVE_REWARD_TYPES[index][i];
            if(type==18 && !includeGreen)continue;
            if(!grantTaskResource(state,type,ACTIVE_REWARD_AMOUNTS[index][i],now)){
                if(catalog==null)throw new IOException("Daily reward catalog required");
                grant(state,catalog,type,taskRewardItem(index,type),ACTIVE_REWARD_AMOUNTS[index][i],now);
                if(type==2||type==3)inventory=true;
            }
        }
        if(inventory)state.put("inventoryRevision",
            Math.addExact(state.optLong("inventoryRevision",0),1));
    }

    /** Prior claims paid only green. Complete current-day claims exactly once. */
    private static void upgradeClaimedRewards(JSONObject state,long now) throws Exception {
        JSONObject tasks=state.getJSONObject("dailyTasks");
        JSONObject claimed=tasks.getJSONObject("claimed");
        JSONObject versions=tasks.optJSONObject("rewardVersion");
        if(versions==null){versions=new JSONObject();tasks.put("rewardVersion",versions);}
        for(long legacyId:LEGACY_ACTIVE_TASKS) {
            int i=indexOf(legacyId);String key=String.valueOf(legacyId);
            if(claimed.optBoolean(key,false) &&
                    versions.optInt(key,1)<TASK_REWARD_VERSION) {
                grantTaskRewards(state,null,i,false,now);
                versions.put(key,TASK_REWARD_VERSION);
            }
        }
    }

    /** Date-keyed idempotence: a response retry never grants the same day twice. */
    static byte[] claim(JSONObject state, JSONObject catalog, String path,
                        Map<String,String> args,long now) throws Exception {
        requireRole(state,args);
        refresh(state,now);
        JSONObject login = state.getJSONObject("dailyLogin");
        long today = login.getLong("day");
        if (path.equals("/activity/sign/continuitygain")) {
            if (!String.valueOf(STREAK_ID).equals(args.get("baseid")))
                throw new InvalidRequest("Wrong activity baseid");
            int index = login.getInt("streakDays") - 1;
            if (index < 0 || index >= 7) throw new Conflict("No streak reward");
            if (login.optLong("streakClaimDay",Long.MIN_VALUE) != today) {
                grant(state,catalog,STREAK_TYPE[index],STREAK_ITEM[index],STREAK_AMOUNT[index],now);
                login.put("streakClaimDay",today);
            }
            return loot(STREAK_TYPE[index],STREAK_ITEM[index],STREAK_AMOUNT[index]).bytes();
        }
        if (path.equals("/activity/sign/autogain")) {
            if (!String.valueOf(TOTAL_ID).equals(args.get("baseid")))
                throw new InvalidRequest("Wrong activity baseid");
            if (login.getInt("totalDays") % 15 != 0) throw new Conflict("Cumulative reward not due");
            if (login.optLong("totalClaimDay",Long.MIN_VALUE) != today) {
                grant(state,catalog,3,40350003L,3,now);
                login.put("totalClaimDay",today);
            }
            return loot(3,40350003L,3).bytes();
        }
        throw new InvalidRequest("Unknown daily claim route");
    }

    private static int indexOf(long id) {
        for (int i=0;i<TASK_IDS.length;i++) if (TASK_IDS[i]==id) return i;
        return -1;
    }

    private static void increment(JSONObject state,long id,long amount,long now) throws Exception {
        if (amount <= 0) return;
        refresh(state,now);
        int index = indexOf(id);
        if (index < 0) return;
        JSONObject progress = state.getJSONObject("dailyTasks").getJSONObject("progress");
        String key = String.valueOf(id);
        long old = progress.optLong(key,0);
        progress.put(key,Math.min(TASK_TARGETS[index],Math.addExact(old,amount)));
    }
    private static int originalInstanceType(long stage){
        // instance.txt: normal 311...001..010, hard ...011..015;
        // 312 groups 1..4 are Rift, 5..6 Dojo, and 7 the furnace.
        if(stage>=3110001001L&&stage<=3110016015L){
            long order=stage%1000;
            return order>=1&&order<=10?2:order>=11&&order<=15?3:0;
        }
        if(stage>=3120001001L&&stage<=3120007999L){
            long group=(stage/1000)%10000;
            return group>=1&&group<=4?5:group==5||group==6?6:group==7?14:0;
        }
        return 0;
    }
    private static long clears(JSONObject record){
        return record==null?0:Math.addExact(Math.max(0,record.optLong("wins",0)),
            Math.max(0,record.optLong("sweeps",0)));
    }
    static long mainlineClears(JSONObject state,int type)throws Exception{
        JSONObject stages=state.optJSONObject("mainlineStages");long count=0;
        if(stages!=null)for(Iterator<String> it=stages.keys();it.hasNext();){
            String key=it.next();
            if(key.matches("311[0-9]{7}")&&originalInstanceType(Long.parseLong(key))==type)
                count=Math.addExact(count,clears(stages.optJSONObject(key)));
        }
        return count;
    }
    private static long changedClears(JSONObject before,JSONObject after,String ledger,int type)
            throws Exception{
        JSONObject old=before.optJSONObject(ledger),updated=after.optJSONObject(ledger);long count=0;
        if(updated==null)return 0;
        for(Iterator<String> it=updated.keys();it.hasNext();){
            String key=it.next();
            if(!key.matches("31[12][0-9]{7}")||originalInstanceType(Long.parseLong(key))!=type)continue;
            long delta=Math.max(0,clears(updated.optJSONObject(key))-
                clears(old==null?null:old.optJSONObject(key)));
            count=Math.addExact(count,delta);
        }
        return count;
    }
    private static long taskProgress(JSONObject tasks,int index)throws Exception{
        JSONObject progress=tasks.getJSONObject("progress"),claimed=tasks.getJSONObject("claimed");
        if(TASK_IDS[index]!=502006001L)return Math.max(0,progress.optLong(Long.toString(TASK_IDS[index]),0));
        // The summary quest counts completed original daily jobs. Claiming
        // a reward is not an additional completion, and it cannot count itself.
        long count=0;
        for(int i=1;i<TASK_IDS.length;i++)if(claimed.optBoolean(Long.toString(TASK_IDS[i]),false)||
            progress.optLong(Long.toString(TASK_IDS[i]),0)>=TASK_TARGETS[i])count++;
        return count;
    }
    /** Call only after the original powder-shop purchase actually succeeds. */
    static void recordShopPurchase(JSONObject state,Map<String,String> args,long now)throws Exception{
        String set=args.containsKey("setid")?args.get("setid"):args.get("shopsetid");
        if("44000188".equals(set))increment(state,502040001L,1,now);
    }
    /** The guild transaction owns validation and idempotence for these callbacks. */
    static void recordGuildDonation(JSONObject state,long now)throws Exception{
        increment(state,502074001L,1,now);
    }
    static void recordGuildSupport(JSONObject state,long now)throws Exception{
        increment(state,502071002L,1,now);
    }

    /** Run only after a successful gameplay mutation, before the save commit. */
    static void observe(JSONObject state,JSONObject before,String path,long now) throws Exception {
        if(starter(state)) {
            // 509005003 is the original naming job (achievement type 008).
            if(path.equals("/role/rename")&&before.optBoolean("namePending",false)&&
                !state.optBoolean("namePending",true))guideReady(state,509005003L);
            // Each type-021 job follows its own original instance ID. A
            // failed or repeated settlement cannot advance another route.
            if(path.equals("/level/pushGuideProgress"))for(int i=0;i<GUIDE_STAGE_IDS.length;i++) {
                String field="tutorialWins_"+GUIDE_STAGE_IDS[i];
                if(state.optLong(field,0)>before.optLong(field,0)){
                    guideReady(state,GUIDE_STAGE_TASK_IDS[i]);
                    if(GUIDE_STAGE_IDS[i]==3150001005L)
                        for(long storyJob:new long[]{509005004L,509005005L,509005006L})
                            guideReady(state,storyJob);
                }
            }
        }
        if(path.equals("/level/pushMainLineProgress")||path.equals("/level/pushDailyProgress")||
           path.equals("/level/pushMaterialProgress")||path.equals("/level/sweep")){
            long normal=changedClears(before,state,"mainlineStages",2);
            long hard=changedClears(before,state,"mainlineStages",3);
            if(normal==0&&hard==0&&path.equals("/level/pushMainLineProgress")){
                long fallback=Math.max(0,state.optLong("wins")-before.optLong("wins"))+
                    Math.max(0,state.optLong("mainlineWins")-before.optLong("mainlineWins"));
                int type=originalInstanceType(state.optLong("activeStage",0));
                if(type==3)hard=fallback;
                else if(type==2||state.optLong("activeStage",0)==0)normal=fallback;
            }
            increment(state,502022001L,normal,now);
            increment(state,502022002L,hard,now);
            increment(state,502022003L,changedClears(before,state,"dailyBattleStages",5),now);
            increment(state,502022004L,changedClears(before,state,"dailyBattleStages",6),now);
            increment(state,502022007L,changedClears(before,state,"furnaceStages",14),now);
            increment(state,502022005L,Math.max(0,state.optLong("mazeWins")-before.optLong("mazeWins")),now);
        }
        if(path.startsWith("/level/")||path.startsWith("/ap/"))
            increment(state,502043004L,Math.max(0,before.optLong("activityStamina",0)-
                state.optLong("activityStamina",0)),now);
        if (path.startsWith("/draw/gold/"))
            increment(state,502031001L,Math.max(0,state.optLong("drawCount")-before.optLong("drawCount")),now);
        if (path.startsWith("/draw/rmb/"))
            increment(state,502034001L,Math.max(0,state.optLong("drawCount")-before.optLong("drawCount")),now);
        if (path.equals("/servant/weapon") && servantAdvanced(before,state,12,16))
            increment(state,502018001L,1,now);
        if (path.equals("/servant/exp") && servantAdvanced(before,state,2,3))
            increment(state,502083001L,1,now);
    }

    private static boolean servantAdvanced(JSONObject before,JSONObject after,
                                           int levelField,int expField) throws Exception {
        JSONObject old = before.optJSONObject("ownedServants"),
            updated = after.optJSONObject("ownedServants");
        if (old == null || updated == null) return false;
        for (Iterator<String> it=updated.keys();it.hasNext();) {
            String key=it.next();
            if (!old.has(key)) continue;
            ProtoWire previous=LocalEconomy.decode(old.getString(key));
            ProtoWire current=LocalEconomy.decode(updated.getString(key));
            long oldLevel=previous.number(levelField,0),newLevel=current.number(levelField,0);
            if (newLevel>oldLevel || newLevel==oldLevel &&
                current.number(expField,0)>previous.number(expField,0)) return true;
        }
        return false;
    }

    /** Keep tutorial/bond jobs and restore all fifteen original daily rows. */
    static byte[] taskList(JSONObject state,byte[] seed,long now) throws Exception {
        refresh(state,now);
        upgradeClaimedRewards(state,now);
        ProtoWire result = ProtoWire.parse(seed);
        JSONObject tasks=state.getJSONObject("dailyTasks");
        JSONObject claimed=tasks.getJSONObject("claimed");
        if(starter(state)) {
            guideStatuses(state);
            reconcileOpeningTasks(state);
            // Some original create paths can submit a name before the first
            // task fetch. The persisted pending flag is authoritative.
            if(state.optBoolean("roleCreated",false)&&!state.optBoolean("namePending",true))
                guideReady(state,509005003L);
        }
        Set<Long> existing=new HashSet<Long>();
        for (ProtoWire.Field f:result.fields) if(f.number==1 && f.type==2) {
            ProtoWire job=ProtoWire.parse(f.data);
            long id=job.number(1,0);
            existing.add(id);
            if(starter(state)&&guideTask(String.valueOf(id))) {
                job.set(2,guideStatus(state,id));
                f.data=job.bytes();
            }
        }
        // The author's static task fixture predates this preserved 1001
        // route. Add its original type-021 job only for starter accounts when
        // the fixture lacks it; existing accounts retain their original list.
        if(starter(state)&&!existing.contains(509005002L))
            result.add(1,new ProtoWire().set(1,509005002L)
                .set(2,guideStatus(state,509005002L)).set(3,1)
                .text(4,"021").set(5,1).bytes());
        for(Iterator<ProtoWire.Field> it=result.fields.iterator();it.hasNext();){
            ProtoWire.Field field=it.next();
            if((field.number==1||field.number==2)&&field.type==2){
                long id=ProtoWire.parse(field.data).number(field.number==1?1:3,0);
                if(dailyTask(Long.toString(id)))it.remove();
            }
        }
        for(int i=0;i<TASK_IDS.length;i++) {
            long id=TASK_IDS[i];
            String key=String.valueOf(id), type=String.valueOf(TASK_TYPES[i]);
            long count=taskProgress(tasks,i);
            int status=claimed.optBoolean(key,false)?1:count>=TASK_TARGETS[i]?0:-1;
            result.add(1,new ProtoWire().set(1,id).set(2,status).set(3,1).text(4,type).bytes());
            result.add(2,new ProtoWire().set(1,2).text(2,type).set(3,id)
                .set(4,Math.min(TASK_TARGETS[i],count)).bytes());
        }
        return result.bytes();
    }

    /** All original resources are granted atomically and only once per task/day. */
    static byte[] claimTask(JSONObject state,JSONObject catalog,Map<String,String> args,long now) throws Exception {
        return claimTask(state,catalog,args,now,false);
    }
    static byte[] claimTask(JSONObject state,JSONObject catalog,Map<String,String> args,long now,
                            boolean verifiedGuildMember) throws Exception {
        requireRole(state,args);
        refresh(state,now);
        String raw=args.get("jobid");
        if(raw==null || !raw.matches("[1-9][0-9]{0,18}"))throw new InvalidRequest("Wrong jobid");
        long id;
        try { id=Long.parseLong(raw); }
        catch(NumberFormatException ex) { throw new InvalidRequest("Wrong jobid"); }
        int active=-1;
        for(int i=0;i<ACTIVE_TASKS.length;i++)if(ACTIVE_TASKS[i]==id)active=i;
        if(active<0)throw new Conflict("Unknown daily task");
        JSONObject tasks=state.getJSONObject("dailyTasks"),progress=tasks.getJSONObject("progress"),
            claimed=tasks.getJSONObject("claimed");
        JSONObject guildRewarded=tasks.optJSONObject("guildRewarded");
        if(guildRewarded==null){guildRewarded=new JSONObject();tasks.put("guildRewarded",guildRewarded);}
        String key=String.valueOf(id);
        if(taskProgress(tasks,indexOf(id))<TASK_TARGETS[indexOf(id)])throw new Conflict("Daily task incomplete");
        upgradeClaimedRewards(state,now);
        JSONObject versions=tasks.getJSONObject("rewardVersion");
        if(!claimed.optBoolean(key,false)) {
            grantTaskRewards(state,catalog,active,true,now);
            if(verifiedGuildMember){grantGuildReputation(state);guildRewarded.put(key,true);}
            claimed.put(key,true);
            versions.put(key,TASK_REWARD_VERSION);
        }
        return taskLoot(active,guildRewarded.optBoolean(key,false)).bytes();
    }

    /** The original one-key button uses /task/updatemore, not /task/update. */
    static byte[] claimTaskBatch(JSONObject state,JSONObject catalog,
                                 Map<String,String> args,long now) throws Exception {
        return claimTaskBatch(state,catalog,args,now,false);
    }
    static byte[] claimTaskBatch(JSONObject state,JSONObject catalog,
                                 Map<String,String> args,long now,
                                 boolean verifiedGuildMember) throws Exception {
        requireRole(state,args);
        refresh(state,now);
        String raw=args.containsKey("jobid")?args.get("jobid"):args.get("jobids");
        Set<Long> requested=new LinkedHashSet<Long>();
        if(raw==null || raw.trim().isEmpty() || raw.trim().equals("0")) {
            // Some clients send only the daily tab's category for a batch.
            // Never treat a missing or different category as permission to
            // claim unrelated quest types.
            if(!"2".equals(args.get("typeid")))
                throw new InvalidRequest("Daily batch needs jobid or typeid 2");
            for(long id:ACTIVE_TASKS)requested.add(id);
        } else {
            if(raw.length()>256)throw new InvalidRequest("Daily batch too large");
            for(String token:raw.trim().split("[,|;\\s]+")) {
                if(!token.matches("[1-9][0-9]{0,18}"))
                    throw new InvalidRequest("Invalid daily batch jobid");
                long id;
                try{id=Long.parseLong(token);}
                catch(NumberFormatException ex){throw new InvalidRequest("Invalid daily batch jobid");}
                boolean active=false;
                for(long known:ACTIVE_TASKS)if(known==id){active=true;break;}
                if(!active)throw new InvalidRequest("Unsupported daily batch jobid");
                requested.add(id);
            }
        }
        JSONObject tasks=state.getJSONObject("dailyTasks"),progress=tasks.getJSONObject("progress"),
            claimed=tasks.getJSONObject("claimed");
        JSONObject guildRewarded=tasks.optJSONObject("guildRewarded");
        if(guildRewarded==null){guildRewarded=new JSONObject();tasks.put("guildRewarded",guildRewarded);}
        upgradeClaimedRewards(state,now);
        JSONObject versions=tasks.getJSONObject("rewardVersion");
        ProtoWire result=new ProtoWire();
        for(int i=0;i<ACTIVE_TASKS.length;i++) {
            long id=ACTIVE_TASKS[i];String key=String.valueOf(id);
            if(!requested.contains(id) || claimed.optBoolean(key,false) ||
                taskProgress(tasks,indexOf(id))<TASK_TARGETS[indexOf(id)])continue;
            grantTaskRewards(state,catalog,i,true,now);
            if(verifiedGuildMember){grantGuildReputation(state);guildRewarded.put(key,true);}
            claimed.put(key,true);
            versions.put(key,TASK_REWARD_VERSION);
            for(ProtoWire.Field field:taskLoot(i,guildRewarded.optBoolean(key,false)).fields)
                result.add(1,field.data);
        }
        if(!result.fields.isEmpty()) {
            tasks.put("batchLast",new JSONObject().put("request",requested.toString())
                .put("response",Base64.encodeToString(result.bytes(),Base64.NO_WRAP)));
            return result.bytes();
        }
        // A transport retry should see the same presentation without paying
        // twice. A newly completed task above still produces a fresh result.
        JSONObject previous=tasks.optJSONObject("batchLast");
        if(previous!=null && requested.toString().equals(previous.optString("request","")))
            return Base64.decode(previous.getString("response"),Base64.DEFAULT);
        return result.bytes();
    }
}
