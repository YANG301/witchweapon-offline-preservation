package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Arrays;

/** Pure save/protobuf regression for the five preserved furnace depths. */
public final class WeaponFurnaceSelfTest {
    private static void check(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    private static byte[] bytes(String path)throws Exception{
        return Files.readAllBytes(Paths.get(path));
    }
    private static String firstOwnedWeapon(JSONObject state,JSONObject source)throws Exception{
        JSONObject owned=state.getJSONObject("ownedServants");
        for(String sid:owned.keySet()){
            ProtoWire servant=ProtoWire.parse(Base64.decode(owned.getString(sid),Base64.DEFAULT));
            for(ProtoWire.Field field:servant.fields)if(field.number==13&&field.type==2){
                String id=Long.toString(ProtoWire.parse(field.data).number(1,0));
                if(source.getJSONObject("weaponCoreItems").has(id))return id;
            }
        }
        throw new AssertionError("No owned original weapon core mapping");
    }
    private static Map<String,String> form(long id,String key,String weapon){
        Map<String,String> args=new LinkedHashMap<String,String>();
        args.put("instanceid",Long.toString(id));args.put("pass","1");args.put("stars","3");
        args.put("idempotency",key);
        if(weapon!=null)args.put("wantweapon",weapon);
        return args;
    }
    private static JSONObject starter(JSONObject catalog)throws Exception{
        JSONObject state=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("stamina",200).put("gold",1000).put("rmb",100);
        LocalEconomy.init(state,catalog);
        return state;
    }
    private static JSONObject started(WeaponFurnace furnace,JSONObject state,long id,String key)throws Exception{
        JSONObject active=new JSONObject(state.toString());
        active.put("active",true).put("activeStage",id).put("startKey",key);
        furnace.recordStart(active,id);
        return active;
    }
    private static int specified(byte[] result)throws Exception{
        int count=0;
        for(ProtoWire.Field field:ProtoWire.parse(result).fields)if(field.number==6)count++;
        return count;
    }
    private static String poolSignature(JSONArray choices)throws Exception{
        java.util.ArrayList<Long> ids=new java.util.ArrayList<Long>();
        for(int i=0;i<choices.length();i++)ids.add(choices.getLong(i));
        java.util.Collections.sort(ids);StringBuilder signature=new StringBuilder();
        for(long id:ids){if(signature.length()>0)signature.append(',');signature.append(id);}
        return signature.toString();
    }
    public static void main(String[] args)throws Exception{
        String root=args.length==0?".":args[0];
        JSONObject responseSet=new JSONObject(new String(bytes(root+"/resources/offline_responses.json"),StandardCharsets.UTF_8));
        JSONObject catalog=responseSet.getJSONObject("_catalog");
        JSONObject source=new JSONObject(new String(bytes(root+"/resources/weapon_furnace_catalog.json"),StandardCharsets.UTF_8));
        WeaponFurnace furnace=new WeaponFurnace(source);
        furnace.install(responseSet);
        for(long id=3120007001L;id<=3120007005L;id++){
            check(responseSet.getJSONObject("/combat/mob/json#"+id)
                .getString("body").contains("\"levelID\":\""+id+"\""),"Wrong combat level ID");
            check(Base64.decode(responseSet.getJSONObject("/combat/mob/info#"+id)
                .getString("base64"),Base64.DEFAULT).length>100,"Missing mob payload");
        }
        JSONObject state=new JSONObject().put("starterProfile",1).put("roleCreated",true)
            .put("stamina",200).put("gold",1000).put("rmb",100);
        LocalEconomy.init(state,catalog);
        String weapon=firstOwnedWeapon(state,source);
        long core=source.getJSONObject("weaponCoreItems").getLong(weapon);
        long now=1800000000L;
        for(long id=3120007001L;id<=3120007005L;id++)
            furnace.validateStart(state,catalog,id,1,now,true,weapon);
        ProtoWire openProgress=new ProtoWire();
        furnace.appendProgress(openProgress,state,1,now,true);
        ProtoWire openChapter=ProtoWire.parse(openProgress.data(1));
        int accessible=0;
        for(ProtoWire.Field field:openChapter.fields)if(field.number==2&&field.type==2 &&
            ProtoWire.parse(field.data).number(4,0)==1)accessible++;
        check(accessible==5,"Open-access client cannot enter all five depths at level one");
        boolean locked=false;
        try{furnace.validateStart(state,catalog,3120007001L,24,now,weapon);}catch(Exception ex){locked=true;}
        check(locked,"Level 24 entered depth 1");
        locked=false;
        try{furnace.validateStart(state,catalog,3120007002L,35,now,weapon);}catch(Exception ex){locked=true;}
        check(locked,"Depth 2 entered before depth 1 victory");
        String unowned=null;
        JSONObject weaponDefs=catalog.getJSONObject("weapons");
        for(String candidate:weaponDefs.keySet()){
            if(source.getJSONObject("weaponCoreItems").has(candidate) &&
                !state.getJSONObject("ownedServants").has(Long.toString(
                    weaponDefs.getJSONObject(candidate).getLong("servant")))){
                unowned=candidate;break;
            }
        }
        check(unowned!=null,"No unowned weapon available for rejection test");
        for(String invalid:new String[]{null,"","0",unowned}){
            boolean rejected=false;
            String before=state.toString();
            try{furnace.validateStart(state,catalog,3120007001L,25,now,true,invalid);}
            catch(java.io.IOException expected){rejected=true;}
            check(rejected && before.equals(state.toString()),
                "An unselected or unowned weapon started a furnace battle");
        }
        JSONObject invalidActive=new JSONObject(state.toString()).put("active",true)
            .put("activeStage",3120007001L).put("startKey","unowned-core");
        long unownedCore=source.getJSONObject("weaponCoreItems").getLong(unowned);
        WeaponFurnace.Settlement invalidChoice=furnace.settle(invalidActive,catalog,
            form(3120007001L,"unowned-core",unowned),now);
        check(specified(invalidChoice.response)==0 &&
            invalidChoice.next.getInt("furnaceCoreClaims")==0 &&
            invalidChoice.next.getInt("furnaceCoreSkipped")==1,
            "Unowned weapon minted a core, used a selection, or prevented an earned battle result");
        JSONObject boundActive=started(furnace,starter(catalog),3120007001L,"bound-core")
            .put("furnaceBattleWeapon",weapon);
        WeaponFurnace.Settlement bound=furnace.settle(boundActive,catalog,
            form(3120007001L,"bound-core",unowned),now);
        check(specified(bound.response)==1 &&
            bound.next.getJSONObject("items").getLong(Long.toString(core))==2 &&
            !bound.next.has("furnaceBattleWeapon"),
            "Settlement changed or retained the weapon bound at battle start");

        byte[] firstResponse=null;
        for(int run=1;run<=3;run++){
            String key="furnace-run-"+run;
            if(run<=2)furnace.validateStart(state,catalog,3120007001L,25,now,weapon);
            else{
                boolean quotaRejected=false;String before=state.toString();
                try{furnace.validateStart(state,catalog,3120007001L,25,now,weapon);}
                catch(java.io.IOException expected){quotaRejected=true;}
                check(quotaRejected && before.equals(state.toString()),
                    "A new battle started after both core selections were consumed");
            }
            JSONObject active=new JSONObject(state.toString());
            active.put("active",true).put("activeStage",3120007001L).put("startKey",key);
            furnace.recordStart(active,3120007001L);
            Map<String,String> request=form(3120007001L,key,run<=2?weapon:null);
            WeaponFurnace.Settlement settlement=furnace.settle(active,catalog,request,now);
            state=settlement.next;
            check(state.getLong("stamina")==(run==1?190:run==2?180:160),"Wrong stamina debit");
            check(state.getInt("furnaceCoreClaims")==Math.min(run,2),"Wrong core claim count");
            check(state.getJSONObject("furnaceStages").getJSONObject("3120007001")
                .getInt("wins")==run,"Wrong per-depth wins");
            if(run==2)check(state.optInt("furnaceAutoClaimedChoices",0)==0,
                "A previously claimed material choice was granted a second time");
            ProtoWire battle=ProtoWire.parse(settlement.response);
            int specified=0;
            for(ProtoWire.Field f:battle.fields)if(f.number==6 && f.type==2){
                ProtoWire selectedLoot=ProtoWire.parse(f.data);
                check(selectedLoot.number(2,0)==core && selectedLoot.number(3,0)==2 && selectedLoot.number(4,0)==2,"Wrong selected core or amount");specified++;
            }
            check(specified==(run<=2?1:0),"Wrong guaranteed core rule");
            WeaponFurnace.Settlement retry=furnace.settle(state,catalog,request,now);
            check(retry.next==null && Arrays.equals(retry.response,settlement.response),
                "Settlement retry changed reward");
            if(run==1){
                firstResponse=settlement.response;
                JSONArray choices=state.getJSONArray("furnacePendingChoiceItems");
                long bonus=choices.getLong(0);
                long extra=choices.getLong(1);
                check(ProtoWire.parse(ProtoWire.parse(firstResponse).data(8)).number(2,0)==bonus &&
                    state.optBoolean("furnacePendingChoiceInitialGranted",false),
                    "The battle result did not bind the free original-pool random material");
                long before=state.getJSONObject("items").optLong(Long.toString(extra),0);
                Map<String,String> choice=new LinkedHashMap<String,String>();
                choice.put("materials",Long.toString(extra));
                WeaponFurnace.Settlement chosen=furnace.chooseMaterials(state,catalog,choice,now);
                state=chosen.next;
                check(state.getJSONObject("items").getLong(Long.toString(extra))==before+1 &&
                    state.getLong("rmb")==95 && state.getInt("furnaceChoicePurchases")==1,
                    "Material choice was not granted");
                check(ProtoWire.parse(ProtoWire.parse(chosen.response).data(8)).number(2,0)==extra,
                    "Native OneOfRandom response is missing");
                WeaponFurnace.Settlement chooseReplay=furnace.chooseMaterials(state,catalog,choice,now);
                check(chooseReplay.next==null && Arrays.equals(chooseReplay.response,chosen.response),
                    "Material choice retry changed inventory");
            }
        }
        check(firstResponse.length>0,"Empty first battle result");
        // The preserved ChooseMaterials request has rid, but no materials.
        // A paid pick must consume the next unseen candidate and the original
        // 5/10/10/15 diamond prices. A request identity, when supplied by a
        // test or later client, replays without charging again.
        WeaponFurnace priceFurnace=new WeaponFurnace(source);
        JSONObject priced=priceFurnace.settle(started(priceFurnace,starter(catalog),
            3120007003L,"four-prices"),catalog,
            form(3120007003L,"four-prices",weapon),now).next;
        JSONArray expanded=priced.getJSONArray("furnacePendingChoiceItems");
        check(expanded.length()==5,"Furnace must offer one free and four paid core choices");
        Map<String,String> wrongPool=new LinkedHashMap<String,String>();
        wrongPool.put("idempotency","wrong-pool");wrongPool.put("choicePool","40330039");
        String beforeWrongPool=priced.toString();boolean poolRejected=false;
        try{priceFurnace.chooseMaterials(priced,catalog,wrongPool,now);}
        catch(java.io.IOException expected){poolRejected=true;}
        check(poolRejected && beforeWrongPool.equals(priced.toString()),
            "A stale furnace choice pool bought from a different battle");
        java.util.Set<Long> priceClaimed=new java.util.HashSet<Long>();
        priceClaimed.add(expanded.getLong(0));
        int[] prices={5,10,10,15};
        long balance=100;
        byte[] firstPaidResponse=null;
        for(int i=0;i<prices.length;i++){
            Map<String,String> nativeChoice=new LinkedHashMap<String,String>();
            nativeChoice.put("rid","123");
            nativeChoice.put("idempotency","four-prices-"+i);
            nativeChoice.put("choicePool",poolSignature(expanded));
            JSONObject beforeItems=new JSONObject(priced.getJSONObject("items").toString());
            WeaponFurnace.Settlement paid=priceFurnace.chooseMaterials(
                priced,catalog,nativeChoice,now);
            long materialId=ProtoWire.parse(ProtoWire.parse(paid.response).data(8)).number(2,0);
            check(priceClaimed.add(materialId),"Paid furnace choice repeated an obtained core");
            long before=beforeItems.optLong(Long.toString(materialId),0);
            if(i==0)firstPaidResponse=paid.response;
            balance-=prices[i];priced=paid.next;
            check(priced.getLong("rmb")==balance &&
                priced.getInt("furnaceChoicePurchases")==i+1 &&
                priced.getJSONObject("items").getLong(Long.toString(materialId))==before+1 &&
                ProtoWire.parse(ProtoWire.parse(paid.response).data(8)).number(2,0)==materialId,
                "Native paid material or original diamond price was not persisted");
            WeaponFurnace.Settlement paidReplay=priceFurnace.chooseMaterials(
                priced,catalog,nativeChoice,now);
            check(paidReplay.next==null && Arrays.equals(paidReplay.response,paid.response),
                "Identified furnace choice retry charged a second time");
            if(i==0){
                Map<String,String> conflicting=new LinkedHashMap<String,String>(nativeChoice);
                conflicting.put("materials",Long.toString(expanded.getLong(2)));
                String beforeConflict=priced.toString();boolean rejected=false;
                try{priceFurnace.chooseMaterials(priced,catalog,conflicting,now);}
                catch(java.io.IOException expected){rejected=true;}
                check(rejected && beforeConflict.equals(priced.toString()),
                    "Reused choice request identity accepted changed materials");
            }
        }
        check(!priced.has("furnacePendingChoiceItems") && balance==60,
            "Four paid material choices did not exhaust the original price table");
        Map<String,String> fifthChoice=new LinkedHashMap<String,String>();
        fifthChoice.put("idempotency","fifth-choice");
        String beforeFifth=priced.toString();boolean fifthRejected=false;
        try{priceFurnace.chooseMaterials(priced,catalog,fifthChoice,now);}
        catch(java.io.IOException expected){fifthRejected=true;}
        check(fifthRejected && beforeFifth.equals(priced.toString()),
            "A fifth paid choice changed the exhausted furnace reward state");
        Map<String,String> noId=new LinkedHashMap<String,String>();noId.put("rid","123");
        WeaponFurnace.Settlement exhausted=priceFurnace.chooseMaterials(priced,catalog,noId,now);
        check(exhausted.next==null && priced.getLong("rmb")==60,
            "An exhausted no-ID native request charged again");
        JSONObject nextBattle=priceFurnace.settle(started(priceFurnace,priced,
            3120007003L,"after-four-prices"),catalog,
            form(3120007003L,"after-four-prices",weapon),now).next;
        Map<String,String> oldIdentity=new LinkedHashMap<String,String>();
        oldIdentity.put("rid","123");oldIdentity.put("idempotency","four-prices-0");
        oldIdentity.put("choicePool",poolSignature(expanded));
        WeaponFurnace.Settlement crossBattle=priceFurnace.chooseMaterials(
            nextBattle,catalog,oldIdentity,now);
        check(crossBattle.next==null &&
            Arrays.equals(crossBattle.response,firstPaidResponse) &&
            nextBattle.getLong("rmb")==60 && nextBattle.has("furnacePendingChoiceItems"),
            "An identified retry from the previous battle bought from the new pool");
        Map<String,String> changedOldIdentity=new LinkedHashMap<String,String>(oldIdentity);
        changedOldIdentity.put("materials",Long.toString(expanded.getLong(2)));
        String beforeCrossConflict=nextBattle.toString();
        boolean crossConflictRejected=false;
        try{priceFurnace.chooseMaterials(nextBattle,catalog,changedOldIdentity,now);}
        catch(java.io.IOException expected){crossConflictRejected=true;}
        check(crossConflictRejected && beforeCrossConflict.equals(nextBattle.toString()),
            "An identified retry from the previous battle accepted changed materials");
        JSONObject nativeOnly=priceFurnace.settle(started(priceFurnace,
            starter(catalog),3120007003L,"native-only"),catalog,
            form(3120007003L,"native-only",weapon),now).next;
        WeaponFurnace.Settlement nativeFirst=priceFurnace.chooseMaterials(
            nativeOnly,catalog,noId,now);
        WeaponFurnace.Settlement nativeReplay=priceFurnace.chooseMaterials(
            nativeFirst.next,catalog,noId,now);
        check(nativeFirst.next.has("furnacePendingChoiceItems") &&
            nativeFirst.next.getLong("rmb")==95 &&
            nativeFirst.next.getInt("furnaceChoicePurchases")==1 &&
            nativeReplay.next==null &&
            Arrays.equals(nativeFirst.response,nativeReplay.response),
            "Rid-only retry spent diamonds while unclaimed candidates remained");
        JSONObject poor=priceFurnace.settle(started(priceFurnace,
            starter(catalog).put("rmb",4),3120007001L,"poor-choice"),catalog,
            form(3120007001L,"poor-choice",weapon),now).next;
        String beforePoor=poor.toString();boolean insufficient=false;
        try{priceFurnace.chooseMaterials(poor,catalog,noId,now);}
        catch(java.io.IOException expected){insufficient=true;}
        check(insufficient && beforePoor.equals(poor.toString()),
            "Insufficient diamonds changed the account or granted a material");
        WeaponFurnace.Settlement exact=priceFurnace.chooseMaterials(
            new JSONObject(poor.toString()).put("rmb",5),catalog,noId,now);
        check(exact.next.getLong("rmb")==0 && exact.next.getInt("furnaceChoicePurchases")==1,
            "Exactly five diamonds could not buy the first extra material");
        java.util.Set<Long> stagePool=new java.util.HashSet<Long>();
        org.json.JSONArray listed=source.getJSONObject("stages").getJSONObject("3120007001")
            .getJSONArray("originalDropItems");
        for(int i=0;i<listed.length();i++)stagePool.add(listed.getLong(i));
        for(ProtoWire.Field field:ProtoWire.parse(firstResponse).fields){
            if(field.type!=2 || (field.number!=3 && field.number!=6 &&
                field.number!=7 && field.number!=8))continue;
            ProtoWire entry=ProtoWire.parse(field.data);
            long item=entry.number(2,0);
            check(entry.number(1,0)==3,"Furnace battle result has a non-item reward type");
            if(field.number==6)check(item==core,
                "The specified bonus is not the chosen weapon core");
            else if(field.number==3)check(stagePool.contains(item),
                "Ordinary furnace material is outside the stage's original pool");
            else {
                boolean originalCore=false;
                for(String originalWeapon:source.getJSONObject("weaponCoreItems").keySet())
                    if(source.getJSONObject("weaponCoreItems").getLong(originalWeapon)==item)
                        originalCore=true;
                check(originalCore && !stagePool.contains(item),
                    "Optional furnace reward is not an original weapon core");
            }
        }
        StringBuilder rewardFields=new StringBuilder();
        for(ProtoWire.Field field:ProtoWire.parse(firstResponse).fields)
            if(field.type==2 && (field.number==3 || field.number==6 ||
                field.number==7 || field.number==8))
                rewardFields.append(field.number).append(':')
                    .append(ProtoWire.parse(field.data).number(2,0)).append(' ');
        System.out.println("FURNACE_REWARD_AUDIT stage=3120007001 weapon="+weapon+
            " core="+core+" fields="+rewardFields.toString().trim());
        check(state.getJSONObject("items").getLong(Long.toString(core))>=4,
            "Chosen core was not persisted twice");

        // Verify every depth has exactly five distinct core-only candidates,
        // one already-granted member, and a guaranteed quantity of two.
        for(long depth=3120007001L;depth<=3120007005L;depth++){
            WeaponFurnace.Settlement checkDepth=furnace.settle(started(furnace,
                starter(catalog),depth,"core-pool-"+depth),catalog,
                form(depth,"core-pool-"+depth,weapon),now);
            ProtoWire payload=ProtoWire.parse(checkDepth.response);
            java.util.Set<Long> choices=new java.util.HashSet<Long>();int count=0;
            for(ProtoWire.Field field:payload.fields)if(field.number==7 && field.type==2){
                ProtoWire candidate=ProtoWire.parse(field.data);
                check(candidate.number(3,0)==1 && choices.add(candidate.number(2,0)),
                    "Furnace random candidates repeat an ID or quantity");count++;
            }
            check(count==5 && choices.contains(ProtoWire.parse(payload.data(8)).number(2,0)) &&
                !choices.contains(core),"Furnace random pool does not bind the obtained slot");
        }
        JSONObject fullCore=starter(catalog);
        fullCore.getJSONObject("items").put(Long.toString(core),
            LocalEconomy.stackCap(catalog,Long.toString(core))-1);
        JSONObject fullCoreBattle=started(furnace,fullCore,3120007001L,"full-specified-core");
        String beforeFullCore=fullCoreBattle.toString();boolean fullCoreRejected=false;
        try{furnace.settle(fullCoreBattle,catalog,
            form(3120007001L,"full-specified-core",weapon),now);}
        catch(java.io.IOException expected){fullCoreRejected=true;}
        check(fullCoreRejected && beforeFullCore.equals(fullCoreBattle.toString()),
            "A two-core guaranteed reward was partially granted or silently skipped at stack cap");

        JSONObject partialClock=starter(catalog).put("stamina",50)
            .put("staminaRegenCap",60).put("staminaRegenAt",now-100);
        WeaponFurnace.Settlement timed=furnace.settle(
            started(furnace,partialClock,3120007001L,"partial-clock"),catalog,
            form(3120007001L,"partial-clock",weapon),now);
        ProtoWire timedResult=ProtoWire.parse(timed.response);
        check(timedResult.number(1,0)==40 && timedResult.number(2,0)==now-100,
            "Furnace BattleResult reset the original AP countdown");

        // Native re-entry may omit wantweapon even though the previous valid
        // selection remains on the account. The second victory must settle.
        long stage=3120007001L;
        JSONObject fresh=starter(catalog);
        JSONObject first=furnace.settle(started(furnace,fresh,stage,"keep-first"),catalog,
            form(stage,"keep-first",weapon),now).next;
        long material=source.getJSONObject("stages").getJSONObject(Long.toString(stage))
            .getJSONArray("originalDropItems").getLong(0);
        long firstMaterials=first.getJSONObject("items").getLong(Long.toString(material));
        JSONObject secondStart=started(furnace,first,stage,"keep-second");
        check(secondStart.has("furnacePendingChoiceItems") &&
            "keep-first".equals(secondStart.getString("furnacePendingChoiceKey")),
            "Rebattle erased the previous material choice");
        WeaponFurnace.Settlement second=furnace.settle(secondStart,catalog,
            form(stage,"keep-second",null),now);
        JSONObject secondSaved=second.next;
        check(secondSaved.getLong("stamina")==180 &&
            secondSaved.getInt("furnaceCoreClaims")==2 &&
            secondSaved.getJSONObject("items").getLong(Long.toString(core))==4 &&
            specified(second.response)==1,
            "Missing second wantweapon rejected victory or lost the prior valid core choice");
        check(secondSaved.optInt("furnaceAutoClaimedChoices",0)==0 &&
            secondSaved.getJSONObject("items").getLong(Long.toString(material))==firstMaterials+1 &&
            "keep-second".equals(secondSaved.getString("furnacePendingChoiceKey")),
            "Abandoned optional pick was granted free or the second battle random material was lost");
        WeaponFurnace.Settlement repeatedSecond=furnace.settle(secondSaved,catalog,
            form(stage,"keep-second",null),now);
        check(repeatedSecond.next==null && Arrays.equals(repeatedSecond.response,second.response),
            "Retried second settlement awarded resources twice");
        JSONObject zeroSelected=furnace.settle(started(furnace,first,stage,"zero-second"),
            catalog,form(stage,"zero-second","0"),now).next;
        check(zeroSelected.getJSONObject("items").getLong(Long.toString(core))==4 &&
            zeroSelected.getInt("furnaceCoreClaims")==2,
            "Native zero-valued optional selection did not reuse the last owned weapon");
        Map<String,String> omittedStage=form(stage,"omitted-stage",null);
        omittedStage.remove("instanceid");
        JSONObject withoutStage=furnace.settle(started(furnace,first,stage,"omitted-stage"),
            catalog,omittedStage,now).next;
        check(withoutStage.getInt("furnaceCoreClaims")==2 &&
            withoutStage.getLong("stamina")==180,
            "Active furnace stage could not settle when the native request omitted its optional ID");
        boolean wrongStageRejected=false,invalidPassRejected=false;
        ByteArrayOutputStream diagnostic=new ByteArrayOutputStream();
        PrintStream formerError=System.err;
        try{
            System.setErr(new PrintStream(diagnostic,true,"UTF-8"));
            try{furnace.settle(started(furnace,first,stage,"wrong-stage"),catalog,
                form(stage+1,"wrong-stage",weapon),now);}
            catch(java.io.IOException expected){wrongStageRejected=true;}
            Map<String,String> malformed=form(stage,"invalid-pass",weapon);
            malformed.put("pass","private-form-marker");
            try{furnace.settle(started(furnace,first,stage,"invalid-pass"),catalog,
                malformed,now);}
            catch(java.io.IOException expected){invalidPassRejected=true;}
        }finally{System.setErr(formerError);}
        check(wrongStageRejected,"Explicitly mismatched furnace stage was accepted");
        String labels=new String(diagnostic.toByteArray(),StandardCharsets.UTF_8);
        check(invalidPassRejected && labels.contains("FURNACE_SETTLEMENT_REJECT STAGE_MISMATCH") &&
            labels.contains("FURNACE_SETTLEMENT_REJECT INVALID_PASS") &&
            !labels.contains("private-form-marker"),
            "Settlement diagnostics leaked form data or lost the fixed rejection category");
        JSONObject invalidSecond=furnace.settle(started(furnace,first,stage,"invalid-second"),
            catalog,form(stage,"invalid-second",unowned),now).next;
        check(invalidSecond.getJSONObject("items").getLong(Long.toString(core))==4,
            "Invalid second selection minted an unowned core instead of using the last valid choice");

        // Reconstruct the already deployed broken state: the old start route
        // removed an earned first choice before the second battle completed.
        JSONObject legacy=started(furnace,first,stage,"legacy-second");
        legacy.remove("furnacePendingChoiceItems");legacy.remove("furnacePendingChoiceKey");
        legacy.remove("furnacePendingChoiceInitialGranted");
        legacy.getJSONObject("items").put(Long.toString(material),firstMaterials-1);
        WeaponFurnace.Settlement recovered=furnace.settle(legacy,catalog,
            form(stage,"legacy-second",null),now);
        check(recovered.next.optBoolean("furnaceLegacyChoiceRecovered",false) &&
            recovered.next.getInt("furnaceAutoClaimedChoices")==1 &&
            recovered.next.getJSONObject("items").getLong(Long.toString(material))==firstMaterials+1,
            "Already-lost first choice was not recovered during the live second settlement");
        WeaponFurnace.Settlement recoveredReplay=furnace.settle(recovered.next,catalog,
            form(stage,"legacy-second",null),now);
        check(recoveredReplay.next==null &&
            Arrays.equals(recoveredReplay.response,recovered.response) &&
            recovered.next.getInt("furnaceAutoClaimedChoices")==1 &&
            recovered.next.getJSONObject("items").getLong(Long.toString(material))==firstMaterials+1,
            "Legacy material recovery ran twice on a retried settlement");

        // A player can still claim the earlier choice while a new battle is
        // active; its duplicate request remains idempotent.
        JSONObject chooseDuringBattle=started(furnace,first,stage,"choose-later");
        Map<String,String> chooseForm=new LinkedHashMap<String,String>();
        long remaining=first.getJSONArray("furnacePendingChoiceItems").getLong(1);
        long remainingBefore=chooseDuringBattle.getJSONObject("items")
            .optLong(Long.toString(remaining),0);
        chooseForm.put("materials",Long.toString(remaining));
        WeaponFurnace.Settlement claimed=furnace.chooseMaterials(
            chooseDuringBattle,catalog,chooseForm,now);
        WeaponFurnace.Settlement claimedAgain=furnace.chooseMaterials(
            claimed.next,catalog,chooseForm,now);
        check(claimed.next.optBoolean("active",false) &&
            claimed.next.getJSONObject("items").getLong(Long.toString(remaining))==remainingBefore+1 &&
            claimed.next.getLong("rmb")==95 &&
            claimedAgain.next==null && Arrays.equals(claimed.response,claimedAgain.response),
            "Earlier material choice was unavailable or paid twice during rebattle");

        // A missing core selection must not consume one of two daily choices.
        // Existing active battles still settle, including later re-entry.
        JSONObject noSelection=starter(catalog);
        for(int run=1;run<=5;run++){
            String key="none-"+run;
            WeaponFurnace.Settlement result=furnace.settle(
                started(furnace,noSelection,stage,key),catalog,form(stage,key,null),now);
            noSelection=result.next;
            check(specified(result.response)==0 &&
                noSelection.getInt("furnaceCoreClaims")==0 &&
                noSelection.getInt("furnaceDailyRuns")==run &&
                noSelection.getLong("stamina")==200-run*10,
                "Missing core selection used a daily choice or blocked settlement");
        }
        Map<String,String> unselectedSweep=new LinkedHashMap<String,String>();
        unselectedSweep.put("chapid",Long.toString(WeaponFurnace.CHAPTER));
        unselectedSweep.put("instanceid",Long.toString(stage));
        unselectedSweep.put("count","2");
        unselectedSweep.put("idempotency","none-sweep");
        String beforeRejectedSweep=noSelection.toString();
        boolean unselectedSweepRejected=false;
        try{furnace.sweep(noSelection,catalog,unselectedSweep,now,true);}
        catch(java.io.IOException expected){unselectedSweepRejected=true;}
        check(unselectedSweepRejected && beforeRejectedSweep.equals(noSelection.toString()),
            "Unselected sweep was accepted or changed the account");
        ProtoWire unselectedProgress=new ProtoWire();
        furnace.appendProgress(unselectedProgress,noSelection,25,now,true);
        check(unselectedProgress.number(2,-1)==0 && unselectedProgress.number(5,-1)==0,
            "Five unselected runs produced negative remaining choices in the native panel");
        WeaponFurnace.Settlement selectedAfterSkip=furnace.settle(
            started(furnace,noSelection,stage,"select-after-skip"),catalog,
            form(stage,"select-after-skip",weapon),now);
        check(selectedAfterSkip.next.getInt("furnaceCoreClaims")==1 &&
            selectedAfterSkip.next.getInt("furnaceDailyRuns")==6 &&
            selectedAfterSkip.next.getLong("stamina")==140 &&
            specified(selectedAfterSkip.response)==1,
            "A valid choice after unselected runs did not earn its first daily core");
        ProtoWire selectedProgress=new ProtoWire();
        furnace.appendProgress(selectedProgress,selectedAfterSkip.next,25,now,true);
        check(selectedProgress.number(2,-1)==1 && selectedProgress.number(5,-1)==1,
            "Selected core quota did not update the native panel");
        Map<String,String> oversizedSweep=new LinkedHashMap<String,String>(unselectedSweep);
        oversizedSweep.put("idempotency","oversized-sweep");
        String beforeOversized=selectedAfterSkip.next.toString();
        boolean oversizedRejected=false;
        try{furnace.sweep(selectedAfterSkip.next,catalog,oversizedSweep,now,true);}
        catch(java.io.IOException expected){oversizedRejected=true;}
        check(oversizedRejected && beforeOversized.equals(selectedAfterSkip.next.toString()),
            "A sweep exceeded the one remaining core selection or changed the account");
        JSONObject validSweepState=new JSONObject(noSelection.toString())
            .put("furnaceSelectedWeapon",weapon);
        Map<String,String> selectedSweep=new LinkedHashMap<String,String>(unselectedSweep);
        selectedSweep.put("idempotency","selected-sweep");
        WeaponFurnace.Settlement swept=furnace.sweep(validSweepState,catalog,
            selectedSweep,now,true);
        check(swept.next.getInt("furnaceCoreClaims")==2 &&
            swept.next.getInt("furnaceDailyRuns")==7 &&
            swept.next.getLong("stamina")==130 &&
            swept.next.getJSONObject("items").getLong(Long.toString(core))==noSelection.getJSONObject("items").optLong(Long.toString(core),0)+4,
            "Valid selected sweep did not grant and count two cores");
        Map<String,String> afterQuotaSweep=new LinkedHashMap<String,String>(selectedSweep);
        afterQuotaSweep.put("count","1");
        afterQuotaSweep.put("idempotency","after-quota-sweep");
        String beforeQuotaSweep=swept.next.toString();boolean quotaSweepRejected=false;
        try{furnace.sweep(swept.next,catalog,afterQuotaSweep,now,true);}
        catch(java.io.IOException expected){quotaSweepRejected=true;}
        check(quotaSweepRejected && beforeQuotaSweep.equals(swept.next.toString()),
            "A sweep started after the daily core selections were exhausted");
        JSONObject staleSelection=new JSONObject(noSelection.toString())
            .put("furnaceSelectedWeapon",unowned);
        Map<String,String> staleSweep=new LinkedHashMap<String,String>(unselectedSweep);
        staleSweep.put("idempotency","unowned-sweep");
        String beforeStaleSweep=staleSelection.toString();
        boolean staleSweepRejected=false;
        try{furnace.sweep(staleSelection,catalog,staleSweep,now,true);}
        catch(java.io.IOException expected){staleSweepRejected=true;}
        check(staleSweepRejected && beforeStaleSweep.equals(staleSelection.toString()),
            "Stale unowned sweep selection was accepted or changed the account");
        ProtoWire progress=new ProtoWire();
        furnace.appendProgress(progress,state,25,now);
        check(state.getInt("furnaceDailyRuns")==3 &&
            progress.number(2,-1)==2 && progress.number(5,-1)==2,
            "Native quota displayed more than two used core selections");
        ProtoWire nextDay=new ProtoWire();
        furnace.appendProgress(nextDay,state,25,now+86400);
        check(nextDay.number(2,-1)==0 && nextDay.number(5,-1)==0,
            "Furnace daily allowance did not reset");
        furnace.validateStart(state,catalog,stage,25,now+86400,weapon);
        System.out.println("Weapon furnace five-depth resource, gated start, three wins, stamina, cores and replay OK");
    }
}
