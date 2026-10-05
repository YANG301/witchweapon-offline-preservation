package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.util.Map;

/**
 * Beginner encounters derived from the preserved Instance, InstanceMobList
 * and Mob tables. The original server's enemy waves, coordinates and combat
 * statistics were not in the APK; those parts are intentionally local balance.
 */
final class TutorialBattleFixtures {
    private static final long BASESTATION_STAGE = 3150001001L;
    private static final long SMELTER_STAGE = 3150001004L;
    private static final long OVERBRIDGE_STAGE = 3150001005L;
    // Original Instance.instance_restrict and Challenge.asset rows. These
    // parties are battle-only and must never enter ownedServants.
    static final long FIRST_SHOW_CHALLENGE = 400L;
    static final long[] FIRST_SHOW_SERVANTS = {
        10011901L,10010301L,10012701L,10010101L
    };
    static final long[] FIRST_SHOW_WEAPONS = {
        1701190101L,1701030101L,1701270101L,1701010101L
    };
    static final class ChallengeRole {
        final long stage, challenge;
        final int roleLevel, servantLevel, rank, star, weaponLevel;
        final long[] servants, weapons;
        ChallengeRole(long stage,long challenge,int roleLevel,int servantLevel,
                int rank,int star,int weaponLevel,long[] servants,long[] weapons){
            this.stage=stage;this.challenge=challenge;this.roleLevel=roleLevel;
            this.servantLevel=servantLevel;this.rank=rank;this.star=star;
            this.weaponLevel=weaponLevel;this.servants=servants;this.weapons=weapons;
        }
    }
    private static final ChallengeRole[] GUIDE_ROLES = {
        new ChallengeRole(BASESTATION_STAGE,100,30,30,5,1,30,
            new long[]{10012701L,10011701L,10010101L,10011901L},
            new long[]{1701270101L,1701170101L,1701010101L,1701190101L}),
        new ChallengeRole(SMELTER_STAGE,FIRST_SHOW_CHALLENGE,30,30,5,1,30,
            FIRST_SHOW_SERVANTS,FIRST_SHOW_WEAPONS),
        new ChallengeRole(OVERBRIDGE_STAGE,401,1,1,1,1,1,
            new long[]{10010601L,10010301L},
            new long[]{1701060102L,1701030101L}),
        new ChallengeRole(3150001006L,402,1,1,1,1,1,
            new long[]{10010601L,10010301L,10011801L},
            new long[]{1701060102L,1701030101L,1701180101L})
    };
    static ChallengeRole activeGuideRole(JSONObject state,Map<String,String> args) {
        if(!state.optBoolean("active",false))return null;
        long stage=state.optLong("activeStage",0);
        long challenge=LocalEconomy.number(args.get("challengeid"),-1);
        for(ChallengeRole role:GUIDE_ROLES)
            if(role.stage==stage&&role.challenge==challenge)return role;
        return null;
    }
    static ChallengeRole activeBasestationRole(JSONObject state) {
        if(!firstShowBasestation(state))return null;
        return GUIDE_ROLES[0];
    }
    static boolean firstShowChallenge(JSONObject state,Map<String,String> args) {
        // The original ARM64 constructor discards its instanceID parameter.
        // Its rid form field comes from the current role, not the stage, so
        // the server must use the active encounter it recorded itself.
        return state.optBoolean("active",false) &&
            state.optLong("activeStage",0)==SMELTER_STAGE &&
            LocalEconomy.number(args.get("challengeid"),-1)==FIRST_SHOW_CHALLENGE;
    }
    static boolean firstShowBasestation(JSONObject state) {
        return state.optBoolean("active",false) &&
            state.optLong("activeStage",0)==BASESTATION_STAGE;
    }
    // Original MapNode.brithPoint=(0,0,0). These nodes are on the connected
    // graph0 route through the station. Original server spawn coordinates are
    // missing; they are chosen only to make lesson00001's three-zone route
    // traversable. Order follows the five InstanceMobList row entries, plus
    // mob 434 required by lesson00001's CreateMobTap("434 #4") target.
    private static final double[][] BASESTATION_SPAWNS = {
        {22.936,-25.536}, {9.861,-11.385}, {24.116,-26.617},
        {12.220,-13.547}, {2.685,-2.639}, {11.041,-12.466}
    };
    // Local restoration: the original guide_0-0 server wave JSON is absent.
    // lesson01001 waits for combat-field events 1102 (zone 0, wave 1) and
    // 1201 (zone 1, wave 0). The first pocket is on graph1 near the original
    // birth point; the last two placements are on graph0 beyond its north
    // entrance. These positions are selected from the original map nav data,
    // not claimed to reproduce the lost server's exact timing or layout.
    private static final double[][] SMELTER_SPAWNS = {
        {-0.698, -15.975}, {1.24, -5.5}, {4.24, -5.5},
        {1.49, -7.0}, {0.885, -14.358}
    };
    // Local restoration: the original server waves are unavailable. These
    // graph0 nodes on map_1000_overbridge are walkable and connected to the
    // preserved MapNode.brithPoint (2.74, 0.17, -5.5). The former first two
    // points at z=-1.5 were on unwalkable nodes, one inside a wall collider.
    private static final double[][] OVERBRIDGE_SPAWNS = {
        {4.27, -5.28}, {3.65, -7.60}, {5.12, -6.75},
        {5.74, -4.43}, {6.59, -5.90}
    };
    private static final class Enemy {
        final long id;
        final int rank, level;
        final String model;
        Enemy(long id, int rank, int level, String model) {
            this.id=id;this.rank=rank;this.level=level;this.model=model;
        }
    }
    private static final class Stage {
        final long id;
        final String scene;
        final int objective, sourceSeconds;
        final Enemy[] enemies;
        Stage(long id,String scene,int objective,int sourceSeconds,Enemy... enemies){
            this.id=id;this.scene=scene;this.objective=objective;
            this.sourceSeconds=sourceSeconds;this.enemies=enemies;
        }
    }
    private static final Stage[] STAGES = {
        // 3150001001: original one-off guide_1, InstanceMobList mapID 1020.
        new Stage(BASESTATION_STAGE,"map_1020_basestation",0,0,
            new Enemy(331010343201L,3,24,"mob_432"),
            new Enemy(331010344303L,1,28,"mob_443"),
            new Enemy(331010240801L,1,26,"mob_408"),
            new Enemy(331010344401L,1,24,"mob_444"),
            new Enemy(331010343701L,1,24,"mob_437"),
            // Guide-only target; absent from the five source mob slots.
            new Enemy(332010343402L,1,24,"mob_434")),
        // 3150001004: InstanceMobList mapID 1028; source time=0.
        new Stage(3150001004L,"map_1028_smelter",0,0,
            new Enemy(331010110201L,2,25,"mob_102"),
            new Enemy(331010344303L,1,28,"mob_443"),
            new Enemy(331010344401L,1,24,"mob_444"),
            new Enemy(332010343402L,1,22,"mob_434"),
            new Enemy(331010240801L,1,22,"mob_408")),
        // 3150001005: InstanceMobList mapID 1000.
        new Stage(3150001005L,"map_1000_overbridge",0,300,
            new Enemy(331010240401L,1,1,"mob_404"),
            new Enemy(331010342209L,1,1,"mob_422"),
            new Enemy(331010342210L,1,1,"mob_422"),
            new Enemy(331010342211L,1,1,"mob_422"),
            new Enemy(331010240405L,1,1,"mob_404")),
        // 3150001006: InstanceMobList mapID 1013.
        new Stage(3150001006L,"map_1013_groofbroken",6,300,
            new Enemy(331010111201L,2,1,"mob_112"),
            new Enemy(332010343402L,1,3,"mob_434"))
    };
    static boolean handles(long id) {
        for(Stage stage:STAGES)if(stage.id==id)return true;
        return false;
    }
    static boolean allCleared(JSONObject state) {
        // Existing saves finished the previous local 1004 reconstruction.
        // New accounts use the original one-off basestation 1001 instead.
        return (state.optInt("tutorialWins_"+BASESTATION_STAGE,0)>0 ||
                state.optInt("tutorialWins_"+SMELTER_STAGE,0)>0) &&
            state.optInt("tutorialWins_"+OVERBRIDGE_STAGE,0)>0 &&
            state.optInt("tutorialWins_3150001006",0)>0;
    }
    static void install(JSONObject responses) throws Exception {
        JSONObject baseInfo=responses.optJSONObject("/combat/mob/info");
        JSONObject baseJson=responses.optJSONObject("/combat/mob/json");
        if(baseInfo==null || baseJson==null)
            throw new IOException("Missing preserved combat fixtures");
        ProtoWire base=ProtoWire.parse(Base64.decode(baseInfo.getString("base64"),Base64.DEFAULT));
        ProtoWire[] mobTemplates=new ProtoWire[2],typeTemplates=new ProtoWire[2];
        for(ProtoWire.Field field:base.fields){
            if(field.type!=2)continue;
            if(field.number==5 && mobTemplates[0]==null)mobTemplates[0]=ProtoWire.parse(field.data);
            else if(field.number==5 && mobTemplates[1]==null)mobTemplates[1]=ProtoWire.parse(field.data);
            else if(field.number==6 && typeTemplates[0]==null)typeTemplates[0]=ProtoWire.parse(field.data);
            else if(field.number==6 && typeTemplates[1]==null)typeTemplates[1]=ProtoWire.parse(field.data);
        }
        if(mobTemplates[0]==null || mobTemplates[1]==null ||
                typeTemplates[0]==null || typeTemplates[1]==null)
            throw new IOException("Incomplete preserved combat enemy templates");
        for(Stage stage:STAGES){
            ProtoWire basket=new ProtoWire();
            for(ProtoWire.Field field:base.fields)
                if(field.number!=5 && field.number!=6){
                    ProtoWire.Field copy=new ProtoWire.Field(field.number,field.type);
                    copy.value=field.value;
                    copy.data=field.data==null?null:field.data.clone();
                    basket.fields.add(copy);
                }
            JSONArray monsters=new JSONArray();
            int minimum=Integer.MAX_VALUE,maximum=0;
            for(int index=0;index<stage.enemies.length;index++){
                Enemy enemy=stage.enemies[index];
                minimum=Math.min(minimum,enemy.level);maximum=Math.max(maximum,enemy.level);
                // Preserve the original ID, appearance and configured level.
                // HP/attack, the behavior tree and spawn position are local
                // stand-ins because the original server wave data is absent.
                ProtoWire mob=ProtoWire.parse(mobTemplates[enemy.rank>=2?0:1].bytes());
                mob.set(3,enemy.level).set(4,enemy.rank).set(6,enemy.id)
                    .text(9,enemy.model).set(26,enemy.id).set(27,enemy.id)
                    .set(28,enemy.id).set(30,enemy.rank==2?1200:800)
                    .set(31,20).set(32,20);
                ProtoWire type=ProtoWire.parse(typeTemplates[enemy.rank>=2?0:1].bytes());
                type.set(1,enemy.id);
                basket.add(5,mob.bytes()).add(6,type.bytes());
                JSONObject monster=new JSONObject();
                monster.put("name","Enemy_"+(index+1));
                monster.put("opName",enemy.model);
                monster.put("givenName","");
                monster.put("statID",enemy.id+"-"+enemy.rank+"-"+enemy.level);
                monster.put("appearType",0);
                double x=2.74+index*2,z=-1.5;
                if(stage.id==BASESTATION_STAGE){
                    x=BASESTATION_SPAWNS[index][0];z=BASESTATION_SPAWNS[index][1];
                }else if(stage.id==SMELTER_STAGE){
                    x=SMELTER_SPAWNS[index][0];z=SMELTER_SPAWNS[index][1];
                }else if(stage.id==OVERBRIDGE_STAGE){
                    x=OVERBRIDGE_SPAWNS[index][0];z=OVERBRIDGE_SPAWNS[index][1];
                }
                monster.put("PRS",new JSONArray().put(x).put(z).put(180).put(1));
                monster.put("groupID",101);
                monster.put("ai_config",new JSONObject().put("taunt_list_index",0)
                    .put("can_be_taunt",true).put("follow_target",""));
                monster.put("tag","");
                monsters.put(monster);
            }
            JSONObject level=new JSONObject(baseJson.getString("body"));
            JSONObject quest=level.getJSONObject("QuestInfo");
            quest.put("LevelObjectiveType",stage.objective);
            quest.put("sec",stage.sourceSeconds);
            if(stage.sourceSeconds==0){
                quest.put("Triggers",new JSONArray()
                    .put(new JSONObject().put("type","AllZoneClear").put("param",new JSONArray()))
                    .put(new JSONObject().put("type","HeroPerish").put("param",new JSONArray())));
                quest.put("LoseJudgement",new JSONArray()
                    .put(1).put(-1).put(-1).put(-1).put(-1).put(-1).put(-1).put(-1).put(-1));
            }
            level.getJSONObject("MapInfo").put("sceneName",stage.scene)
                .put("isForceGuideMap",true).put("globalBuff",5);
            JSONObject layer=level.getJSONObject("EnemyLayer");
            layer.put("levelID",Long.toString(stage.id));
            layer.put("lvMin",minimum).put("lvMax",maximum);
            JSONObject firstZone=layer.getJSONArray("areas").getJSONObject(0)
                .getJSONArray("zones").getJSONObject(0);
            if(stage.id==BASESTATION_STAGE){
                installBasestationWaves(layer,firstZone,monsters);
            }else if(stage.id==SMELTER_STAGE){
                // Preserve the source's five monster identities, but stage
                // their arrival so the original lesson's event gates fire.
                JSONArray firstWave=new JSONArray().put(monsters.getJSONObject(1))
                    .put(monsters.getJSONObject(2));
                JSONArray secondWave=new JSONArray().put(monsters.getJSONObject(3));
                JSONArray secondZoneWave=new JSONArray().put(monsters.getJSONObject(0))
                    .put(monsters.getJSONObject(4));
                JSONObject waveTemplate=firstZone.getJSONArray("waves").getJSONObject(0);
                JSONArray zoneWaves=new JSONArray()
                    .put(guideWave(waveTemplate,"Wave_0",firstWave))
                    .put(guideWave(waveTemplate,"Wave_1",secondWave));
                firstZone.put("navP",new JSONArray().put(0.09).put(0).put(-10.84));
                firstZone.put("waves",zoneWaves);
                JSONObject corridor=new JSONObject(firstZone.toString());
                corridor.put("name","Zone_1");
                corridor.put("entryPR",new JSONArray().put(0.06).put(0)
                    .put(-11.966).put(0).put(0).put(0));
                corridor.put("navP",new JSONArray().put(0.085).put(0).put(-14.366));
                corridor.getJSONArray("triggers").getJSONObject(0)
                    .put("PRS",new JSONArray().put(0.06).put(-11.4).put(0).put(2.0));
                corridor.put("waves",new JSONArray()
                    .put(guideWave(waveTemplate,"Wave_0",secondZoneWave)));
                layer.getJSONArray("areas").getJSONObject(0).getJSONArray("zones")
                    .put(corridor);
            }else{
                firstZone.getJSONArray("waves").getJSONObject(0)
                    .put("monsters",monsters);
            }
            responses.put("/combat/mob/info#"+stage.id,
                new JSONObject().put("type","application/octet-stream")
                    .put("base64",Base64.encodeToString(basket.bytes(),Base64.NO_WRAP)));
            responses.put("/combat/mob/json#"+stage.id,
                new JSONObject().put("type","application/json").put("body",level.toString()));
        }
    }
    private static JSONObject namedMonster(JSONArray source,int index,String name,
            double x,double z) throws Exception {
        JSONObject result=new JSONObject(source.getJSONObject(index).toString());
        result.put("name",name);
        result.put("PRS",new JSONArray().put(x).put(z).put(180).put(1));
        return result;
    }
    private static void installBasestationWaves(JSONObject layer,JSONObject firstZone,
            JSONArray monsters) throws Exception {
        // lesson00001 waits for combat-field 1201, then 1301/1302/1303.
        // The event numbering is area 1 / zone 2 or 3 / wave 1..3; the
        // preserved server did not include its JSON, so wave multiplicity is
        // a local restoration. Keep the original five mob IDs and levels.
        JSONObject zoneTemplate=new JSONObject(firstZone.toString());
        JSONObject waveTemplate=zoneTemplate.getJSONArray("waves").getJSONObject(0);
        firstZone.put("entryPR",new JSONArray().put(0).put(0).put(0)
            .put(0).put(0).put(0));
        firstZone.put("navP",new JSONArray().put(2.685).put(0).put(-2.639));
        firstZone.getJSONArray("triggers").getJSONObject(0)
            .put("PRS",new JSONArray().put(1.5).put(-1.5).put(0).put(4));
        firstZone.put("waves",new JSONArray().put(guideWave(waveTemplate,"Wave_0",
            new JSONArray().put(monsters.getJSONObject(4)))));

        JSONObject secondZone=new JSONObject(zoneTemplate.toString());
        secondZone.put("name","Zone_1");
        secondZone.put("entryPR",new JSONArray().put(7.403).put(0).put(-6.963)
            .put(0).put(0).put(0));
        secondZone.put("navP",new JSONArray().put(9.861).put(0).put(-11.385));
        secondZone.getJSONArray("triggers").getJSONObject(0)
            .put("PRS",new JSONArray().put(10.94).put(-12.47).put(0).put(5));
        secondZone.put("waves",new JSONArray().put(guideWave(waveTemplate,"Wave_0",
            new JSONArray().put(monsters.getJSONObject(1))
                .put(monsters.getJSONObject(3))
                .put(namedMonster(monsters,5,"434 #4",11.041,-12.466)))));

        JSONObject thirdZone=new JSONObject(zoneTemplate.toString());
        thirdZone.put("name","Zone_2");
        thirdZone.put("entryPR",new JSONArray().put(19.2).put(0).put(-17.772)
            .put(0).put(0).put(0));
        thirdZone.put("navP",new JSONArray().put(22.936).put(0).put(-25.536));
        thirdZone.getJSONArray("triggers").getJSONObject(0)
            .put("PRS",new JSONArray().put(23.9).put(-26.5).put(0).put(6));
        thirdZone.put("waves",new JSONArray()
            .put(guideWave(waveTemplate,"Wave_0",new JSONArray()
                .put(namedMonster(monsters,0,"432 #12",22.936,-25.536))
                .put(monsters.getJSONObject(2))))
            .put(guideWave(waveTemplate,"Wave_1",new JSONArray()
                .put(namedMonster(monsters,0,"432 #18",25.295,-27.698))))
            .put(guideWave(waveTemplate,"Wave_2",new JSONArray()
                .put(namedMonster(monsters,0,"432 #24",27.655,-29.86)))));
        layer.getJSONArray("areas").getJSONObject(0).getJSONArray("zones")
            .put(secondZone).put(thirdZone);
    }
    private static JSONObject guideWave(JSONObject preserved,String name,
            JSONArray monsters) throws Exception {
        JSONObject wave=new JSONObject(preserved.toString());
        wave.put("name",name);
        wave.put("monsters",monsters);
        wave.put("NextWaveTriggers",new JSONArray().put(new JSONObject()
            .put("type","WaveClear").put("param","")));
        return wave;
    }
    private TutorialBattleFixtures(){}
}
