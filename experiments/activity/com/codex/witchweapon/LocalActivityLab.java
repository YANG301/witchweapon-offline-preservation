package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.*;

/** Isolated local reconstruction. Layouts are original; dynamic rules are local. */
final class LocalActivityLab {
    static final long FIRST=3190001001L, LAST=3190001025L;
    static final int EVENT=5, RULE=3, FLOOR_LIMIT=50;
    static final long TIME_ID=1030005L, CURRENCY=40330104L, STORY_GROUP=6030001L;
    // Original UIUtil time labels convert to Int32; keep the lab clock representable.
    static final long OPEN_START=1577808000L, OPEN_END=2082758400L;
    private static final String NS="labActivity";
    private static final int[] GUIDE_IDS={1,2,3,4,5,6,7,8,9,10,11,12,13,50,200,201,202,203,204,205,206,207,208,209,210,211,212,213,214,215,216,218,219,300,301,302,303,304,305};
    private static final long[] GUIDE_TASKS={509005003L,509005004L,509005005L,509005006L,509005009L,509005010L,509005011L,509021001L,509021002L,509021003L};
    private static final SecureRandom RANDOM=new SecureRandom();
    private static JSONObject catalog;
    private static JSONObject startupRoleCatalog;
    private static final Set<String> PATHS=Collections.unmodifiableSet(new HashSet<String>(Arrays.asList(
        "/ap/instance/get","/ap/getInfo","/ap/R3/getInfo","/ap/R3/getData",
        "/ap/r3/getInfo","/ap/r3/getData","/ap/getMobs","/ap/getRoleInfo",
        "/ap/startBattle","/ap/win","/ap/reset","/ap/enter","/ap/instance/enter",
        "/ap/getInitStamina","/ap/getDailyStamina","/ap/initStamina","/ap/dailyStamina",
        "/ap/gainInitStamina","/ap/gainDailyStamina","/ap/instance/initStamina",
        "/ap/stamina/init/gain","/ap/stamina/daily/gain",
        "/ap/instance/dailyStamina","/ap/buyStamina","/ap/getStamina",
        "/ap/getProfit","/ap/getRank","/ap/rank","/ap/lose","/ap/cancel")));

