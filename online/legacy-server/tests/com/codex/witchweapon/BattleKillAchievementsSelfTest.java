package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Optional native killed telemetry, real settlement replay and original rewards.
 * The caller supplies an empty disposable directory; no player save is opened.
 */
public final class BattleKillAchievementsSelfTest {
    private static final String KILLS="331010240101=2=3|331010342201=1=2";
    private static void check(boolean good,String message){if(!good)throw new AssertionError(message);}
    private static Map<String,String> form(String... pairs){
        Map<String,String> out=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)out.put(pairs[i],pairs[i+1]);
        return out;
    }
    private static JSONObject account()throws Exception{
        return new JSONObject().put("version",1).put("roleCreated",true).put("legacyRoleId",7)
            .put("starterProfile",1).put("namePending",false).put("stamina",200)
            .put("gold",1000).put("rmb",0).put("exp",0);
    }
    private static JSONObject read(File file)throws Exception{
        return new JSONObject(new String(Files.readAllBytes(file.toPath()),StandardCharsets.UTF_8));
    }
    private static JSONObject saved(File folder)throws Exception{
        return read(new File(folder,"offline_save_v1.json"));
    }
    private static LocalSave prepare(File folder)throws Exception{
        check(folder.mkdir(),"Fresh isolated account directory required");
        Files.write(new File(folder,"offline_save_v1.json").toPath(),
            (account().toString()+"\n").getBytes(StandardCharsets.UTF_8));
        return new LocalSave(folder);
    }
    private static byte[] call(LocalSave save,String path,Map<String,String> args,
                               byte[] seed,JSONObject catalog,StageCatalog stages)throws Exception{
        return save.respond(path,args,seed,catalog,null,stages);
    }
    private static ProtoWire job(byte[] list,long id)throws Exception{
        for(ProtoWire.Field field:ProtoWire.parse(list).fields)if(field.number==1&&field.type==2){
            ProtoWire row=ProtoWire.parse(field.data);
            if(row.number(1,0)==id)return row;
        }
        throw new AssertionError("Missing original achievement "+id);
    }
    private static void parserChecks()throws Exception{
        JSONObject state=account();
        ProgressionTasks.recordBattleKills(state,form("killed",KILLS));
        check(state.getLong("enemyKillsTotal")==5,"Count must use the third component, not rank or rows");
        ProgressionTasks.recordBattleKills(state,form("killed","331010240101=1=2|331010240101=3=4"));
        check(state.getLong("enemyKillsTotal")==11,"Different native power ranks are separate dictionary keys");
        JSONObject summoned=account();
        ProgressionTasks.recordBattleKills(summoned,form("killed","332010111301=1=2"));
        check(summoned.getLong("enemyKillsTotal")==2,"Original namespace-332 summoned monster deaths were discarded");
        String[] invalid={"","0","331010240101=1", "331010240101=1=0",
            "331010240101=1=-1","331010240101=4=1","331010240101=1=01",
            "331010240101=1=10001","331010240101=1=9223372036854775807",
            "9223372036854775808=1=1","999010240101=1=1","331010240101=1=1|",
            "331010240101=1=1|broken","331010240101=1=1|331010240101=1=2",
            "331010240101=1=1;331010342201=1=1","331010240101=1=1 ",
            "331010240101=1=6000|331010342201=1=6000"};
        for(String value:invalid){
            ProgressionTasks.recordBattleKills(state,form("killed",value));
            check(state.getLong("enemyKillsTotal")==11,"Invalid telemetry counted: "+value);
        }
        ProgressionTasks.recordBattleKills(state,form());
        check(state.getLong("enemyKillsTotal")==11,"Missing telemetry changed progress");
        StringBuilder rows=new StringBuilder();
        for(int i=0;i<257;i++){
            if(i>0)rows.append('|');rows.append(331000000000L+i).append("=1=1");
        }
        ProgressionTasks.recordBattleKills(state,form("killed",rows.toString()));
        ProgressionTasks.recordBattleKills(state,form("killed",new String(new char[8193]).replace('\0','1')));
        check(state.getLong("enemyKillsTotal")==11,"Bounded optional telemetry accepted excessive rows or bytes");
        state.put("enemyKillsTotal",Long.MAX_VALUE-1);
        ProgressionTasks.recordBattleKills(state,form("killed",KILLS));
        check(state.getLong("enemyKillsTotal")==Long.MAX_VALUE,"Lifetime counter overflow interrupted settlement");
    }
    private static void rewardChecks(JSONObject catalog)throws Exception{
        ProgressionTasks tasks=ProgressionTasks.bundled();JSONObject state=account();
        state.put("wins",100000).put("mainlineWins",100000).put("lastBattle",new JSONObject().put("killed",KILLS));
        byte[] list=tasks.achievementList(state,catalog,new byte[0]);
        check(!state.has("enemyKillsTotal")&&job(list,501100001L).number(2,0)==-1,
            "Historic wins and the last request must not fabricate lifetime kills");
        state.put("enemyKillsTotal",4999);
        ProgressionTasks.recordBattleKills(state,form("killed","331010240101=1=1"));
        list=tasks.achievementList(state,catalog,new byte[0]);
        check(job(list,501100001L).number(2,-1)==0&&job(list,501100002L).number(2,0)==-1,
            "Original 5000-kill threshold or predecessor gating is wrong");
        Map<String,String> first=form("roleid","7","jobid","501100001","type","100");
        byte[] reward=tasks.claimAchievement(state,catalog,first);
        check(state.getLong("rmb")==20&&state.getLong("gold")==21000&&
            Arrays.equals(reward,tasks.claimAchievement(state,catalog,first))&&state.getLong("rmb")==20,
            "Original first kill reward or exactly-once claim is wrong");
        state.put("enemyKillsTotal",49999);
        ProgressionTasks.recordBattleKills(state,form("killed","331010240101=1=1"));
        check(job(tasks.achievementList(state,catalog,new byte[0]),501100002L).number(2,-1)==0,
            "Original 50000-kill achievement did not become claimable");
        tasks.claimAchievement(state,catalog,form("roleid","7","jobid","501100002","type","100"));
        check(state.getLong("rmb")==70&&state.getLong("gold")==71000,"Original second kill reward is wrong");
        check(job(tasks.achievementList(state,catalog,new byte[0]),501072001L).number(2,0)==-1&&
            job(tasks.achievementList(state,catalog,new byte[0]),501073001L).number(2,0)==-1,
            "Support achievements acquired invented counters");
    }
    private static void dailyChecks(JSONObject catalog)throws Exception{
        DailyBattle daily=DailyBattle.bundled();long now=1800000000L,stage=3120002001L;
        JSONObject active=daily.begin(account(),stage,form("idempotency","kill-daily-1"),now,true);
        Map<String,String> won=form("instanceid",Long.toString(stage),"pass","1","stars","3","killed",KILLS);
        DailyBattle.Settlement first=daily.settle(active,catalog,won,now+1);
        check(first.state.getLong("enemyKillsTotal")==5,"Daily victory did not count its real kill telemetry");
        Map<String,String> changed=form("instanceid",Long.toString(stage),"pass","1","stars","3",
            "killed","331010240101=1=10000");
        DailyBattle.Settlement repeat=daily.settle(first.state,catalog,changed,now+2);
        check(repeat.state==first.state&&Arrays.equals(first.response,repeat.response)&&
            repeat.state.getLong("enemyKillsTotal")==5,"Daily replay counted kills twice");
        DailyBattle.Settlement sweep=daily.sweep(first.state,catalog,form("chapid","3020002",
            "instanceid",Long.toString(stage),"count","1","idempotency","kill-sweep","killed",KILLS),now+3,true);
        check(sweep.state.getLong("enemyKillsTotal")==5,"Daily sweep fabricated kill progress");
        // The first battle plus sweep consume the original two daily attempts.
        long nextDay=now+86400;
        JSONObject second=daily.begin(sweep.state,stage,form("idempotency","kill-daily-2"),nextDay,true);
        DailyBattle.Settlement malformed=daily.settle(second,catalog,form("instanceid",Long.toString(stage),
            "pass","0","stars","0","killed","331010240101=1=99999999999999999999999"),nextDay+1);
        check(!malformed.state.optBoolean("active",true)&&malformed.state.getLong("enemyKillsTotal")==5,
            "Malformed optional telemetry broke daily settlement");
    }
    private static void furnaceChecks(JSONObject catalog)throws Exception{
        WeaponFurnace furnace=WeaponFurnace.bundled();long stage=3120007001L,now=1800000000L;
        JSONObject active=account().put("active",true).put("activeStage",stage).put("startKey","kill-furnace");
        furnace.recordStart(active,stage);
        Map<String,String> lost=form("instanceid",Long.toString(stage),"pass","0","stars","0","killed",KILLS);
        WeaponFurnace.Settlement first=furnace.settle(active,catalog,lost,now);
        check(first.next.getLong("enemyKillsTotal")==5,"Accepted furnace battle omitted actual enemy deaths");
        Map<String,String> furnaceReplay=new HashMap<String,String>(lost);
        furnaceReplay.put("killed","331010240101=1=10000");
        WeaponFurnace.Settlement repeat=furnace.settle(first.next,catalog,furnaceReplay,now+1);
        check(repeat.next==null&&Arrays.equals(first.response,repeat.response)&&
            first.next.getLong("enemyKillsTotal")==5,"Furnace replay counted kills twice");
        JSONObject second=new JSONObject(first.next.toString()).put("active",true).put("startKey","kill-furnace-2");
        furnace.recordStart(second,stage);
        WeaponFurnace.Settlement malformed=furnace.settle(second,catalog,form("instanceid",Long.toString(stage),
            "pass","0","stars","0","killed","bad"),now+2);
        check(!malformed.next.optBoolean("active",true)&&malformed.next.getLong("enemyKillsTotal")==5,
            "Malformed optional telemetry broke furnace settlement");
    }
    private static void routeChecks(File root,JSONObject fixtures,StageCatalog stages)throws Exception{
        JSONObject catalog=fixtures.getJSONObject("_catalog");File main=new File(root,"main");
        LocalSave save=prepare(main);String stage="3110001002";
        call(save,"/level/startBattle",form("instanceid",stage,"idempotency","kill-main"),
            new byte[0],catalog,stages);
        Map<String,String> won=form("instanceid",stage,"pass","1","stars","3","killed",KILLS);
        byte[] response=call(save,"/level/pushMainLineProgress",won,new byte[0],catalog,stages);
        check(saved(main).getLong("enemyKillsTotal")==5,"Mainline transaction did not persist real kills");
        LocalSave resumed=new LocalSave(main);
        Map<String,String> mainReplay=new HashMap<String,String>(won);
        mainReplay.put("killed","331010240101=1=10000");
        check(Arrays.equals(response,call(resumed,"/level/pushMainLineProgress",mainReplay,new byte[0],catalog,stages))&&
            saved(main).getLong("enemyKillsTotal")==5,"Mainline replay after reload counted kills twice");
        call(resumed,"/level/startBattle",form("instanceid",stage,"idempotency","kill-main-2"),
            new byte[0],catalog,stages);
        call(resumed,"/level/pushMainLineProgress",form("instanceid",stage,"pass","0","stars","0",
            "killed","331010240101=1=10001"),new byte[0],catalog,stages);
        check(!saved(main).optBoolean("active",true)&&saved(main).getLong("enemyKillsTotal")==5,
            "Malformed optional telemetry broke mainline settlement");
        call(resumed,"/level/sweep",form("chapid","3010001","instanceid",stage,"count","1",
            "idempotency","kill-main-sweep","killed",KILLS),new byte[0],catalog,stages);
        check(saved(main).getLong("enemyKillsTotal")==5,"Mainline sweep fabricated kill progress");
        byte[] role=Base64.decode(fixtures.getJSONObject("/combat/role/info").getString("base64"),Base64.DEFAULT);
        File maze=new File(root,"maze");LocalSave mazeSave=prepare(maze);
        call(mazeSave,"/csc/info",form(),role,catalog,stages);
        long mazeStage=BarrierLabyrinth.stageForRound(1);
        ProtoWire prepared=ProtoWire.parse(call(mazeSave,"/csc/role",form("instid",Long.toString(mazeStage)),
            role,catalog,stages));
        Map<String,String> mazeWin=form("levelid",Long.toString(mazeStage),"state","1",
            "hp",Long.toString(prepared.number(16,1)),"servantcardids","","energys","","data","","killed",KILLS);
        byte[] mazeResponse=call(mazeSave,"/csc/normal/commit",mazeWin,role,catalog,stages);
        check(saved(maze).getLong("enemyKillsTotal")==5,"CSC transaction did not persist native killed telemetry");
        LocalSave mazeResumed=new LocalSave(maze);
        Map<String,String> mazeReplay=new HashMap<String,String>(mazeWin);
        mazeReplay.put("killed","331010240101=1=10000");
        check(Arrays.equals(mazeResponse,call(mazeResumed,"/csc/normal/commit",mazeReplay,role,catalog,stages))&&
            saved(maze).getLong("enemyKillsTotal")==5,"CSC replay after reload counted kills twice");
        long nextStage=BarrierLabyrinth.stageForRound(2);
        call(mazeResumed,"/csc/role",form("instid",Long.toString(nextStage)),role,catalog,stages);
        call(mazeResumed,"/csc/normal/commit",form("levelid",Long.toString(nextStage),"state","0","hp","0",
            "servantcardids","","energys","","data","","killed","bad"),role,catalog,stages);
        check(saved(maze).optBoolean("mazeRoundSettled",false)&&saved(maze).getLong("enemyKillsTotal")==5,
            "Malformed optional telemetry broke CSC settlement");
    }
    public static void main(String[] args)throws Exception{
        if(args.length!=3)throw new IllegalArgumentException("empty-test-dir responses.json stage_catalog.json");
        File root=new File(args[0]);
        check(root.isDirectory()&&root.list()!=null&&root.list().length==0,"Empty isolated test directory required");
        JSONObject fixtures=read(new File(args[1]));JSONObject catalog=fixtures.getJSONObject("_catalog");
        StageCatalog stages=new StageCatalog(read(new File(args[2])));
        parserChecks();rewardChecks(catalog);dailyChecks(catalog);furnaceChecks(catalog);
        routeChecks(root,fixtures,stages);
        System.out.println("BATTLE_KILL_ACHIEVEMENTS_SELF_TEST_OK");
    }
}
