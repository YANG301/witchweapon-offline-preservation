package com.codex.witchweapon;

import java.io.File;
import java.nio.file.Files;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.UUID;
import org.json.JSONObject;

public final class GuildSelfTest {
    private static File testDirectory;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static GuildStore.Identity role(String account,long id,String name){
        return new GuildStore.Identity(account,id,name,1,1,20);
    }
    private static Map<String,String> form(String... pairs){
        Map<String,String> result=new HashMap<String,String>();
        for(int i=0;i<pairs.length;i+=2)result.put(pairs[i],pairs[i+1]);
        return result;
    }
    private interface Action {void run()throws Exception;}
    private static void rejected(Class<? extends Exception> type,Action action)throws Exception {
        try {action.run();throw new AssertionError("Expected "+type.getSimpleName());}
        catch(Exception failure){if(!type.isInstance(failure))throw failure;}
    }
    private static ProtoWire message(GuildStore store,String route,GuildStore.Identity actor,
                                     Map<String,String> args)throws Exception {
        return ProtoWire.parse(store.respond(route,actor,args));
    }
    private static String utf8(byte[] data)throws Exception {
        return new String(data,"UTF-8");
    }
    private static String own(GuildStore store,GuildStore.Identity actor)throws Exception {
        ProtoWire info=message(store,"/guild/getUserGuild",actor,Collections.<String,String>emptyMap());
        check("ok".equals(utf8(info.data(3))),"Original GuildInfo success marker");
        return utf8(ProtoWire.parse(info.data(1)).data(2));
    }
    private static String create(GuildStore store,GuildStore.Identity actor,String name)throws Exception {
        ProtoWire.parse(store.createCharged(actor,form("guildName",name,"guildSlogan","怀旧集会所",
            "emblem","1","emblemborder","1","emblembackground","1"),testSave(actor)));
        String guild=own(store,actor);check(guild.matches("g[0-9a-f]{24}"),"Created guild ID");
        return guild;
    }
    private static LocalSave testSave(GuildStore.Identity actor)throws Exception {
        File directory=new File(new File(testDirectory,"users"),actor.accountId);
        Files.createDirectories(directory.toPath());
        File file=new File(directory,"offline_save_v1.json");
        if(!file.exists()){
            JSONObject value=new JSONObject().put("version",1).put("roleCreated",true)
                .put("legacyRoleId",actor.roleId).put("name",actor.name)
                .put("gold",1000000).put("rmb",100000).put("exp",2300);
            Files.write(file.toPath(),(value.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        }
        return new LocalSave(directory);
    }
    private static String pendingCreate(File dir,GuildStore.Identity actor,String name)throws Exception {
        String id="g"+String.format("%024x",actor.roleId);
        String tx=UUID.randomUUID().toString();
        File guildFile=new File(dir,"guild_state_v1.json");
        JSONObject state=new JSONObject(new String(Files.readAllBytes(guildFile.toPath()),StandardCharsets.UTF_8));
        JSONObject member=new JSONObject().put("accountId",actor.accountId).put("roleId",actor.roleId)
            .put("name",actor.name).put("head",1).put("headBox",1).put("level",20)
            .put("joinedAt",System.currentTimeMillis()/1000).put("privilege",2);
        JSONObject group=new JSONObject().put("id",id).put("name",name).put("slogan","")
            .put("notice","").put("president",actor.roleId)
            .put("members",new JSONObject().put(Long.toString(actor.roleId),member))
            .put("requests",new JSONObject());
        state.put("pendingCreate",new JSONObject().put("transaction",tx)
            .put("accountId",actor.accountId).put("roleId",actor.roleId).put("guild",group));
        Files.write(guildFile.toPath(),(state.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        return tx;
    }
    private static int memberCount(GuildStore store,GuildStore.Identity actor)throws Exception {
        ProtoWire info=message(store,"/guild/getUserGuild",actor,Collections.<String,String>emptyMap());
        ProtoWire guild=ProtoWire.parse(info.data(2));int count=0;
        for(ProtoWire.Field field:guild.fields)if(field.number==4)count++;
        return count;
    }
    private static ProtoWire memberInfo(ProtoWire common,long role)throws Exception {
        for(ProtoWire.Field field:common.fields)if(field.number==4) {
            ProtoWire person=ProtoWire.parse(field.data);
            if(person.number(1,0)==role)return person;
        }
        throw new AssertionError("Member missing from original Guild payload");
    }
    private static java.util.Set<Long> deployedIds(GuildStore store,GuildStore.Identity actor)throws Exception {
        ProtoWire info=message(store,"/guild/getUserGuild",actor,Collections.<String,String>emptyMap());
        ProtoWire user=ProtoWire.parse(info.data(1));
        return new java.util.HashSet<Long>(user.integers(6));
    }
    private static java.util.List<ProtoWire> donationLogs(GuildStore store,
        GuildStore.Identity actor)throws Exception {
        ProtoWire guild=ProtoWire.parse(message(store,"/guild/getUserGuild",actor,
            Collections.<String,String>emptyMap()).data(2));
        java.util.List<ProtoWire> logs=new java.util.ArrayList<ProtoWire>();
        for(ProtoWire.Field field:guild.fields)if(field.number==17&&field.type==2)
            logs.add(ProtoWire.parse(field.data));
        return logs;
    }
    private static java.util.Set<Long> listedMercenaries(GuildStore store,
        GuildStore.Identity actor,String guildId)throws Exception {
        ProtoWire list=message(store,"/guild/mercenariesList",actor,form("guildID",guildId));
        java.util.Set<Long> ids=new java.util.HashSet<Long>();
        for(ProtoWire.Field field:list.fields)if(field.number==2) {
            ProtoWire map=ProtoWire.parse(field.data);
            ProtoWire mercenary=ProtoWire.parse(map.data(2));
            ids.add(mercenary.number(2,0));
        }
        return ids;
    }
    private static long listedTimeProfit(GuildStore store,GuildStore.Identity actor,
        String guildId,long servantId)throws Exception {
        ProtoWire list=message(store,"/guild/mercenariesList",actor,form("guildID",guildId));
        for(ProtoWire.Field field:list.fields)if(field.number==2) {
            ProtoWire map=ProtoWire.parse(field.data);
            ProtoWire mercenary=ProtoWire.parse(map.data(2));
            if(mercenary.number(2,0)==servantId)return mercenary.number(7,-1);
        }
        throw new AssertionError("Mercenary not listed");
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("Pass isolated test directory");
        File dir=new File(args[0]);Files.createDirectories(dir.toPath());
        testDirectory=dir;
        if(Files.exists(dir.toPath().resolve("guild_state_v1.json")))
            throw new IllegalArgumentException("Test directory must start empty");
        final GuildStore initial=new GuildStore(dir);
        GuildStore store=initial;
        GuildStore.Identity a=role("AAAAAAAAAAAAAAAAAAAAAA",101,"会长甲");
        GuildStore.Identity b=role("BBBBBBBBBBBBBBBBBBBBBB",202,"会员乙");
        GuildStore.Identity c=role("CCCCCCCCCCCCCCCCCCCCCC",303,"路人丙");
        GuildStore.Identity d=role("DDDDDDDDDDDDDDDDDDDDDD",404,"路人丁");
        check(own(store,a).isEmpty(),"Initially no guild");
        check(!store.isMember(a.accountId,a.roleId) && !store.isMember("",a.roleId) &&
            !store.isMember(a.accountId,0),"Unknown or invalid member identities are rejected");
        String id=create(store,a,"测试集会所");
        check(donationLogs(store,a).isEmpty(),"Fresh guild has no donation history");
        ProtoWire donateReply=ProtoWire.parse(store.donateCharged(a,form("guildid",id),testSave(a),false));
        ProtoWire immediateGuild=ProtoWire.parse(donateReply.data(2));
        boolean immediateLog=false;
        for(ProtoWire.Field field:immediateGuild.fields)if(field.number==17) {
            ProtoWire event=ProtoWire.parse(field.data);
            immediateLog=event.number(4,0)==10080;
        }
        check(immediateLog,"Donation reply includes the newly committed log immediately");
        java.util.List<ProtoWire> donation=donationLogs(store,a);
        check(donation.size()==1&&donation.get(0).number(1,0)==1&&
            donation.get(0).number(2,0)>0&&donation.get(0).number(4,0)==10080&&
            "会长甲".equals(utf8(donation.get(0).data(5))),
            "Original guild gold donation log and dictionary interpolation");
        store.donateCharged(a,form("guildid",id),testSave(a),false);
        check(donationLogs(store,a).size()==1&&
            donationLogs(new GuildStore(dir),a).size()==1,
            "Donation replay and restart cannot duplicate historical log");
        check(store.isMember(a.accountId,a.roleId) && !store.isMember(c.accountId,a.roleId),
            "Membership requires the authoritative account ID and role ID");
        GuildStore.Identity tooYoung=new GuildStore.Identity("EEEEEEEEEEEEEEEEEEEEEE",505,"未满级",1,1,14);
        check(own(store,tooYoung).isEmpty(),"Login guild probe remains available below entry level");
        check(message(initial,"/guild/guilds",tooYoung,Collections.<String,String>emptyMap())
            .number(2,-1)==1,"Open-access guild list is available at level one");
        rejected(GuildStore.Conflict.class,()->create(initial,b,"测试集会所"));
        ProtoWire list=message(store,"/guild/guilds",b,form("page","1"));
        check(list.number(2,-1)==1,"List total count");
        ProtoWire item=ProtoWire.parse(list.data(1));
        check(id.equals(utf8(item.data(1))) && "测试集会所".equals(utf8(item.data(2))),
            "Original AllGuildInfo list fields");
        check(message(store,"/guild/search",b,form("guildname","测试")).number(2,-1)==1,
            "Search original list");
        check(message(store,"/guild/search",b,form("guildname","不存在")).number(2,-1)==0,
            "Search account isolation");
        message(store,"/guild/apply",b,form("guildid",id,"roleid","101"));
        message(store,"/guild/apply",b,form("guildid",id));
        check(ProtoWire.parse(message(store,"/guild/getUserGuild",b,
            Collections.<String,String>emptyMap()).data(1)).data(3).length>0,
            "Applicant sees pending guild");
        rejected(GuildStore.Forbidden.class,()->message(initial,"/guild/handleRequest",c,
            form("guildid",id,"targetid","202","allow","1")));
        rejected(GuildStore.Forbidden.class,()->message(initial,"/guild/recallPresident",c,
            form("guildid",id)));
        rejected(GuildStore.Forbidden.class,()->message(initial,"/guild/getUserGuild",
            role(c.accountId,a.roleId,c.name),Collections.<String,String>emptyMap()));
        message(store,"/guild/handleRequest",a,form("guildid",id,"targetid","202","allow","1"));
        check(id.equals(own(store,b)) && memberCount(store,b)==2,"Approved member sees shared guild");
        check(store.isMember(b.accountId,b.roleId) && !store.isMember(c.accountId,b.roleId),
            "Approved guild member is account-bound");
        rejected(GuildStore.Conflict.class,()->message(initial,"/guild/apply",b,form("guildid",id)));
        rejected(GuildStore.Forbidden.class,()->message(initial,"/guild/editNotice",b,
            form("guildid",id,"notice","伪造公告")));
        message(store,"/guild/editNotice",a,form("guildid",id,"notice","欢迎测试"));
        check("欢迎测试".equals(utf8(ProtoWire.parse(message(store,"/guild/getUserGuild",b,
            Collections.<String,String>emptyMap()).data(2)).data(9))),"Shared notice");
        store=new GuildStore(dir);
        check(id.equals(own(store,b)) && memberCount(store,a)==2,"Restart restores shared membership");
        final GuildStore restored=store;
        rejected(GuildStore.Invalid.class,()->message(restored,"/guild/editPrivilege",a,
            form("guildid",id,"targetid","202","targetposition","4")));
        message(store,"/guild/editPrivilege",a,form("guildid",id,"targetid","202","targetposition","2"));
        ProtoWire promotedGuild=ProtoWire.parse(message(store,"/guild/getUserGuild",b,
            Collections.<String,String>emptyMap()).data(2));
        check(promotedGuild.integers(3).contains(202L),"Original targetposition=2 grants administrator");
        message(store,"/guild/editSlogan",b,form("guildid",id,"slogan","副会长编辑"));
        message(store,"/guild/editPrivilege",a,form("guildid",id,"targetid","202","targetposition","1"));
        rejected(GuildStore.Forbidden.class,()->message(restored,"/guild/editSlogan",b,
            form("guildid",id,"slogan","普通成员不可改")));
        message(store,"/guild/editPrivilege",a,form("guildid",id,"targetid","202","targetposition","2"));
        rejected(GuildStore.Forbidden.class,()->message(restored,"/guild/kickOut",b,
            form("guildid",id,"targetid","101")));
        rejected(GuildStore.Conflict.class,()->message(restored,"/guild/dissolveGuild",a,form("guildid",id)));
        message(store,"/guild/changePresident",a,form("guildid",id,"targetid","202"));
        rejected(GuildStore.Forbidden.class,()->message(restored,"/guild/editNotice",a,
            form("guildid",id,"notice","旧会长")));
        message(store,"/guild/leaveGuild",a,form("guildid",id));
        check(own(store,a).isEmpty() && memberCount(store,b)==1,"Former leader left");
        message(store,"/guild/dissolveGuild",b,form("guildid",id));
        check(!store.isMember(a.accountId,a.roleId) && !store.isMember(b.accountId,b.roleId),
            "Membership check follows guild dissolution");
        check(own(store,b).isEmpty() && message(store,"/guild/guilds",a,
            Collections.<String,String>emptyMap()).number(2,-1)==0,"Guild dissolved without stale index");
        rejected(GuildStore.Conflict.class,()->create(restored,a,"退会冷却"));
        GuildStore concurrent=new GuildStore(dir);CountDownLatch start=new CountDownLatch(1);
        AtomicInteger successes=new AtomicInteger(),conflicts=new AtomicInteger();
        Thread one=new Thread(()->{
            try {start.await();create(concurrent,c,"并发同名");successes.incrementAndGet();}
            catch(GuildStore.Conflict ex){conflicts.incrementAndGet();}
            catch(Exception ex){throw new RuntimeException(ex);}
        });
        Thread two=new Thread(()->{
            try {start.await();create(concurrent,d,"并发同名");successes.incrementAndGet();}
            catch(GuildStore.Conflict ex){conflicts.incrementAndGet();}
            catch(Exception ex){throw new RuntimeException(ex);}
        });
        one.start();two.start();start.countDown();one.join();two.join();
        check(successes.get()==1 && conflicts.get()==1,"Concurrent duplicate name serialized");
        check(message(new GuildStore(dir),"/guild/guilds",b,form("page","1")).number(2,-1)==1,
            "Concurrent result durable after restart");
        GuildStore.Identity e=role("EEEEEEEEEEEEEEEEEEEEEE",707,"断点前");
        LocalSave eSave=testSave(e);
        pendingCreate(dir,e,"待扣费恢复");
        GuildStore recoverBeforeDebit=new GuildStore(dir);
        recoverBeforeDebit.recoverPending(account->testSave(e));
        check(!own(recoverBeforeDebit,e).isEmpty(),"Pending intent finalized after restart");
        JSONObject eSaved=new JSONObject(new String(Files.readAllBytes(new File(
            new File(new File(dir,"users"),e.accountId),"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
        check(eSaved.getLong("rmb")==99940,"Recovery charged once before debit checkpoint");
        GuildStore.Identity f=role("GGGGGGGGGGGGGGGGGGGGGG",808,"断点后");
        LocalSave fSave=testSave(f);
        String tx=pendingCreate(dir,f,"已扣费恢复");
        fSave.guildDebit(tx,f.roleId,"rmb",60);
        GuildStore recoverAfterDebit=new GuildStore(dir);
        recoverAfterDebit.recoverPending(account->testSave(f));
        check(!own(recoverAfterDebit,f).isEmpty(),"Charged intent finalized after restart");
        JSONObject fSaved=new JSONObject(new String(Files.readAllBytes(new File(
            new File(new File(dir,"users"),f.accountId),"offline_save_v1.json").toPath()),StandardCharsets.UTF_8));
        check(fSaved.getLong("rmb")==99940,"Recovery did not debit twice");
        GuildStore.Identity leader=role("IIIIIIIIIIIIIIIIIIIIII",909,"新会长");
        GuildStore.Identity applicant=role("JJJJJJJJJJJJJJJJJJJJJJ",1001,"新申请人");
        GuildStore regression=new GuildStore(dir);
        String newId=create(regression,leader,"成员资料回归");
        ProtoWire initialInfo=message(regression,"/guild/getUserGuild",leader,
            Collections.<String,String>emptyMap());
        ProtoWire common=ProtoWire.parse(initialInfo.data(2));
        check(common.number(8,0)>0,"President last online is present in original Guild field 8");
        check(common.number(24,-1)==1 && common.number(25,-1)==1 &&
            common.number(26,-1)==1 && common.number(28,-1)==0 &&
            common.number(29,-1)==0 && common.number(30,-1)==0,
            "Guild emblem, border, background and colors use the original field numbers");
        check(memberInfo(common,leader.roleId).number(3,0)==20,"Creator member level");
        GuildStore.Identity advanced=new GuildStore.Identity(leader.accountId,leader.roleId,
            "新会长改名",2,3,50,3456.5);
        ProtoWire refreshed=message(regression,"/guild/getUserGuild",advanced,
            Collections.<String,String>emptyMap());
        ProtoWire person=memberInfo(ProtoWire.parse(refreshed.data(2)),advanced.roleId);
        check(person.number(3,0)==50 && person.number(9,0)==2 && person.number(10,0)==3 &&
            "新会长改名".equals(utf8(person.data(2))),"Creator profile refreshed from live role");
        check(person.doubles(4).length==1 && person.doubles(4)[0]==3456.5 &&
            ProtoWire.parse(refreshed.data(2)).number(10,0)==3457,
            "Member CE uses original fixed64 double and guild total updates at once");
        regression.donateCharged(advanced,form("guildid",newId),testSave(advanced),true);
        java.util.List<ProtoWire> diamondLog=donationLogs(regression,advanced);
        check(diamondLog.size()==1&&diamondLog.get(0).number(4,0)==10081&&
            "新会长改名".equals(utf8(diamondLog.get(0).data(5))),
            "Original diamond donation history uses its separate dictionary string");
        ProtoWire guildList=message(regression,"/guild/search",advanced,form("content","成员资料回归"));
        ProtoWire listCard=ProtoWire.parse(guildList.data(1));
        check(listCard.number(8,0)==50 && "新会长改名".equals(utf8(listCard.data(7))),
            "List card uses refreshed president profile");
        regression=new GuildStore(dir);
        check(memberInfo(ProtoWire.parse(message(regression,"/guild/getUserGuild",advanced,
            Collections.<String,String>emptyMap()).data(2)),advanced.roleId).number(3,0)==50,
            "Refreshed creator level survives restart");
        regression.respond("/guild/apply",applicant,form("guildID",newId));
        ProtoWire requests=ProtoWire.parse(message(regression,"/guild/getUserGuild",applicant,
            Collections.<String,String>emptyMap()).data(1));
        ProtoWire requested=ProtoWire.parse(requests.data(3));
        check(requested.number(4,0)==1 && requested.number(5,0)==1 && requested.number(6,0)==1,
            "Pending guild card includes original emblem fields");
        GuildStore.Identity changedApplicant=new GuildStore.Identity(applicant.accountId,
            applicant.roleId,"新申请人改名",4,5,31);
        regression.respond("/guild/getUserGuild",changedApplicant,Collections.<String,String>emptyMap());
        common=ProtoWire.parse(message(regression,"/guild/getUserGuild",advanced,
            Collections.<String,String>emptyMap()).data(2));
        ProtoWire pending=null;
        for(ProtoWire.Field field:common.fields)if(field.number==12) {
            ProtoWire candidate=ProtoWire.parse(field.data);
            if(candidate.number(1,0)==applicant.roleId)pending=candidate;
        }
        check(pending!=null && pending.number(3,0)==31 && pending.number(9,0)==4 &&
            "新申请人改名".equals(utf8(pending.data(2))),"Application card refreshes role data");
        regression.respond("/guild/handleRequest",advanced,
            form("guildID",newId,"targetid",Long.toString(applicant.roleId),"allow","1"));
        check(memberCount(regression,changedApplicant)==2,"Applicant joins shared guild");
        File guildFile=new File(dir,"guild_state_v1.json");
        JSONObject state=new JSONObject(new String(Files.readAllBytes(guildFile.toPath()),StandardCharsets.UTF_8));
        JSONObject deployed=new JSONObject().put("roleId",advanced.roleId).put("servantId",12345);
        state.getJSONObject("guilds").getJSONObject(newId).getJSONObject("mercenaries")
            .put(Long.toString(advanced.roleId)+":12345",deployed);
        Files.write(guildFile.toPath(),(state.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        regression=new GuildStore(dir);
        ProtoWire user=ProtoWire.parse(message(regression,"/guild/getUserGuild",advanced,
            Collections.<String,String>emptyMap()).data(1));
        boolean numericMercenary=false;
        for(ProtoWire.Field field:user.fields)if(field.number==6)
            numericMercenary=field.type==0 && field.value==12345;
        check(numericMercenary,"UserGuild.Mercenaries must use int64 wire type");
        regression.respond("/guild/changePresident",advanced,
            form("guildID",newId,"targetid",Long.toString(applicant.roleId)));
        regression.respond("/guild/leaveGuild",advanced,form("guildID",newId));
        state=new JSONObject(new String(Files.readAllBytes(guildFile.toPath()),StandardCharsets.UTF_8));
        check(state.getJSONObject("guilds").getJSONObject(newId).getJSONObject("mercenaries")
            .length()==0,"Departed member cannot leave orphaned mercenaries");
        GuildStore.Identity supporter=role("KKKKKKKKKKKKKKKKKKKKKK",1111,"支援测试者");
        final GuildStore supportStore=new GuildStore(dir);
        String supportId=create(supportStore,supporter,"支援增补测试");
        JSONObject templates=new JSONObject();
        long[] servantIds={10010001L,10010101L,10010201L,10010301L};
        for(long servantId:servantIds)templates.put(Long.toString(servantId),
            LocalEconomy.encode(new ProtoWire().add(1,servantId)));
        JSONObject catalog=new JSONObject().put("servants",templates).put("items",new JSONObject());
        LocalSave supportSave=testSave(supporter);
        supportStore.sendMercenary(supporter,form("guildID",supportId,
            "svs","10010001,10010101","svwps","0,0"),supportSave,catalog);
        check(deployedIds(supportStore,supporter).size()==2,
            "First request garrisons two selected servants");
        supportStore.sendMercenary(supporter,form("guildID",supportId,
            "svs","10010201","svwps","0"),supportSave,catalog);
        java.util.Set<Long> expected=new java.util.HashSet<Long>();
        for(long servantId:new long[]{10010001L,10010101L,10010201L})expected.add(servantId);
        check(expected.equals(deployedIds(supportStore,supporter)),
            "Adding a third servant keeps the previous two garrisons");
        check(expected.equals(listedMercenaries(supportStore,supporter,supportId)),
            "Guild mercenary list exposes all three selected servants");
        supportStore.sendMercenary(supporter,form("guildID",supportId,
            "svs","10010201","svwps","0"),supportSave,catalog);
        check(expected.equals(deployedIds(supportStore,supporter)),
            "Retrying a servant request does not duplicate or replace the roster");
        rejected(GuildStore.Conflict.class,()->supportStore.sendMercenary(supporter,
            form("guildID",supportId,"svs","10010301","svwps","0"),supportSave,catalog));
        check(expected.equals(deployedIds(supportStore,supporter)),
            "Fourth servant rejection preserves all three existing garrisons");
        File supportGuildFile=new File(dir,"guild_state_v1.json");
        JSONObject rewardState=new JSONObject(new String(Files.readAllBytes(supportGuildFile.toPath()),
            StandardCharsets.UTF_8));
        rewardState.getJSONObject("guilds").getJSONObject(supportId)
            .getJSONObject("mercenaries").getJSONObject(supporter.roleId+":10010101")
            .put("garrisonTime",System.currentTimeMillis()/1000L-30L*3600L);
        rewardState.getJSONObject("guilds").getJSONObject(supportId)
            .getJSONObject("mercenaries").getJSONObject(supporter.roleId+":10010001")
            .put("garrisonTime",System.currentTimeMillis()/1000L-3601L);
        Files.write(supportGuildFile.toPath(),(rewardState.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        GuildStore rewardStore=new GuildStore(dir);
        check(listedTimeProfit(rewardStore,supporter,supportId,10010001L)==8 &&
            listedTimeProfit(rewardStore,supporter,supportId,10010101L)==200 &&
            listedTimeProfit(rewardStore,supporter,supportId,10010201L)==0,
            "Garrison earns eight coins per full hour and stops at 200");
        long beforeGold=new JSONObject(new String(Files.readAllBytes(new File(
            new File(new File(dir,"users"),supporter.accountId),"offline_save_v1.json").toPath()),
            StandardCharsets.UTF_8)).getLong("gold");
        rewardStore.recallMercenary(supporter,form("guildID",supportId,"sv","10010101"),supportSave);
        File supportSaveFile=new File(new File(new File(dir,"users"),supporter.accountId),
            "offline_save_v1.json");
        JSONObject credited=new JSONObject(new String(Files.readAllBytes(supportSaveFile.toPath()),
            StandardCharsets.UTF_8));
        check(credited.getLong("guildCurrency")==200 && credited.getLong("gold")==beforeGold,
            "Recall pays capped garrison coins without inventing hire commission");
        rewardStore.recallMercenary(supporter,form("guildID",supportId,"sv","10010101"),supportSave);
        credited=new JSONObject(new String(Files.readAllBytes(supportSaveFile.toPath()),
            StandardCharsets.UTF_8));
        check(credited.getLong("guildCurrency")==200,"Repeated recall cannot pay twice");
        rewardStore.sendMercenary(supporter,form("guildID",supportId,
            "svs","10010301","svwps","0"),supportSave,catalog);
        expected.remove(10010101L);expected.add(10010301L);
        check(expected.equals(deployedIds(new GuildStore(dir),supporter)),
            "Recall then refill persists the exact three selected servants");
        check(expected.equals(listedMercenaries(new GuildStore(dir),supporter,supportId)),
            "Guild mercenary list remains complete after restart");
        String recoveryTransaction=UUID.randomUUID().toString();
        supportSave.guildCredit(recoveryTransaction,supporter.roleId,8,0);
        rewardState=new JSONObject(new String(Files.readAllBytes(supportGuildFile.toPath()),
            StandardCharsets.UTF_8));
        rewardState.put("pendingRecall",new JSONObject().put("transaction",recoveryTransaction)
            .put("accountId",supporter.accountId).put("roleId",supporter.roleId)
            .put("guildId",supportId).put("servantId",10010001L)
            .put("guildCurrency",8).put("gold",0));
        Files.write(supportGuildFile.toPath(),(rewardState.toString()+"\n").getBytes(StandardCharsets.UTF_8));
        GuildStore recovered=new GuildStore(dir);
        recovered.recoverPending(accountId->supportSave);
        recovered.recoverPending(accountId->supportSave);
        credited=new JSONObject(new String(Files.readAllBytes(supportSaveFile.toPath()),
            StandardCharsets.UTF_8));
        check(credited.getLong("guildCurrency")==208 &&
            !deployedIds(recovered,supporter).contains(10010001L),
            "Interrupted recall finalizes once without duplicate currency");
        System.out.println("GuildSelfTest PASS: create/list/search/apply/approve/permissions/transfer/restart/concurrency");
    }
}