    static final class Rejected extends IOException {
        final String code;
        Rejected(String code){super(code);this.code=code;}
    }
    static final class Action {
        final byte[] response; final boolean changed;
        Action(byte[] response,boolean changed){this.response=response;this.changed=changed;}
    }
    static String normalize(String path){return path.startsWith("/game/")?path.substring(5):path;}
    static boolean contains(long id){return id>=FIRST&&id<=LAST;}
    static void configureRoleCatalog(JSONObject roleCatalog){startupRoleCatalog=roleCatalog;}
    static Set<String> routes(){
        Set<String> result=new HashSet<String>(PATHS);
        for(String path:PATHS)result.add("/game"+path);
        return result;
    }
    static boolean direct(String path){return PATHS.contains(normalize(path));}
    static JSONObject bundled() throws Exception {
        if(catalog!=null)return catalog;
        synchronized(LocalActivityLab.class){
            if(catalog!=null)return catalog;
            InputStream in=LocalActivityLab.class.getResourceAsStream("/activity_catalog.json");
            if(in==null)throw new IOException("Local activity catalog resource missing");
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            try{byte[] buffer=new byte[16384];int n;while((n=in.read(buffer))!=-1)out.write(buffer,0,n);}
            finally{in.close();}
            JSONObject loaded=new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8));
            if(loaded.getInt("schemaVersion")!=1||!"local-activity-lab".equals(loaded.getString("mode"))||
               loaded.getJSONObject("event").getInt("id")!=EVENT||loaded.getJSONObject("stages").length()!=25)
                throw new IOException("Invalid isolated activity catalog");
            for(long id=FIRST;id<=LAST;id++){
                JSONObject stage=loaded.getJSONObject("stages").getJSONObject(Long.toString(id));
                if(stage.getLong("id")!=id||!stage.has("combatJson")||!stage.has("combatMobInfo"))
                    throw new IOException("Incomplete local activity layout");
                Base64.decode(stage.getString("combatMobInfo"),0);
            }
            catalog=loaded;return catalog;
        }
    }
    static void install(JSONObject responses)throws Exception {
        JSONObject stages=bundled().getJSONObject("stages");
        for(long id=FIRST;id<=LAST;id++){
            JSONObject stage=stages.getJSONObject(Long.toString(id));
            responses.put("/combat/mob/json#"+id,new JSONObject().put("type","application/json")
                .put("body",stage.getJSONObject("combatJson").toString()));
            responses.put("/combat/mob/info#"+id,new JSONObject().put("type","application/octet-stream")
                .put("base64",stage.getString("combatMobInfo")));
        }
    }
    private static JSONObject lab(JSONObject state)throws Exception{return state.getJSONObject(NS);}
    private static long day(long now){return Math.floorDiv(now+28800L,86400L);}
    private static long constant(String name,long fallback)throws Exception {
        JSONArray rows=bundled().getJSONArray("constants");
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);if(!name.equals(row.optString("ID")))continue;
            for(String key:new String[]{"value3","value1","value2","value4"}){
                String value=row.optString(key);if(value.matches("[0-9]+"))return Long.parseLong(value);
            }
        }
        return fallback;
    }
    private static long storyPrice()throws Exception{
        return Long.parseLong(bundled().getJSONArray("stories").getJSONObject(0).getString("unlock_value"));
    }
    /** Existing role fields are only the projection used by the original local client. */
    static boolean initialize(JSONObject state,JSONObject roleCatalog,long now)throws Exception {
        if(roleCatalog==null)roleCatalog=startupRoleCatalog;
        String before=state.toString();
        JSONObject activity=state.optJSONObject(NS);
        if(activity==null){
            if(state.optBoolean("roleCreated",false))throw new Rejected("REFUSE_NON_LAB_SAVE");
            activity=new JSONObject().put("schemaVersion",1).put("mode","local-activity-lab")
                .put("eventId",EVENT).put("floor",1).put("maxFloor",1).put("resetFloor",1)
                .put("resetDay",day(now)).put("resetCount",0).put("lastReset",0L)
                .put("stamina",Long.parseLong(bundled().getJSONObject("event").getJSONObject("originalRow").getString("init_stamina")))
                .put("initClaimed",true).put("dailyClaimDay",-1L).put("regenAt",now)
                .put("currency",storyPrice()*bundled().getJSONArray("storyIds").length())
                .put("earnedCurrency",0L).put("totalCombat",0L).put("consumedStamina",0L)
                .put("completed",false).put("routeWins",new JSONObject())
                .put("storyUnlocked",new JSONObject()).put("shopPurchases",new JSONObject())
                .put("transactions",new JSONObject()).put("entered",false).put("profileExpanded",false);
            state.put(NS,activity);
            state.put("roleCreated",true).put("name","本地活动测试").put("namePending",false)
                .put("starterProfile",1).put("stamina",200L).put("gold",1000000L).put("rmb",0L);
            if(state.optLong("legacyRoleId",0)<=0)
                state.put("legacyRoleId",1000000000000L+Math.floorMod(RANDOM.nextLong(),7000000000000L));
            JSONObject guides=new JSONObject();for(int id:GUIDE_IDS)guides.put(Integer.toString(id),-2);
            state.put("guidePoints",guides);
        }
        // The original client builds tutorial progress from Quest jobs on login,
        // before /guide/get. This event-only fixture has already finished them.
        JSONObject tutorial=state.optJSONObject("tutorialTasks");
        if(tutorial==null){tutorial=new JSONObject();state.put("tutorialTasks",tutorial);}
        JSONObject guideClaims=state.optJSONObject("progressionTaskClaims");
        if(guideClaims==null){guideClaims=new JSONObject();state.put("progressionTaskClaims",guideClaims);}
        for(long id:GUIDE_TASKS){tutorial.put(Long.toString(id),1);guideClaims.put(Long.toString(id),true);}
        // This APK retains the earlier basestation opening rather than the later furnace one.
        tutorial.put("509005002",1);guideClaims.put("509005002",true);
        if(roleCatalog!=null&&!activity.optBoolean("profileExpanded")){
            LocalEconomy.init(state,roleCatalog);
            long exp=0;JSONObject costs=roleCatalog.getJSONObject("roleLevels");
            for(int level=1;level<60;level++)exp=Math.addExact(exp,costs.getLong(Integer.toString(level)));
            state.put("exp",exp);
            JSONObject servants=state.getJSONObject("ownedServants");
            for(Iterator<String> it=servants.keys();it.hasNext();){
                String key=it.next();ProtoWire servant=LocalEconomy.decode(servants.getString(key));
                servant.set(2,60).set(9,1).set(10,0).set(12,60).set(16,0);
                servants.put(key,LocalEconomy.encode(servant));
            }
            activity.put("profileExpanded",true);
        }
        if(activity.optLong("resetDay",-1)!=day(now))
            activity.put("resetDay",day(now)).put("resetCount",0);
        long anchor=activity.optLong("regenAt",now),period=constant("ACTIVITY_STAMINA_RESTORE_PERIOD",300);
        long stamina=activity.optLong("stamina"),initial=500;
        if(stamina<initial&&now>anchor&&period>0){
            long gained=(now-anchor)/period;
            if(gained>0)activity.put("stamina",Math.min(initial,stamina+gained))
                .put("regenAt",anchor+gained*period);
        }else if(stamina>=initial)activity.put("regenAt",now);
        project(state);return !before.equals(state.toString());
    }
    private static void project(JSONObject state)throws Exception {
        JSONObject activity=lab(state);
        state.put("activityStamina",activity.getLong("stamina"));
        // RoleInstanceProto 129 is ActivityStoryCurrency; 128 belongs to ordinary stories.
        state.put("activityStoryCurrency",activity.getLong("currency"));
        JSONObject items=state.optJSONObject("items");
        if(items!=null)items.put(Long.toString(CURRENCY),activity.getLong("currency"));
    }
    private static JSONObject stage(long id)throws Exception {
        if(!contains(id))throw new Rejected("UNKNOWN_ACTIVITY_STAGE");
        return bundled().getJSONObject("stages").getJSONObject(Long.toString(id));
    }
    private static long arg(Map<String,String> args,long fallback,String...keys)throws Exception {
        String value=null;
        for(String key:keys)if(args.containsKey(key)){
            String candidate=args.get(key);if(value!=null&&!value.equals(candidate))throw new Rejected("CONFLICTING_ARGUMENTS");
            value=candidate;
        }
        if(value==null||value.isEmpty())return fallback;
        if(!value.matches("[0-9]{1,18}"))throw new Rejected("INVALID_ACTIVITY_NUMBER");
        try{return Long.parseLong(value);}catch(NumberFormatException ex){throw new Rejected("INVALID_ACTIVITY_NUMBER");}
    }
    private static long stageArg(Map<String,String> args)throws Exception{return arg(args,0,"levelid","instanceid");}
    private static long[] routesAt(int floor){
        // The original panel has three general buttons and one hard button.
        long[] ids=new long[4];
        for(int i=0;i<3;i++)ids[i]=FIRST+Math.floorMod((floor-1)*3+i,15);
        ids[3]=FIRST+15+Math.floorMod(floor-1,10);return ids;
    }
    private static int floor(JSONObject activity){return Math.max(1,Math.min(FLOOR_LIMIT,activity.optInt("floor",1)));}
    private static long resetCost(JSONObject activity)throws Exception{
        JSONArray rows=bundled().getJSONArray("activityGameData");int current=floor(activity);
        for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);
            if(row.optInt("ID")==current){
                String raw=row.optString("rule3_reset_cost").trim();
                // Original CSV blanks are the default zero, not an invalid integer.
                if(raw.isEmpty())return 0L;
                if(!raw.matches("[0-9]+"))throw new IOException("Invalid original reset cost");
                return Long.parseLong(raw);
            }}
        throw new IOException("Original rule 3 reset price missing");
    }
    private static ProtoWire r3(JSONObject activity)throws Exception {
        int current=floor(activity);
        ProtoWire result=new ProtoWire().set(1,current).text(3,"").set(4,activity.optInt("maxFloor",1))
            .set(5,activity.optInt("resetFloor",1)).set(6,Math.max(0,3-activity.optInt("resetCount")))
            .set(7,resetCost(activity)).set(8,activity.optInt("resetCount"));
        JSONObject wins=activity.getJSONObject("routeWins");
        // Original UI dereferences the metadata for LevelBuff. Present original,
        // catalog-backed cards; no unverified combat effect is fabricated.
        JSONArray buffs=bundled().getJSONArray("activityGameBuffs");int slot=0;
        for(long id:routesAt(current))result.add(2,new ProtoWire().set(1,id<FIRST+15?1:0).set(2,id)
            .set(3,buffs.getJSONObject(Math.floorMod((current-1)*3+slot++,buffs.length())).getLong("ID"))
            .set(4,wins.optInt(current+":"+id,0)).bytes());
        return result;
    }
    // ApOpen (field 7) is an opening notification: repeating it in every
    // instance reply recursively triggers another instance request in the client.
    private static ProtoWire extra(JSONObject activity)throws Exception{return new ProtoWire().set(103,r3(activity).bytes());}
    private static byte[] common(JSONObject activity)throws Exception{return new ProtoWire().text(1,"ok").set(2,extra(activity).bytes()).bytes();}
    static byte[] instance(JSONObject state,byte[] seed,long now)throws Exception{
        JSONObject activity=lab(state);ProtoWire value=ProtoWire.parse(seed);
        value.set(1,1).set(2,EVENT).set(3,activity.optBoolean("initClaimed")?1:0)
            .set(4,activity.optLong("dailyClaimDay",-1)==day(now)?1:0).set(5,activity.optLong("lastReset",0))
            .set(6,activity.optLong("earnedCurrency",0)).set(7,activity.optLong("totalCombat",0))
            .set(8,0).set(10,1).set(12,1).set(13,activity.optLong("consumedStamina",0))
            .set(100,extra(activity).bytes());
        value.clear(34).add(34,new ProtoWire().set(1,EVENT).set(2,activity.optBoolean("entered")?1:0).bytes());
        // Empty, present nested containers match the preserved instance shape.
        byte[] acc=value.data(9),mercenary=value.data(11);
        if(acc==null||acc.length==0)value.set(9,new byte[0]);
        if(mercenary==null||mercenary.length==0)value.set(11,new byte[0]);
        return value.bytes();
    }
    static boolean intercept(String path,Map<String,String> args)throws Exception{
        path=normalize(path);
        if(direct(path)||path.equals("/story/get")||path.equals("/shop/allShopSet")||path.equals("/shop/getSetData"))return true;
        if(path.equals("/story/buy"))return storyRow(arg(args,0,"storyid"))!=null;
        if(path.equals("/shop/buy"))return setRow(arg(args,0,"setid","shopsetid"))!=null;
        if(path.equals("/combat/mob/info"))return contains(stageArg(args));
        return false;
    }
    static Action respond(JSONObject state,JSONObject roleCatalog,String path,Map<String,String> args,
                          byte[] seed,byte[] storySeed,long now)throws Exception {
        path=normalize(path);if(!intercept(path,args))return null;
        if(path.equals("/ap/stamina/init/gain"))path="/ap/getInitStamina";
        if(path.equals("/ap/stamina/daily/gain"))path="/ap/getDailyStamina";
        String before=state.toString();JSONObject activity=lab(state);byte[] response;
        if(path.equals("/ap/instance/get")||path.equals("/ap/getInfo"))response=instance(state,seed,now);
        else if(path.equals("/ap/enter")||path.equals("/ap/instance/enter")){
            activity.put("entered",true);response=instance(state,new byte[0],now);
        }else if(path.equals("/ap/R3/getInfo")||path.equals("/ap/R3/getData")||
                 path.equals("/ap/r3/getInfo")||path.equals("/ap/r3/getData"))response=r3(activity).bytes();
        else if(path.equals("/ap/getMobs")||path.equals("/combat/mob/info"))
            response=Base64.decode(stage(stageArg(args)).getString("combatMobInfo"),0);
        else if(path.equals("/ap/getRoleInfo")){
            Map<String,String> party=new LinkedHashMap<String,String>(args);
            if(!party.containsKey("servantcardids")&&party.containsKey("servantids"))party.put("servantcardids",party.get("servantids"));
            if(!party.containsKey("servantcardids")&&party.containsKey("svcardids"))party.put("servantcardids",party.get("svcardids"));
            if(!party.containsKey("weaponids")&&party.containsKey("wpids"))party.put("weaponids",party.get("wpids"));
            if(!party.containsKey("fashioncardid")&&party.containsKey("fashionid"))party.put("fashioncardid",party.get("fashionid"));
            response=LocalEconomy.combat(state,party,seed,roleCatalog);
        }else if(path.equals("/ap/startBattle"))response=start(activity,args,now);
        else if(path.equals("/ap/win"))response=win(state,activity,args,now);
        else if(path.equals("/ap/lose")||path.equals("/ap/cancel")){
            activity.remove("activeBattle");response=common(activity);
        }else if(path.equals("/ap/reset"))response=reset(activity,args,now);
        // Win already settles the explicit test reward. Profit must not show
        // a second ungranted LootObject or fabricate the original lottery.
        else if(path.equals("/ap/getProfit"))response=new ProtoWire().set(2,extra(activity).bytes()).bytes();
        else if(path.equals("/ap/getRank")||path.equals("/ap/rank"))response=rank(state,activity,now);
        else if(path.equals("/ap/getStamina"))response=new ProtoWire().set(1,now).set(7,activity.getLong("stamina")).set(8,now).bytes();
        else if(path.equals("/ap/buyStamina"))throw new Rejected("UNRECOVERED_PAID_STAMINA_RULE");
        else if(path.toLowerCase(Locale.ROOT).contains("dailystamina")){
            if(activity.optLong("dailyClaimDay",-1)!=day(now)){
                JSONObject row=bundled().getJSONObject("event").getJSONObject("originalRow");
                long item=Long.parseLong(row.getString("everyday_stamina_item"));
                JSONObject itemRow=itemRow(item);long amount=itemRow.getLong("act_stamina")*row.getLong("everyday_stamina_item_num");
                activity.put("stamina",Math.addExact(activity.getLong("stamina"),amount)).put("dailyClaimDay",day(now));
            }
            response=common(activity);
        }else if(path.toLowerCase(Locale.ROOT).contains("initstamina")){
            // Initial 500 was issued once by profile creation; retries cannot duplicate it.
            activity.put("initClaimed",true);response=common(activity);
        }else if(path.equals("/story/get"))response=stories(activity,seed);
        else if(path.equals("/story/buy"))response=buyStory(state,activity,roleCatalog,args,storySeed==null?new byte[0]:storySeed);
        else if(path.equals("/shop/allShopSet")||path.equals("/shop/getSetData"))response=shopSets(activity,seed,now);
        else if(path.equals("/shop/buy"))response=buyShop(state,activity,roleCatalog,args,now);
        else throw new Rejected("UNIMPLEMENTED_ACTIVITY_ROUTE");
        project(state);return new Action(response,!before.equals(state.toString()));
    }
    private static byte[] start(JSONObject activity,Map<String,String> args,long now)throws Exception{
        if(activity.optBoolean("completed"))throw new Rejected("ACTIVITY_RUN_COMPLETE");
        int current=floor(activity);long id=stageArg(args);stage(id);
        if(arg(args,current,"floor")!=current)throw new Rejected("STALE_ACTIVITY_FLOOR");
        boolean route=false;for(long candidate:routesAt(current))if(candidate==id)route=true;
        if(!route)throw new Rejected("STAGE_NOT_ON_CURRENT_ROUTE");
        long cost=stage(id).getJSONObject("originalRow").getLong("instance_stamina_victory");
        if(activity.getLong("stamina")<cost)throw new Rejected("ACTIVITY_STAMINA_INSUFFICIENT");
        JSONObject active=activity.optJSONObject("activeBattle");
        if(active!=null&&active.optInt("floor")==current&&active.optLong("stage")==id)return common(activity);
        activity.put("activeBattle",new JSONObject().put("floor",current).put("stage",id).put("startedAt",now));
        return common(activity);
    }
    private static byte[] loot(JSONObject activity,long amount)throws Exception{
        // 150 is the known story unlock threshold, deliberately a local test reward.
        ProtoWire reward=new ProtoWire().set(1,3).set(2,CURRENCY).set(3,amount).set(4,amount);
        return new ProtoWire().add(1,reward.bytes()).set(2,extra(activity).bytes()).bytes();
    }
    private static byte[] win(JSONObject state,JSONObject activity,Map<String,String> args,long now)throws Exception{
        long id=stageArg(args);long requestedFloor=arg(args,floor(activity),"floor");
        JSONObject active=activity.optJSONObject("activeBattle"),previous=activity.optJSONObject("lastSettlement");
        if(active==null){
            if(previous!=null&&previous.optLong("stage")==id&&previous.optLong("floor")==requestedFloor)
                return Base64.decode(previous.getString("response"),0);
            throw new Rejected("ACTIVITY_BATTLE_NOT_STARTED");
        }
        if(active.getLong("stage")!=id||active.getLong("floor")!=requestedFloor||requestedFloor!=floor(activity))
            throw new Rejected("ACTIVITY_BATTLE_MISMATCH");
        long cost=stage(id).getJSONObject("originalRow").getLong("instance_stamina_victory");
        if(activity.getLong("stamina")<cost)throw new Rejected("ACTIVITY_STAMINA_INSUFFICIENT");
        long reward=storyPrice();activity.put("stamina",activity.getLong("stamina")-cost)
            .put("currency",Math.addExact(activity.getLong("currency"),reward))
            .put("earnedCurrency",Math.addExact(activity.getLong("earnedCurrency"),reward))
            .put("totalCombat",Math.addExact(activity.getLong("totalCombat"),1L))
            .put("consumedStamina",Math.addExact(activity.getLong("consumedStamina"),cost));
        JSONObject wins=activity.getJSONObject("routeWins");String key=requestedFloor+":"+id;
        wins.put(key,wins.optInt(key)+1);activity.remove("activeBattle");
        if(requestedFloor<FLOOR_LIMIT)activity.put("floor",requestedFloor+1).put("maxFloor",Math.max(activity.optInt("maxFloor"),requestedFloor+1));
        else activity.put("completed",true);
        byte[] response=loot(activity,reward);
        activity.put("lastSettlement",new JSONObject().put("stage",id).put("floor",requestedFloor)
            .put("at",now).put("response",Base64.encodeToString(response,Base64.NO_WRAP)));
        return response;
    }
    private static byte[] reset(JSONObject activity,Map<String,String> args,long now)throws Exception{
        long target=arg(args,1,"floor");
        if(target<1||target>Math.max(1,activity.optInt("maxFloor"))||target>FLOOR_LIMIT)throw new Rejected("INVALID_RESET_FLOOR");
        long last=activity.optLong("lastReset",0),cd=constant("ACTIVITY_GAMES_RESET_CD",30);
        if(last>0&&now-last<cd)throw new Rejected("ACTIVITY_RESET_COOLDOWN");
        int count=activity.optInt("resetCount");long cost=count<3?0:resetCost(activity);
        if(activity.getLong("currency")<cost)throw new Rejected("ACTIVITY_CURRENCY_INSUFFICIENT");
        activity.put("currency",activity.getLong("currency")-cost).put("floor",target).put("resetFloor",target)
            .put("resetCount",count+1).put("lastReset",now).put("completed",false).put("routeWins",new JSONObject());
        activity.remove("activeBattle");activity.remove("lastSettlement");return common(activity);
    }
    private static byte[] rank(JSONObject state,JSONObject activity,long now)throws Exception{
        ProtoWire role=new ProtoWire().set(1,state.getLong("legacyRoleId")).set(2,activity.getLong("totalCombat"))
            .text(3,state.optString("name","本地活动测试")).set(4,60).set(5,state.optInt("head",1)).set(6,state.optInt("headBox",1));
        ProtoWire rank=new ProtoWire().add(1,role.bytes()).set(2,activity.getLong("totalCombat")).set(3,1)
            .set(4,OPEN_END).set(5,2).set(6,1).set(9,activity.optInt("maxFloor",1)).set(10,1);
        return new ProtoWire().add(1,rank.bytes()).bytes();
    }
    private static JSONObject row(JSONArray rows,long id)throws Exception{
        for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);if(row.optLong("ID")==id)return row;}return null;
    }
    private static JSONObject storyRow(long id)throws Exception{return row(bundled().getJSONArray("stories"),id);}
    private static JSONObject itemRow(long id)throws Exception{
        JSONObject found=row(bundled().getJSONArray("items"),id);if(found==null)throw new IOException("Original event item missing");return found;
    }
    private static JSONObject setRow(long id)throws Exception{return row(bundled().getJSONObject("shops").getJSONArray("shopSets"),id);}
    private static byte[] stories(JSONObject activity,byte[] seed)throws Exception{
        ProtoWire value=ProtoWire.parse(seed);
        for(Iterator<ProtoWire.Field> it=value.fields.iterator();it.hasNext();){ProtoWire.Field f=it.next();
            if(f.number==1&&f.type==2&&ProtoWire.parse(f.data).number(1,0)==STORY_GROUP)it.remove();}
        ProtoWire group=new ProtoWire().set(100,1).set(101,1);
        JSONArray rows=bundled().getJSONArray("stories");JSONObject unlocked=activity.getJSONObject("storyUnlocked");boolean previous=true;
        for(int i=0;i<rows.length();i++){
            JSONObject row=rows.getJSONObject(i);long id=row.getLong("ID");boolean done=unlocked.optBoolean(Long.toString(id));
            group.add(1,new ProtoWire().set(100,id).set(101,done?1:0).set(102,!done&&previous?1:0).bytes());previous=done;
        }
        value.add(1,new ProtoWire().set(1,STORY_GROUP).set(2,group.bytes()).bytes());
        value.clear(101).add(101,STORY_GROUP).set(102,STORY_GROUP).set(100,1);return value.bytes();
    }
    private static byte[] buyStory(JSONObject state,JSONObject activity,JSONObject roleCatalog,Map<String,String> args,byte[] seed)throws Exception{
        long id=arg(args,0,"storyid");JSONObject selected=storyRow(id);if(selected==null)throw new Rejected("UNKNOWN_EVENT_STORY");
        JSONObject unlocked=activity.getJSONObject("storyUnlocked");String key=Long.toString(id);
        // Original BuyStory parses LootResult, whose field 1 is LootObject.
        ProtoWire result=new ProtoWire();
        if(!unlocked.optBoolean(key)){
            JSONArray rows=bundled().getJSONArray("stories");
            for(int i=0;i<rows.length();i++){long candidate=rows.getJSONObject(i).getLong("ID");
                if(candidate==id)break;if(!unlocked.optBoolean(Long.toString(candidate)))throw new Rejected("EVENT_STORY_PREREQUISITE");}
            long cost=selected.getLong("unlock_value");if(activity.getLong("currency")<cost)throw new Rejected("ACTIVITY_CURRENCY_INSUFFICIENT");
            activity.put("currency",activity.getLong("currency")-cost);unlocked.put(key,true);
            int type=selected.optInt("bonus_type");long amount=selected.optLong("bonus_value");
            LocalEconomy.grantItemReward(state,roleCatalog,new JSONObject().put("type",type)
                .put("id",selected.optLong("bonus_id",0)).put("value",amount).put("count",0),1);
            result.add(1,new ProtoWire().set(1,type).set(2,selected.optLong("bonus_id",0))
                .set(3,amount).set(4,1).bytes());
            activity.put("lastStoryBonus",new JSONObject().put("story",id).put("originalType",type)
                .put("originalValue",amount).put("applied",true));
        }
        return result.set(2,extra(activity).set(5,stories(activity,seed)).set(111,STORY_GROUP).bytes()).bytes();
    }
    private static long bought(JSONObject activity,long set,long shop,long goods,long now)throws Exception{
        JSONObject def=setRow(set);long bucket=def.optInt("period")>0?day(now):0;
        return activity.getJSONObject("shopPurchases").optLong(set+":"+shop+":"+goods+":"+bucket);
    }
    private static byte[] shopSets(JSONObject activity,byte[] seed,long now)throws Exception{
        ProtoWire value=ProtoWire.parse(seed);JSONArray sets=bundled().getJSONObject("shops").getJSONArray("shopSets");
        for(Iterator<ProtoWire.Field> it=value.fields.iterator();it.hasNext();){ProtoWire.Field f=it.next();
            if(f.number==1&&f.type==2&&setRow(ProtoWire.parse(f.data).number(1,0))!=null)it.remove();}
        JSONArray shops=bundled().getJSONObject("shops").getJSONArray("shops");
        for(int i=0;i<sets.length();i++){
            JSONObject set=sets.getJSONObject(i);long setId=set.getLong("ID");
            // AllShopSet/GetSetData parse Shopmod.AllSets -> SetInfo, not
            // Shopmod.ShopSet (the persisted server record with similar names).
            boolean daily=set.optInt("period")>0;
            long timeLeft=daily?(day(now)+1)*86400L-28800L-now:0;
            ProtoWire wire=new ProtoWire().set(1,setId).set(2,timeLeft).set(3,daily?1:0)
                .set(4,0).set(6,OPEN_START).set(7,OPEN_END).set(8,0).set(9,1);
            for(int j=1;j<=50;j++){
                long shopId=set.optLong("shop"+j);if(shopId==0)continue;JSONObject shop=row(shops,shopId);
                if(shop==null)throw new IOException("Historical activity shop missing");
                long totalLimit=shop.optLong("max_total_num");
                // The original client uses -1 for no shelf-wide purchase limit.
                ProtoWire shelf=new ProtoWire().set(1,shopId).set(3,1).set(4,totalLimit<=0?-1:totalLimit);
                for(int k=1;k<=60;k++){
                    long goodId=shop.optLong("goods"+k);if(goodId==0)continue;
                    long limit=shop.optLong("num"+k),remaining=limit==0?0:Math.max(0,limit-bought(activity,setId,shopId,goodId,now));
                    shelf.add(2,new ProtoWire().set(1,goodId).set(2,shop.getLong("price"+k)).set(3,remaining).set(4,0).set(5,0).bytes());
                }
                wire.add(5,shelf.bytes());
            }
            value.add(1,wire.bytes());
        }
        return value.set(2,0).bytes();
    }
    private static byte[] buyShop(JSONObject state,JSONObject activity,JSONObject roleCatalog,Map<String,String> args,long now)throws Exception{
        long set=arg(args,0,"setid","shopsetid"),shopId=arg(args,0,"shopid"),goods=arg(args,0,"goodsid"),count=arg(args,1,"num","count");
        if(count<1||count>999)throw new Rejected("INVALID_SHOP_COUNT");JSONObject setDef=setRow(set);
        if(setDef==null)throw new Rejected("UNKNOWN_EVENT_SHOP");boolean member=false;
        for(int i=1;i<=50;i++)if(setDef.optLong("shop"+i)==shopId)member=true;
        if(!member)throw new Rejected("EVENT_SHOP_SET_MISMATCH");
        JSONObject shop=row(bundled().getJSONObject("shops").getJSONArray("shops"),shopId);int slot=0;
        for(int i=1;i<=60;i++)if(shop.optLong("goods"+i)==goods)slot=i;
        if(slot==0)throw new Rejected("EVENT_GOOD_NOT_ON_SHELF");
        if(shop.optInt("price_type")!=90||shop.optLong("currency_id")!=CURRENCY)throw new Rejected("UNRECOVERED_EVENT_PAYMENT_RULE");
        JSONObject good=row(bundled().getJSONObject("shops").getJSONArray("goods"),goods);
        if(good==null)throw new Rejected("UNKNOWN_EVENT_GOOD");
        String token=args.get("idempotency"),fingerprint=set+":"+shopId+":"+goods+":"+count;
        JSONObject transactions=activity.getJSONObject("transactions"),prior=token==null?null:transactions.optJSONObject(token);
        if(token!=null&&!token.matches("[A-Za-z0-9._:-]{1,128}"))throw new Rejected("INVALID_SHOP_TRANSACTION");
        if(prior!=null){if(!fingerprint.equals(prior.getString("fingerprint")))throw new Rejected("SHOP_TRANSACTION_REUSED");return Base64.decode(prior.getString("response"),0);}
        long old=bought(activity,set,shopId,goods,now),limit=shop.optLong("num"+slot),price=Math.multiplyExact(shop.getLong("price"+slot),count);
        if(limit>0&&old+count>limit)throw new Rejected("EVENT_SHOP_LIMIT");
        if(activity.getLong("currency")<price)throw new Rejected("ACTIVITY_CURRENCY_INSUFFICIENT");
        int type=good.getInt("type");long item=good.optLong("goods_id"),amount=Math.multiplyExact(goodsAmount(good),count);
        if(type==3){
            JSONObject bag=state.getJSONObject("items");String key=Long.toString(item);
            if(!roleCatalog.getJSONObject("items").has(key))throw new Rejected("UNRECOVERED_EVENT_REWARD_ITEM");
            long updated=Math.addExact(bag.optLong(key),amount);if(updated>LocalEconomy.stackCap(roleCatalog,key))throw new Rejected("EVENT_ITEM_STACK_LIMIT");bag.put(key,updated);
        }else if(type==2){
            JSONObject bag=state.getJSONObject("equips");String key=Long.toString(item);
            if(!roleCatalog.getJSONObject("equips").has(key))throw new Rejected("UNRECOVERED_EVENT_REWARD_EQUIP");bag.put(key,Math.addExact(bag.optLong(key),amount));
        }else if(type==13)state.put("gold",Math.addExact(state.optLong("gold"),amount));
        else throw new Rejected("UNRECOVERED_EVENT_REWARD_TYPE");
        activity.put("currency",activity.getLong("currency")-price);
        long bucket=setDef.optInt("period")>0?day(now):0;
        activity.getJSONObject("shopPurchases").put(set+":"+shopId+":"+goods+":"+bucket,old+count);
        // The original BuyAction callback recognizes this exact result token.
        byte[] response=new ProtoWire().text(1,"Buy Success").set(4,extra(activity).bytes()).add(5,
            new ProtoWire().set(1,type).set(2,item).set(3,amount).set(4,type==2||type==3?amount:count).bytes()).bytes();
        if(token!=null)transactions.put(token,new JSONObject().put("fingerprint",fingerprint).put("response",Base64.encodeToString(response,Base64.NO_WRAP)));
        return response;
    }
    private static long goodsAmount(JSONObject good)throws Exception{
        String configured=good.optString("goods_value","").trim();
        if(!configured.isEmpty())return Long.parseLong(configured);
        // Some preserved Goods rows omit the amount, while their original
        // localized name explicitly says e.g. "玉钢 × 2". Use that evidence
        // rather than silently issuing a single item for a multi-item pack.
        JSONArray dictionary=bundled().getJSONArray("dictionary");
        String nameId=good.optString("name");
        for(int i=0;i<dictionary.length();i++){
            JSONObject row=dictionary.getJSONObject(i);
            if(!nameId.equals(row.optString("ID")))continue;
            java.util.regex.Matcher packed=java.util.regex.Pattern.compile("[×xX]\\s*(\\d+)\\s*$")
                .matcher(row.optString("content_chinese"));
            if(packed.find())return Long.parseLong(packed.group(1));
        }
        return 1L;
    }
}
