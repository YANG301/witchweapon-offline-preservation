package com.codex.witchweapon;

import com.codex.witchweapon.host.AtomicFile;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Shared, account-authoritative guild data for the original Guildmod protocol. */
final class GuildStore {
    static final class Identity {
        final String accountId, name;
        final long roleId;
        final int head, headBox, level;
        final double ce;
        Identity(String accountId,long roleId,String name,int head,int headBox,int level) {
            this(accountId,roleId,name,head,headBox,level,0);
        }
        Identity(String accountId,long roleId,String name,int head,int headBox,int level,double ce) {
            this.accountId=accountId;this.roleId=roleId;this.name=name;
            this.head=head;this.headBox=headBox;this.level=level;this.ce=ce;
        }
    }
    static final class Invalid extends IOException { Invalid(String message){super(message);} }
    static final class Forbidden extends IOException { Forbidden(){super("Guild operation forbidden");} }
    static final class Conflict extends IOException { Conflict(String message){super(message);} }
    private static final int MAX_GUILDS=5000, MAX_MEMBERS=30, MAX_ADMINS=5, MAX_REQUESTS=100;
    private static final int GUILD_LEVEL=1, GUILD_POPULATION=30, GUILD_VITALITY_MAX=100000;
    private static final int DONATION_DAILY_LIMIT=1, GOLD_DONATION_COST=10000;
    private static final int MAX_GUILD_LOGS=100;
    private static final int MERCENARY_REWARD_PER_HOUR=8, MERCENARY_REWARD_CAP=200;
    private static final int MERCENARY_EMPLOY_DAILY_CAP=20000;
    private static final int DIAMOND_DONATION_COST=10, BUFF_VITALITY_COST=10000;
    private static final int BUFF_DURATION=86400, BUFF_COOLDOWN=28800;
    private static final SecureRandom RANDOM=new SecureRandom();
    private final AtomicFile file;
    private JSONObject state;
    interface SaveLookup { LocalSave get(String accountId) throws Exception; }

    GuildStore(File dataDir) throws Exception {
        file=new AtomicFile(new File(dataDir,"guild_state_v1.json"));
        if(file.getBaseFile().exists() || new File(file.getBaseFile()+".bak").exists()) {
            state=new JSONObject(new String(file.readFully(),StandardCharsets.UTF_8));
            validate(state);
        } else state=new JSONObject().put("version",1).put("guilds",new JSONObject())
            .put("users",new JSONObject());
    }
    static boolean handles(String path) {
        if(path.startsWith("/game/"))path=path.substring(5);
        switch(path) {
            case "/guild/getUserGuild": case "/guild/guilds": case "/guild/guildsbyce":
            case "/guild/guildsbymember": case "/guild/search": case "/guild/create":
            case "/guild/apply": case "/guild/handleRequest": case "/guild/leaveGuild":
            case "/guild/dissolveGuild": case "/guild/editNotice": case "/guild/editSlogan":
            case "/guild/kickOut": case "/guild/changePresident": case "/guild/editPrivilege":
            case "/guild/donateDiamond": case "/guild/donateGold": case "/guild/openBuff":
            case "/guild/mercenariesList": case "/guild/getModeEmployed":
            case "/guild/sendMercenary": case "/guild/recallMercenary": case "/guild/recallPresident":
                return true;
            default:return false;
        }
    }
    static boolean isReadOnly(String path) {
        if(path.startsWith("/game/"))path=path.substring(5);
        return path.equals("/guild/getUserGuild") || path.equals("/guild/guilds") ||
            path.equals("/guild/guildsbyce") || path.equals("/guild/guildsbymember") ||
            path.equals("/guild/search") || path.equals("/guild/mercenariesList") ||
            path.equals("/guild/getModeEmployed");
    }
    private static String key(long role){return Long.toString(role);}
    private static String argument(Map<String,String> args,String... keys) {
        for(String key:keys)if(args.containsKey(key))return args.get(key);
        return null;
    }
    private static String text(Map<String,String> args,int min,int max,String... names)throws Invalid {
        String value=argument(args,names);
        if(value==null || value.length()>512 || value.getBytes(StandardCharsets.UTF_8).length>1024 ||
            value.codePointCount(0,value.length())<min || value.codePointCount(0,value.length())>max ||
            !value.equals(value.trim()))throw new Invalid("Invalid guild text");
        for(int i=0;i<value.length();) {
            int code=value.codePointAt(i);
            if(Character.isISOControl(code) || Character.getType(code)==Character.FORMAT ||
                (code>=0xD800 && code<=0xDFFF))throw new Invalid("Invalid guild text");
            i+=Character.charCount(code);
        }
        return value;
    }
    private static String guildId(Map<String,String> args)throws Invalid {
        String id=argument(args,"guildID","guildid","guildId","id");
        if(id==null || !id.matches("g[0-9a-f]{24}"))throw new Invalid("Invalid guild ID");
        return id;
    }
    private static long target(Map<String,String> args)throws Invalid {
        String value=argument(args,"targetid","targetId","target");
        if(value==null || !value.matches("[1-9][0-9]{0,18}"))throw new Invalid("Invalid target role");
        try {return Long.parseLong(value);} catch(NumberFormatException e){throw new Invalid("Invalid target role");}
    }
    private static long number(Map<String,String> args,long fallback,String... names)throws Invalid {
        String value=argument(args,names);
        if(value==null || value.isEmpty())return fallback;
        try {
            long result=value.startsWith("0x") ? Long.parseLong(value.substring(2),16) : Long.parseLong(value);
            if(result<0 || result>Integer.MAX_VALUE)throw new NumberFormatException();
            return result;
        }catch(NumberFormatException e){throw new Invalid("Invalid guild emblem");}
    }
    private static String normalizedName(String name){
        return Normalizer.normalize(name,Normalizer.Form.NFKC).toLowerCase(Locale.ROOT);
    }
    private static JSONObject groups(JSONObject snapshot)throws Exception{return snapshot.getJSONObject("guilds");}
    private static JSONObject users(JSONObject snapshot)throws Exception {
        JSONObject users=snapshot.optJSONObject("users");
        if(users==null){users=new JSONObject();snapshot.put("users",users);}
        return users;
    }
    private static JSONObject user(JSONObject snapshot,Identity actor)throws Exception {
        JSONObject all=users(snapshot),record=all.optJSONObject(actor.accountId);
        if(record==null){record=new JSONObject();all.put(actor.accountId,record);}
        return record;
    }
    private static long chinaDay(long now){return (now+28800L)/86400L;}
    private static JSONObject requiredGuild(JSONObject snapshot,String id)throws Exception {
        JSONObject group=groups(snapshot).optJSONObject(id);
        if(group==null)throw new Conflict("Guild not found");
        return group;
    }
    private static String memberGuild(JSONObject snapshot,long role)throws Exception {
        String identity=key(role);JSONObject all=groups(snapshot);
        for(Iterator<String> it=all.keys();it.hasNext();) {
            String id=it.next();if(all.getJSONObject(id).getJSONObject("members").has(identity))return id;
        }
        return "";
    }
    private static void verifyAccount(JSONObject snapshot,Identity actor)throws Exception {
        String role=key(actor.roleId);JSONObject all=groups(snapshot);
        for(Iterator<String> it=all.keys();it.hasNext();) {
            JSONObject group=all.getJSONObject(it.next());
            for(String field:new String[]{"members","requests"}) {
                JSONObject entry=group.getJSONObject(field).optJSONObject(role);
                if(entry!=null && !actor.accountId.equals(entry.getString("accountId")))throw new Forbidden();
            }
        }
    }
    private static JSONObject member(JSONObject group,long role)throws Exception {
        JSONObject entry=group.getJSONObject("members").optJSONObject(key(role));
        if(entry==null)throw new Forbidden();
        return entry;
    }
    private static void president(JSONObject group,long role)throws Exception {
        if(group.getLong("president")!=role)throw new Forbidden();
    }
    private static void officer(JSONObject group,long role)throws Exception {
        if(member(group,role).getInt("privilege")<1)throw new Forbidden();
    }
    private static JSONObject identity(Identity actor,long now)throws Exception {
        if(actor==null || actor.roleId<1 || actor.name==null || actor.accountId==null ||
            actor.head<0 || actor.headBox<0)throw new Invalid("Role required");
        return new JSONObject().put("accountId",actor.accountId).put("roleId",actor.roleId)
            .put("name",actor.name).put("head",actor.head).put("headBox",actor.headBox)
            .put("level",actor.level).put("ce",actor.ce)
            .put("joinedAt",now).put("lastActive",now).put("privilege",0)
            .put("totalVitality",0).put("dailyVitality",0).put("donateCount",0)
            .put("donateDayCount",0).put("donateDay",-1);
    }
    private static void validate(JSONObject snapshot)throws Exception {
        if(snapshot.getInt("version")!=1)throw new IOException("Unsupported guild state version");
        JSONObject all=groups(snapshot);users(snapshot);
        JSONObject pending=snapshot.optJSONObject("pendingCreate");
        if(pending!=null) {
            if(!pending.getString("transaction").matches("[0-9a-f-]{36}") ||
                pending.getLong("roleId")<1 || pending.getString("accountId").isEmpty() ||
                pending.getJSONObject("guild").getLong("president")!=pending.getLong("roleId") ||
                all.has(pending.getJSONObject("guild").getString("id")))
                throw new IOException("Invalid pending guild creation");
        }
        JSONObject donation=snapshot.optJSONObject("pendingDonation");
        if(donation!=null) {
            if(!donation.optString("transaction").matches("[0-9a-f-]{36}") ||
                donation.optLong("roleId")<1 || donation.optString("accountId").isEmpty() ||
                !donation.optString("guildId").matches("g[0-9a-f]{24}") ||
                !("gold".equals(donation.optString("currency")) || "rmb".equals(donation.optString("currency"))) ||
                donation.optLong("cost")<1 || donation.optLong("vitality")<0 || donation.optLong("guildCoin")<0)
                throw new IOException("Invalid pending guild donation");
        }
        JSONObject recall=snapshot.optJSONObject("pendingRecall");
        if(recall!=null) {
            if(!recall.optString("transaction").matches("[0-9a-f-]{36}") ||
                recall.optLong("roleId")<1 || recall.optString("accountId").isEmpty() ||
                !recall.optString("guildId").matches("g[0-9a-f]{24}") ||
                recall.optLong("servantId")<1 ||
                recall.optLong("guildCurrency",-1)<0 || recall.optLong("guildCurrency")>MERCENARY_REWARD_CAP ||
                recall.optLong("gold",-1)<0 || recall.optLong("gold")>MERCENARY_EMPLOY_DAILY_CAP)
                throw new IOException("Invalid pending guild mercenary recall");
            JSONObject group=all.optJSONObject(recall.getString("guildId"));
            JSONObject deployed=group==null?null:group.optJSONObject("mercenaries");
            if(deployed==null || !deployed.has(key(recall.getLong("roleId"))+":"+
                recall.getLong("servantId")))throw new IOException("Pending mercenary is missing");
        }
        if((pending!=null?1:0)+(donation!=null?1:0)+(recall!=null?1:0)>1)
            throw new IOException("Multiple pending guild transactions");
        if(all.length()>MAX_GUILDS)throw new IOException("Too many guilds");
        Set<String> names=new HashSet<String>(), members=new HashSet<String>();
        for(Iterator<String> it=all.keys();it.hasNext();) {
            String id=it.next();JSONObject group=all.getJSONObject(id);
            if(!id.matches("g[0-9a-f]{24}") || !id.equals(group.getString("id")) ||
                !names.add(normalizedName(group.getString("name"))))throw new IOException("Invalid guild identity");
            JSONObject people=group.getJSONObject("members"),requests=group.getJSONObject("requests");
            if(people.length()<1 || people.length()>MAX_MEMBERS || requests.length()>MAX_REQUESTS ||
                !people.has(key(group.getLong("president"))))throw new IOException("Invalid guild membership");
            int admins=0;
            for(Iterator<String> p=people.keys();p.hasNext();) {
                String role=p.next();JSONObject entry=people.getJSONObject(role);
                if(!role.equals(key(entry.getLong("roleId"))) || !members.add(role) ||
                    entry.getInt("privilege")<0 || entry.getInt("privilege")>2 ||
                    entry.getString("accountId").isEmpty())throw new IOException("Invalid guild member");
                if(entry.getInt("privilege")==2 != role.equals(key(group.getLong("president"))))
                    throw new IOException("Invalid guild president");
                if(entry.getInt("privilege")==1)admins++;
            }
            if(admins>MAX_ADMINS)throw new IOException("Too many guild administrators");
        }
    }
    private void commit(JSONObject next)throws Exception {
        validate(next);
        FileOutputStream out=null;
        try {
            out=file.startWrite();out.write((next.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
            file.finishWrite(out);state=next;
        }catch(Exception e){if(out!=null)file.failWrite(out);throw e;}
    }
    /** Read-only, account-bound membership check for other server systems. */
    synchronized boolean isMember(String accountId,long roleId) {
        if(accountId==null || accountId.isEmpty() || roleId<1)return false;
        JSONObject all=state.optJSONObject("guilds");
        if(all==null)return false;
        String role=key(roleId);
        for(Iterator<String> it=all.keys();it.hasNext();) {
            JSONObject group=all.optJSONObject(it.next());
            JSONObject people=group==null?null:group.optJSONObject("members");
            JSONObject person=people==null?null:people.optJSONObject(role);
            if(person!=null)return roleId==person.optLong("roleId",-1) &&
                accountId.equals(person.optString("accountId",""));
        }
        return false;
    }

    /** Private gateway lookup for guild-chat authorization; never creates a save. */
    synchronized String membership(Identity actor)throws Exception {
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        verifyAccount(state,actor);
        String id=memberGuild(state,actor.roleId);
        int privilege=-1;
        if(!id.isEmpty())privilege=member(requiredGuild(state,id),actor.roleId).getInt("privilege");
        return new JSONObject().put("version",1).put("roleId",key(actor.roleId))
            .put("guildId",id).put("conversationId",id.isEmpty()?"":"xinfengzhou-"+id)
            .put("privilege",privilege).toString();
    }
    /** Complete a durable guild intent before the HTTP listener starts. */
    synchronized void recoverPending(SaveLookup lookup)throws Exception {
        JSONObject pending=state.optJSONObject("pendingCreate");
        if(pending!=null) {
            LocalSave save=lookup.get(pending.getString("accountId"));
            synchronized(save) {
                save.guildDebit(pending.getString("transaction"),pending.getLong("roleId"),"rmb",60);
                finishPending();
            }
            return;
        }
        JSONObject donation=state.optJSONObject("pendingDonation");
        if(donation!=null) {
            LocalSave save=lookup.get(donation.getString("accountId"));
            synchronized(save) {
                save.guildDebit(donation.getString("transaction"),donation.getLong("roleId"),
                    donation.getString("currency"),donation.getLong("cost"));
                finishPendingDonation(save);
            }
            return;
        }
        JSONObject recall=state.optJSONObject("pendingRecall");
        if(recall!=null) {
            LocalSave save=lookup.get(recall.getString("accountId"));
            synchronized(save) {
                save.guildCredit(recall.getString("transaction"),recall.getLong("roleId"),
                    recall.getLong("guildCurrency"),recall.getLong("gold"));
                finishPendingRecall();
            }
        }
    }
    /** Backfill existing members once at startup; subsequent visits refresh their own snapshot. */
    synchronized void refreshKnownMemberPower(SaveLookup lookup,JSONObject catalog)throws Exception {
        JSONObject next=new JSONObject(state.toString());
        boolean changed=false;
        JSONObject all=groups(next);
        for(Iterator<String> guilds=all.keys();guilds.hasNext();) {
            JSONObject group=all.getJSONObject(guilds.next());
            JSONObject members=group.getJSONObject("members");
            for(Iterator<String> ids=members.keys();ids.hasNext();) {
                JSONObject person=members.getJSONObject(ids.next());
                long power;
                try{power=lookup.get(person.getString("accountId"))
                    .guildCombatEffectiveness(catalog);}
                catch(IOException missing){continue;}
                if(Double.compare(person.optDouble("ce",0),(double)power)!=0) {
                    person.put("ce",power);group.put("lastCETime",System.currentTimeMillis()/1000);
                    changed=true;
                }
            }
        }
        if(changed)commit(next);
    }
    /** Guild state and the charged player's save are joined by an idempotent write-ahead intent. */
    synchronized byte[] createCharged(Identity actor,Map<String,String> args,LocalSave save)throws Exception {
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        verifyAccount(state,actor);
        if(hasPendingTransaction())
            throw new Conflict("Guild transaction recovery required");
        synchronized(save) {
            // Holding this LocalSave monitor excludes every other player-balance mutation
            // between the funds check, durable intent, and idempotent debit.
            save.guildRequireFunds(actor.roleId,"rmb",60);
            JSONObject next=new JSONObject(state.toString());
            JSONObject group=prepareCreate(next,actor,args,System.currentTimeMillis()/1000);
            String transaction=UUID.randomUUID().toString();
            next.put("pendingCreate",new JSONObject().put("transaction",transaction)
                .put("accountId",actor.accountId).put("roleId",actor.roleId).put("guild",group));
            commit(next);
            save.guildDebit(transaction,actor.roleId,"rmb",60);
            finishPending();
            return userInfo(state,actor);
        }
    }
    private void finishPending()throws Exception {
        JSONObject pending=state.getJSONObject("pendingCreate");
        JSONObject next=new JSONObject(state.toString());
        JSONObject guild=pending.getJSONObject("guild");
        groups(next).put(guild.getString("id"),new JSONObject(guild.toString()));
        clearRequests(next,pending.getLong("roleId"));
        next.remove("pendingCreate");
        commit(next);
    }
    private boolean hasPendingTransaction() {
        return state.optJSONObject("pendingCreate")!=null || state.optJSONObject("pendingDonation")!=null ||
            state.optJSONObject("pendingRecall")!=null;
    }
    /** Donation is a daily, idempotent account-to-guild transfer with a durable recovery intent. */
    synchronized byte[] donateCharged(Identity actor,Map<String,String> args,LocalSave save,
        boolean diamond)throws Exception {
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        verifyAccount(state,actor);
        if(hasPendingTransaction())throw new Conflict("Guild transaction recovery required");
        String id=guildId(args), own=memberGuild(state,actor.roleId);
        if(!id.equals(own))throw new Forbidden();
        JSONObject group=requiredGuild(state,id), person=member(group,actor.roleId);
        long now=System.currentTimeMillis()/1000, day=chinaDay(now);
        if(person.optLong("donateDay",-1)==day && person.optInt("donateDayCount",0)>=DONATION_DAILY_LIMIT) {
            String lastType=person.optString("lastDonateType","");
            if(lastType.equals(diamond?"diamond":"gold"))return userInfo(state,actor);
            throw new Conflict("Daily guild donation limit");
        }
        long vitality=diamond?200:100, guildCoin=diamond?400:200;
        if(group.optLong("vitality",0)+vitality>GUILD_VITALITY_MAX)
            throw new Conflict("Guild vitality capacity reached");
        String currency=diamond?"rmb":"gold";long cost=diamond?DIAMOND_DONATION_COST:GOLD_DONATION_COST;
        synchronized(save) {
            save.guildRequireFunds(actor.roleId,currency,cost);
            JSONObject next=new JSONObject(state.toString());
            String transaction=UUID.randomUUID().toString();
            next.put("pendingDonation",new JSONObject().put("transaction",transaction)
                .put("accountId",actor.accountId).put("roleId",actor.roleId).put("guildId",id)
                .put("currency",currency).put("cost",cost).put("vitality",vitality)
                .put("guildCoin",guildCoin).put("time",now).put("day",day));
            commit(next);
            save.guildDebit(transaction,actor.roleId,currency,cost);
            finishPendingDonation(save);
        }
        return userInfo(state,actor);
    }
    private void finishPendingDonation(LocalSave save)throws Exception {
        JSONObject pending=state.getJSONObject("pendingDonation");
        JSONObject next=new JSONObject(state.toString());
        JSONObject group=requiredGuild(next,pending.getString("guildId"));
        JSONObject person=member(group,pending.getLong("roleId"));
        long day=pending.getLong("day"), vitality=pending.getLong("vitality");
        if(person.optLong("donateDay",-1)!=day || person.optInt("donateDayCount",0)<DONATION_DAILY_LIMIT) {
            person.put("donateDay",day).put("donateDayCount",1)
                .put("donateCount",person.optInt("donateCount",0)+1)
                .put("lastDonate",pending.getLong("time"))
                .put("lastDonateType",pending.getString("currency").equals("rmb")?"diamond":"gold");
            if(person.optLong("totalVitality",0)>Long.MAX_VALUE-vitality)
                throw new IOException("Guild donation vitality overflow");
            person.put("totalVitality",person.optLong("totalVitality",0)+vitality)
                .put("dailyVitality",vitality);
            group.put("vitality",group.optLong("vitality",0)+vitality)
                .put("guildCoin",group.optLong("guildCoin",0)+pending.getLong("guildCoin"));
            appendDonationLog(group,person,pending);
            JSONObject user=users(next).optJSONObject(pending.getString("accountId"));
            if(user==null){user=new JSONObject();users(next).put(pending.getString("accountId"),user);}
            user.put("donateDay",day).put("donateDayCount",1)
                .put("donateCount",user.optInt("donateCount",0)+1)
                .put("lastDonate",pending.getLong("time"))
                .put("lastDonateType",pending.getString("currency").equals("rmb")?"diamond":"gold")
                .put("totalVitality",user.optLong("totalVitality",0)+vitality)
                .put("dailyVitality",vitality);
        }
        // The intent remains durable until both guild and account task state
        // have committed. Recovery can replay the capped one-per-day objective.
        save.guildTaskCompleted(pending.getLong("roleId"),true,pending.getLong("time"));
        next.remove("pendingDonation");commit(next);
    }
    private static void appendDonationLog(JSONObject group,JSONObject person,
                                           JSONObject donation)throws Exception {
        // Guildmod.Guild.Logs[17] contains GuildLog(ID=1,Time=2,StringID=4,
        // Vars=5).  Original dictionary 10080/10081 interpolates @1@ as the
        // member name for gold/diamond donations.  Record only after the
        // durable debit intent has been finalized, so replay cannot duplicate it.
        long previous=group.optLong("lastLogId",0);
        if(previous<0 || previous>=Integer.MAX_VALUE)
            throw new IOException("Guild log sequence exhausted");
        long id=previous+1;
        JSONArray existing=group.optJSONArray("logs");
        JSONArray next=new JSONArray();
        int first=existing==null?0:Math.max(0,existing.length()-(MAX_GUILD_LOGS-1));
        if(existing!=null)for(int i=first;i<existing.length();i++)next.put(existing.getJSONObject(i));
        next.put(new JSONObject().put("id",id).put("time",donation.getLong("time"))
            .put("stringId",donation.getString("currency").equals("rmb")?10081:10080)
            .put("name",person.getString("name")));
        group.put("lastLogId",id).put("logs",next);
    }
    private static List<Long> idList(String raw,String label,boolean allowZero)throws Invalid {
        if(raw==null || raw.isEmpty())return new ArrayList<Long>();
        String[] parts=raw.split("[|,;]",-1);
        if(parts.length>3)throw new Invalid("Too many guild mercenaries");
        ArrayList<Long> result=new ArrayList<Long>();Set<Long> seen=new HashSet<Long>();
        for(String part:parts) {
            if(!part.matches(allowZero?"(?:0|[1-9][0-9]{0,18})":"[1-9][0-9]{0,18}"))
                throw new Invalid("Invalid "+label);
            try {
                long id=Long.parseLong(part);
                if(id!=0 && !seen.add(id))throw new Invalid("Duplicate "+label);
                result.add(id);
            }catch(NumberFormatException e){throw new Invalid("Invalid "+label);}
        }
        return result;
    }
    private static long mercenaryTimeProfit(JSONObject entry,long now) {
        long start=entry.optLong("garrisonTime",now);
        if(start<=0 || now<=start)return 0;
        long hours=Math.min(MERCENARY_REWARD_CAP/MERCENARY_REWARD_PER_HOUR,(now-start)/3600L);
        return hours*MERCENARY_REWARD_PER_HOUR;
    }
    /** Deploy only servants and weapons that are present in the owner's authoritative save. */
    synchronized byte[] sendMercenary(Identity actor,Map<String,String> args,LocalSave save,
        JSONObject catalog)throws Exception {
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        if(hasPendingTransaction())throw new Conflict("Guild transaction recovery required");
        verifyAccount(state,actor);
        String id=guildId(args), own=memberGuild(state,actor.roleId);
        if(!id.equals(own))throw new Forbidden();
        JSONObject group=requiredGuild(state,id);member(group,actor.roleId);
        List<Long> servantIds=idList(argument(args,"svs","servants","servantids"),"servant IDs",false);
        List<Long> weaponIds=idList(argument(args,"svwps","weapons","weaponids"),"weapon IDs",true);
        if(servantIds.isEmpty() || servantIds.size()>3)throw new Invalid("Select one to three servants");
        if(!weaponIds.isEmpty() && weaponIds.size()!=servantIds.size())
            throw new Invalid("Servant and weapon selections do not match");
        if(weaponIds.isEmpty())for(int i=0;i<servantIds.size();i++)weaponIds.add(0L);
        JSONObject owned=save.guildOwnedServants(catalog), next=new JSONObject(state.toString());
        JSONObject updated=requiredGuild(next,id), mercenaries=updated.optJSONObject("mercenaries");
        if(mercenaries==null)mercenaries=new JSONObject();
        String prefix=key(actor.roleId)+":";
        int deployed=0, additional=0;
        for(Iterator<String> it=mercenaries.keys();it.hasNext();) {
            if(it.next().startsWith(prefix))deployed++;
        }
        for(long servantId:servantIds)if(!mercenaries.has(prefix+servantId))additional++;
        if(deployed+additional>3)throw new Conflict("Guild mercenary slots full");
        long now=System.currentTimeMillis()/1000;
        for(int i=0;i<servantIds.size();i++) {
            long servantId=servantIds.get(i), weaponId=weaponIds.get(i);
            Object saved=owned.opt(String.valueOf(servantId));
            if(!(saved instanceof String))throw new Forbidden();
            ProtoWire servant=LocalEconomy.decode((String)saved);
            if(servant.number(1,0)!=servantId)throw new Forbidden();
            ProtoWire weapon=null;
            if(weaponId>0)for(ProtoWire.Field field:servant.fields)if(field.number==13 && field.type==2) {
                ProtoWire candidate=ProtoWire.parse(field.data);
                if(candidate.number(1,0)==weaponId){weapon=candidate;break;}
            }
            if(weaponId>0 && weapon==null)throw new Forbidden();
            String mapKey=prefix+servantId;
            JSONObject old=mercenaries.optJSONObject(mapKey);
            JSONObject entry=new JSONObject().put("roleId",actor.roleId).put("roleName",actor.name)
                .put("servantId",servantId).put("servantInfo",com.codex.witchweapon.host.Base64.encodeToString(servant.bytes(),2))
                .put("garrisonTime",old==null?now:old.optLong("garrisonTime",now))
                .put("curImage",servant.number(18,1))
                .put("employCount",old==null?0:old.optInt("employCount",0))
                .put("employDailyCount",old==null?0:old.optInt("employDailyCount",0))
                .put("timeProfit",0).put("employProfit",old==null?0:old.optInt("employProfit",0))
                .put("employDailyProfit",old==null?0:old.optInt("employDailyProfit",0))
                .put("lastEmployTime",old==null?0:old.optLong("lastEmployTime",0));
            if(weapon!=null)entry.put("weaponInfo",com.codex.witchweapon.host.Base64.encodeToString(weapon.bytes(),2));
            mercenaries.put(mapKey,entry);
        }
        updated.put("mercenaries",mercenaries);commit(next);
        save.guildTaskCompleted(actor.roleId,false,now);
        return userInfo(state,actor);
    }
    synchronized byte[] recallMercenary(Identity actor,Map<String,String> args,LocalSave save)throws Exception {
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        if(hasPendingTransaction())throw new Conflict("Guild transaction recovery required");
        verifyAccount(state,actor);
        String id=guildId(args), own=memberGuild(state,actor.roleId);
        if(!id.equals(own))throw new Forbidden();
        JSONObject group=requiredGuild(state,id);member(group,actor.roleId);
        String raw=argument(args,"sv","servant","servantid");
        if(raw==null || !raw.matches("[1-9][0-9]{0,18}"))throw new Invalid("Invalid servant ID");
        long servantId;
        try{servantId=Long.parseLong(raw);}catch(NumberFormatException e){throw new Invalid("Invalid servant ID");}
        JSONObject deployed=group.optJSONObject("mercenaries");
        JSONObject entry=deployed==null?null:deployed.optJSONObject(key(actor.roleId)+":"+servantId);
        if(entry==null)return userInfo(state,actor);
        long now=System.currentTimeMillis()/1000L;
        long guildCurrency=mercenaryTimeProfit(entry,now);
        long gold=Math.max(0,Math.min(MERCENARY_EMPLOY_DAILY_CAP,entry.optLong("employProfit",0)));
        synchronized(save) {
            JSONObject next=new JSONObject(state.toString());
            next.put("pendingRecall",new JSONObject().put("transaction",UUID.randomUUID().toString())
                .put("accountId",actor.accountId).put("roleId",actor.roleId)
                .put("guildId",id).put("servantId",servantId)
                .put("guildCurrency",guildCurrency).put("gold",gold));
            commit(next);
            JSONObject pending=state.getJSONObject("pendingRecall");
            save.guildCredit(pending.getString("transaction"),actor.roleId,guildCurrency,gold);
            finishPendingRecall();
        }
        return userInfo(state,actor);
    }
    private void finishPendingRecall()throws Exception {
        JSONObject pending=state.getJSONObject("pendingRecall");
        JSONObject next=new JSONObject(state.toString());
        JSONObject group=requiredGuild(next,pending.getString("guildId"));
        JSONObject mercenaries=group.getJSONObject("mercenaries");
        String mercenary=key(pending.getLong("roleId"))+":"+pending.getLong("servantId");
        if(mercenaries.remove(mercenary)==null)throw new IOException("Pending mercenary is missing");
        next.remove("pendingRecall");commit(next);
    }
    private static JSONObject prepareCreate(JSONObject snapshot,Identity actor,Map<String,String> args,long now)throws Exception {
        JSONObject all=groups(snapshot);
        if(!memberGuild(snapshot,actor.roleId).isEmpty())throw new Conflict("Already in a guild");
        if(now-user(snapshot,actor).optLong("leftAt",0)<28800L)
            throw new Conflict("Guild departure cooldown");
        if(all.length()>=MAX_GUILDS)throw new Conflict("Guild capacity reached");
        String name=text(args,2,24,"guildName","name","guildname");
        String slogan=text(args,0,100,"guildSlogan","slogan");
        String canonical=normalizedName(name);
        for(Iterator<String> it=all.keys();it.hasNext();)if(canonical.equals(
            normalizedName(all.getJSONObject(it.next()).getString("name"))))
            throw new Conflict("Guild name exists");
        byte[] random=new byte[12];RANDOM.nextBytes(random);StringBuilder id=new StringBuilder("g");
        for(byte value:random)id.append(String.format(Locale.ROOT,"%02x",value&255));
        String guild=id.toString();if(all.has(guild))throw new Conflict("Guild ID collision");
        JSONObject leader=identity(actor,now).put("privilege",2);
        return new JSONObject().put("id",guild).put("name",name).put("slogan",slogan)
            .put("notice","").put("president",actor.roleId).put("presidentLastOnline",now)
            .put("lastCETime",now).put("createdAt",now)
            .put("members",new JSONObject().put(key(actor.roleId),leader))
            .put("requests",new JSONObject()).put("level",GUILD_LEVEL).put("maxUsers",GUILD_POPULATION)
            .put("vitality",0).put("guildCoin",0).put("buff",0).put("lastBuffTime",0)
            .put("mercenaries",new JSONObject()).put("emblem",number(args,1,"emblem"))
            .put("emblemBorder",number(args,1,"emblemborder"))
            .put("emblemBackground",number(args,1,"emblembackground"))
            .put("emblemColor",number(args,0,"emblemcolor","emblemColor"))
            .put("emblemBorderColor",number(args,0,"emblembordercolor","emblemBorderColor"))
            .put("emblemBackgroundColor",number(args,0,"emblembackgroundcolor","emblemBackgroundColor"));
    }
    synchronized byte[] respond(String route,Identity actor,Map<String,String> args)throws Exception {
        if(route.startsWith("/game/"))route=route.substring(5);
        if(!handles(route))throw new Invalid("Unsupported guild route");
        if(actor==null || actor.roleId<1)throw new Invalid("Role required");
        verifyAccount(state,actor);
        if(isReadOnly(route)) {
            if(route.equals("/guild/getUserGuild")) {
                refreshPlayerActivity(actor,System.currentTimeMillis()/1000);
                return userInfo(state,actor);
            }
            if(route.equals("/guild/mercenariesList"))return mercenaries(state,args);
            if(route.equals("/guild/getModeEmployed"))return new ProtoWire().bytes();
            return list(state,route,args);
        }
        if(hasPendingTransaction())throw new Conflict("Guild transaction recovery required");
        JSONObject next=new JSONObject(state.toString());
        boolean changed=mutate(next,route,actor,args,System.currentTimeMillis()/1000);
        if(changed)commit(next);
        return userInfo(state,actor);
    }
    private static boolean refreshIdentity(JSONObject entry,Identity actor,long now)throws Exception {
        boolean changed=false;
        if(!entry.getString("name").equals(actor.name)) {entry.put("name",actor.name);changed=true;}
        if(entry.optInt("head",0)!=actor.head) {entry.put("head",actor.head);changed=true;}
        if(entry.optInt("headBox",0)!=actor.headBox) {entry.put("headBox",actor.headBox);changed=true;}
        if(entry.optInt("level",0)!=actor.level) {entry.put("level",actor.level);changed=true;}
        if(Double.compare(entry.optDouble("ce",0),actor.ce)!=0) {
            entry.put("ce",actor.ce);changed=true;
        }
        if(now-entry.optLong("lastActive",0)>=60) {entry.put("lastActive",now);changed=true;}
        return changed;
    }
    /** Keep the member and pending-application cards in sync with the authoritative role save. */
    private void refreshPlayerActivity(Identity actor,long now)throws Exception {
        JSONObject next=new JSONObject(state.toString());
        String own=memberGuild(next,actor.roleId);
        boolean changed=false;
        if(!own.isEmpty()) {
            JSONObject group=requiredGuild(next,own);
            if(Double.compare(member(group,actor.roleId).optDouble("ce",0),actor.ce)!=0)
                group.put("lastCETime",now);
            changed=refreshIdentity(member(group,actor.roleId),actor,now);
            if(group.getLong("president")==actor.roleId) {
                if(now-group.optLong("presidentLastOnline",0)>=60) {
                    group.put("presidentLastOnline",now);changed=true;
                }
                if(group.optLong("recallTime",0)!=0 || group.optLong("recallMember",0)!=0) {
                    group.put("recallTime",0).put("recallMember",0);changed=true;
                }
            } else {
                long recallTime=group.optLong("recallTime",0), candidate=group.optLong("recallMember",0);
                if(recallTime>0 && now>=recallTime+259200L && group.optLong("presidentLastOnline",0)>0 &&
                    now-group.getLong("presidentLastOnline")>=604800L && group.getJSONObject("members").has(key(candidate))) {
                    member(group,group.getLong("president")).put("privilege",0);
                    member(group,candidate).put("privilege",2);
                    group.put("president",candidate).put("presidentLastOnline",now)
                        .put("recallTime",0).put("recallMember",0);
                    changed=true;
                }
            }
        }
        JSONObject all=groups(next);
        for(Iterator<String> it=all.keys();it.hasNext();) {
            JSONObject request=all.getJSONObject(it.next()).getJSONObject("requests").optJSONObject(key(actor.roleId));
            if(request!=null)changed=refreshIdentity(request,actor,now)||changed;
        }
        if(changed)commit(next);
    }
    private boolean mutate(JSONObject snapshot,String route,Identity actor,Map<String,String> args,long now)throws Exception {
        JSONObject all=groups(snapshot);String own=memberGuild(snapshot,actor.roleId);
        switch(route) {
            case "/guild/create": throw new Conflict("Guild creation requires charged transaction");
            case "/guild/apply": {
                if(!own.isEmpty())throw new Conflict("Already in a guild");
                JSONObject actorState=user(snapshot,actor);
                if(now-actorState.optLong("leftAt",0)<28800L)
                    throw new Conflict("Guild departure cooldown");
                JSONObject group=requiredGuild(snapshot,guildId(args));
                JSONObject requests=group.getJSONObject("requests");String role=key(actor.roleId);
                // The original /guild/apply request is an idempotent application call.
                // A repeated tap must not silently cancel the player's pending request.
                if(requests.has(role))return false;
                long day=chinaDay(now);
                int sent=actorState.optLong("applyDay",-1)==day?actorState.optInt("applyCount",0):0;
                if(sent>=3)throw new Conflict("Daily guild application limit");
                if(requests.length()>=MAX_REQUESTS)throw new Conflict("Too many applications");
                if(group.getJSONObject("members").length()>=MAX_MEMBERS)throw new Conflict("Guild full");
                actorState.put("applyDay",day).put("applyCount",sent+1);
                requests.put(role,identity(actor,now));return true;
            }
            case "/guild/handleRequest": {
                JSONObject group=requiredGuild(snapshot,guildId(args));officer(group,actor.roleId);
                long role=target(args);JSONObject requests=group.getJSONObject("requests");
                JSONObject request=requests.optJSONObject(key(role));
                if(request==null)throw new Conflict("Application not found");
                String decision=argument(args,"allow");
                if(!"0".equals(decision) && !"1".equals(decision))throw new Invalid("Invalid decision");
                if("1".equals(decision)) {
                    if(!memberGuild(snapshot,role).isEmpty())throw new Conflict("Applicant already joined");
                    if(group.getJSONObject("members").length()>=MAX_MEMBERS)throw new Conflict("Guild full");
                    request.put("joinedAt",now).put("privilege",0);
                    group.getJSONObject("members").put(key(role),request);
                    JSONObject applicant=users(snapshot).optJSONObject(request.getString("accountId"));
                    if(applicant==null){applicant=new JSONObject();users(snapshot).put(request.getString("accountId"),applicant);}
                    applicant.put("joinCount",applicant.optInt("joinCount",0)+1);
                    clearRequests(snapshot,role);
                } else requests.remove(key(role));
                return true;
            }
            case "/guild/leaveGuild": {
                JSONObject group=requiredGuild(snapshot,guildId(args));member(group,actor.roleId);
                if(group.getLong("president")==actor.roleId)throw new Conflict("Transfer leadership first");
                removeMercenaries(group,actor.roleId);
                group.getJSONObject("members").remove(key(actor.roleId));
                user(snapshot,actor).put("leftAt",now);return true;
            }
            case "/guild/dissolveGuild": {
                String id=guildId(args);JSONObject group=requiredGuild(snapshot,id);president(group,actor.roleId);
                if(group.getJSONObject("members").length()!=1)throw new Conflict("Members remain");
                all.remove(id);user(snapshot,actor).put("leftAt",now);return true;
            }
            case "/guild/editNotice": case "/guild/editSlogan": {
                JSONObject group=requiredGuild(snapshot,guildId(args));officer(group,actor.roleId);
                String field=route.equals("/guild/editNotice")?"notice":"slogan";
                String value=text(args,0,field.equals("notice")?300:100,"content",field);
                if(value.equals(group.getString(field)))return false;
                group.put(field,value);return true;
            }
            case "/guild/kickOut": {
                JSONObject group=requiredGuild(snapshot,guildId(args));officer(group,actor.roleId);
                long role=target(args);JSONObject victim=member(group,role);
                if(role==actor.roleId || victim.getInt("privilege")>=member(group,actor.roleId).getInt("privilege"))
                    throw new Forbidden();
                removeMercenaries(group,role);
                group.getJSONObject("members").remove(key(role));
                JSONObject victimState=users(snapshot).optJSONObject(victim.getString("accountId"));
                if(victimState==null){victimState=new JSONObject();users(snapshot).put(victim.getString("accountId"),victimState);}
                victimState.put("leftAt",now);return true;
            }
            case "/guild/changePresident": {
                JSONObject group=requiredGuild(snapshot,guildId(args));president(group,actor.roleId);
                long role=target(args);if(role==actor.roleId)return false;
                JSONObject promoted=member(group,role);
                member(group,actor.roleId).put("privilege",0);
                promoted.put("privilege",2);group.put("president",role)
                    .put("presidentLastOnline",now).put("recallTime",0).put("recallMember",0);return true;
            }
            case "/guild/editPrivilege": {
                JSONObject group=requiredGuild(snapshot,guildId(args));president(group,actor.roleId);
                long role=target(args);if(role==actor.roleId)throw new Forbidden();
                // The original GuildPrivilege enum is a bit mask: Member=1,
                // Admin=2, President=4. EditPrivilege sends targetposition,
                // not our internal 0/1 member/admin representation.
                String requested=argument(args,"targetposition");
                if(!"1".equals(requested) && !"2".equals(requested))
                    throw new Invalid("Invalid guild position");
                JSONObject target=member(group,role);int privilege="2".equals(requested)?1:0;
                if(target.getInt("privilege")==privilege)return false;
                if(privilege==1) {
                    int admins=0;JSONObject people=group.getJSONObject("members");
                    for(Iterator<String> it=people.keys();it.hasNext();)
                        if(people.getJSONObject(it.next()).getInt("privilege")==1)admins++;
                    if(admins>=MAX_ADMINS)throw new Conflict("Administrator capacity reached");
                }
                target.put("privilege",privilege);return true;
            }
            case "/guild/openBuff": {
                JSONObject group=requiredGuild(snapshot,guildId(args));officer(group,actor.roleId);
                long buff=number(args,0,"buffserial","buffSerial","buff","serial");
                if(buff<1 || buff>6)throw new Invalid("Invalid guild buff");
                long last=group.optLong("lastBuffTime",0);
                if(last>0 && now<last+BUFF_DURATION+BUFF_COOLDOWN)
                    throw new Conflict("Guild buff is in cooldown");
                if(group.optLong("vitality",0)<BUFF_VITALITY_COST)
                    throw new Conflict("Insufficient guild vitality");
                group.put("vitality",group.getLong("vitality")-BUFF_VITALITY_COST)
                    .put("buff",buff).put("lastBuffTime",now);
                return true;
            }
            case "/guild/recallPresident": {
                JSONObject group=requiredGuild(snapshot,guildId(args));
                member(group,actor.roleId);
                if(group.getLong("president")==actor.roleId)return false;
                long inactive=group.optLong("presidentLastOnline",group.optLong("createdAt",now));
                if(now-inactive<604800L)throw new Conflict("President impeachment requires 7 days offline");
                long currentRecall=group.optLong("recallTime",0);
                if(currentRecall==0) {
                    group.put("recallTime",now).put("recallMember",actor.roleId);
                    return true;
                }
                if(group.optLong("recallMember",0)!=actor.roleId)
                    throw new Conflict("Another member started the president recall");
                if(now<currentRecall+259200L)throw new Conflict("President recall is still in progress");
                JSONObject successor=member(group,actor.roleId);
                member(group,group.getLong("president")).put("privilege",0);
                successor.put("privilege",2);group.put("president",actor.roleId)
                    .put("presidentLastOnline",now).put("recallTime",0).put("recallMember",0);
                return true;
            }
            case "/guild/sendMercenary":
                throw new Conflict("Mercenary roster synchronization is not available for this account yet");
            case "/guild/recallMercenary":
                throw new Conflict("Mercenary roster synchronization is not available for this account yet");
            default:throw new Invalid("Unsupported guild route");
        }
    }
    private static void clearRequests(JSONObject snapshot,long role)throws Exception {
        JSONObject all=groups(snapshot);for(Iterator<String> it=all.keys();it.hasNext();)
            all.getJSONObject(it.next()).getJSONObject("requests").remove(key(role));
    }
    private static void removeMercenaries(JSONObject group,long role)throws Exception {
        JSONObject deployed=group.optJSONObject("mercenaries");
        if(deployed==null)return;
        String prefix=key(role)+":";
        ArrayList<String> removed=new ArrayList<String>();
        for(Iterator<String> it=deployed.keys();it.hasNext();) {
            String id=it.next();if(id.startsWith(prefix))removed.add(id);
        }
        for(String id:removed)deployed.remove(id);
    }
    private static ProtoWire simple(JSONObject person,long now)throws Exception {
        return new ProtoWire().add(1,person.getLong("roleId")).add(2,person.getString("name").getBytes(StandardCharsets.UTF_8))
            .add(3,person.optInt("level",1)).addDouble(4,person.optDouble("ce",0))
            .add(5,person.optLong("lastActive",person.optLong("joinedAt",0)))
            .add(6,person.optLong("joinedAt",0)).add(7,person.optLong("totalVitality",0))
            .add(8,person.optLong("donateDay",-1)==chinaDay(now)?person.optLong("dailyVitality",0):0)
            .add(9,person.optInt("head",1))
            .add(10,person.optInt("headBox",1));
    }
    private static long combatTotal(JSONObject group)throws Exception {
        JSONObject members=group.getJSONObject("members");
        double sum=0;
        for(Iterator<String> it=members.keys();it.hasNext();) {
            double value=members.getJSONObject(it.next()).optDouble("ce",0);
            if(Double.isFinite(value) && value>0)sum+=value;
        }
        return Math.round(Math.min(sum,Long.MAX_VALUE));
    }
    private static int combatAverage(JSONObject group)throws Exception {
        int count=group.getJSONObject("members").length();
        return count==0?0:(int)Math.min(Integer.MAX_VALUE,combatTotal(group)/count);
    }
    private static ProtoWire guild(JSONObject group,long now)throws Exception {
        long buff=group.optLong("buff",0), buffTime=group.optLong("lastBuffTime",0);
        if(buffTime<=0 || now>=buffTime+BUFF_DURATION)buff=0;
        ProtoWire out=new ProtoWire().add(1,group.getString("id").getBytes(StandardCharsets.UTF_8))
            .add(2,group.getLong("president"))
            .add(5,group.getString("name").getBytes(StandardCharsets.UTF_8))
            .add(6,group.getString("slogan").getBytes(StandardCharsets.UTF_8))
            .add(8,group.optLong("presidentLastOnline",group.optLong("createdAt",0)))
            .add(9,group.getString("notice").getBytes(StandardCharsets.UTF_8))
            .add(10,combatTotal(group))
            .add(11,group.optInt("maxUsers",GUILD_POPULATION)).add(13,group.optLong("vitality",0))
            .add(15,group.optLong("recallTime",0)).add(16,group.optLong("recallMember",0))
            .add(18,group.optInt("level",GUILD_LEVEL)).add(19,combatAverage(group))
            .add(22,buff).add(27,buffTime)
            .add(21,("xinfengzhou-"+group.getString("id")).getBytes(StandardCharsets.UTF_8))
            .add(24,group.optLong("emblem",1)).add(25,group.optLong("emblemBorder",1))
            .add(26,group.optLong("emblemBackground",1)).add(28,group.optLong("emblemColor",0))
            .add(29,group.optLong("emblemBorderColor",0))
            .add(30,group.optLong("emblemBackgroundColor",0));
        JSONObject members=group.getJSONObject("members"),requests=group.getJSONObject("requests");
        for(Iterator<String> it=members.keys();it.hasNext();) {
            JSONObject person=members.getJSONObject(it.next());
            out.add(4,simple(person,now).bytes());
            out.add(31,new ProtoWire().add(1,person.getLong("roleId"))
                .addDouble(2,person.optDouble("ce",0)).bytes());
            if(person.getInt("privilege")==1)out.add(3,person.getLong("roleId"));
        }
        for(Iterator<String> it=requests.keys();it.hasNext();)out.add(12,simple(requests.getJSONObject(it.next()),now).bytes());
        JSONArray logs=group.optJSONArray("logs");
        if(logs!=null)for(int i=logs.length()-1;i>=0;i--){
            JSONObject event=logs.getJSONObject(i);
            out.add(17,new ProtoWire().add(1,event.getLong("id"))
                .add(2,event.getLong("time")).add(4,event.getLong("stringId"))
                .add(5,event.getString("name").getBytes(StandardCharsets.UTF_8)).bytes());
        }
        out.add(20,requests.length()).add(32,group.optLong("lastCETime",0));return out;
    }
    private static byte[] userInfo(JSONObject snapshot,Identity actor)throws Exception {
        long now=System.currentTimeMillis()/1000, day=chinaDay(now);
        ProtoWire user=new ProtoWire();String own=memberGuild(snapshot,actor.roleId);
        JSONObject userState=users(snapshot).optJSONObject(actor.accountId);
        if(userState!=null) {
            user.add(5,userState.optLong("leftAt",0));
            user.add(7,userState.optInt("donateCount",0));
            user.add(8,userState.optLong("lastDonate",0));
            user.add(9,userState.optLong("totalVitality",0));
            user.add(10,userState.optLong("donateDay",-1)==day?userState.optLong("dailyVitality",0):0);
            user.add(11,userState.optInt("joinCount",0));
        }
        if(!own.isEmpty()) {
            JSONObject group=requiredGuild(snapshot,own), ownMember=member(group,actor.roleId);
            user.add(2,own.getBytes(StandardCharsets.UTF_8));
            JSONObject deployed=group.optJSONObject("mercenaries");
            if(deployed!=null)for(Iterator<String> it=deployed.keys();it.hasNext();) {
                JSONObject mercenary=deployed.getJSONObject(it.next());
                if(mercenary.optLong("roleId",0)==actor.roleId)
                    user.add(6,mercenary.optLong("servantId",0));
            }
            if(userState==null)user.add(7,ownMember.optInt("donateCount",0))
                .add(8,ownMember.optLong("lastDonate",0)).add(9,ownMember.optLong("totalVitality",0))
                .add(10,ownMember.optLong("donateDay",-1)==day?ownMember.optLong("dailyVitality",0):0);
        }
        JSONObject all=groups(snapshot);
        for(Iterator<String> it=all.keys();it.hasNext();) {
            JSONObject group=all.getJSONObject(it.next());
            JSONObject request=group.getJSONObject("requests").optJSONObject(key(actor.roleId));
            if(request!=null) {
                ProtoWire entry=new ProtoWire().add(1,group.getString("id").getBytes(StandardCharsets.UTF_8))
                    .add(2,group.getString("name").getBytes(StandardCharsets.UTF_8))
                    .add(3,request.optLong("joinedAt",0))
                    .add(4,group.optLong("emblem",1)).add(5,group.optLong("emblemBorder",1))
                    .add(6,group.optLong("emblemBackground",1))
                    .add(7,group.optLong("emblemColor",0)).add(8,group.optLong("emblemBorderColor",0))
                    .add(9,group.optLong("emblemBackgroundColor",0));
                user.add(3,entry.bytes());
            }
        }
        ProtoWire result=new ProtoWire().add(1,user.bytes());
        if(!own.isEmpty())result.add(2,guild(requiredGuild(snapshot,own),now).bytes());
        result.add(3,"ok".getBytes(StandardCharsets.UTF_8)).add(4,new byte[0]);
        return result.bytes();
    }
    private static ProtoWire listEntry(JSONObject group)throws Exception {
        JSONObject leader=group.getJSONObject("members").getJSONObject(key(group.getLong("president")));
        return new ProtoWire().add(1,group.getString("id").getBytes(StandardCharsets.UTF_8))
            .add(2,group.getString("name").getBytes(StandardCharsets.UTF_8))
            .add(3,group.getJSONObject("members").length())
            .add(4,group.getString("slogan").getBytes(StandardCharsets.UTF_8))
            .add(5,group.optInt("level",GUILD_LEVEL)).add(6,group.getLong("president"))
            .add(7,leader.getString("name").getBytes(StandardCharsets.UTF_8))
            .add(8,leader.optInt("level",1)).add(9,combatAverage(group))
            .add(10,group.optLong("emblem",1))
            .add(11,group.optLong("emblemBorder",1)).add(12,group.optLong("emblemBackground",1))
            .add(14,group.optLong("emblemColor",0)).add(15,group.optLong("emblemBorderColor",0))
            .add(16,group.optLong("emblemBackgroundColor",0)).add(17,combatTotal(group));
    }
    private static byte[] list(JSONObject snapshot,String route,Map<String,String> args)throws Exception {
        List<JSONObject> items=new ArrayList<JSONObject>();JSONObject all=groups(snapshot);
        String query=argument(args,"content","guildname","name");
        if(route.equals("/guild/search")) {
            if(query==null || query.isEmpty() || query.codePointCount(0,query.length())>40)throw new Invalid("Invalid search");
            query=normalizedName(query);
        }
        for(Iterator<String> it=all.keys();it.hasNext();) {
            JSONObject group=all.getJSONObject(it.next());
            if(route.equals("/guild/search") && !normalizedName(group.getString("name")).contains(query))continue;
            items.add(group);
        }
        if(route.equals("/guild/guildsbyce"))Collections.sort(items,(a,b)->{
            try{return Long.compare(combatTotal(b),combatTotal(a));}
            catch(Exception error){throw new IllegalStateException(error);}
        });
        else if(route.equals("/guild/guildsbymember"))Collections.sort(items,(a,b)->Integer.compare(
            b.optJSONObject("members").length(),a.optJSONObject("members").length()));
        else Collections.sort(items,Comparator.comparing(a->a.optString("name","")));
        int page=1;String raw=argument(args,"page");
        if(raw!=null && !raw.isEmpty())try{page=Integer.parseInt(raw);}catch(NumberFormatException e){throw new Invalid("Invalid page");}
        if(page<0 || page>100000)throw new Invalid("Invalid page");
        // The original client uses a string page; accept both zero and one as the first page.
        int start=(Math.max(1,page)-1)*30;
        ProtoWire result=new ProtoWire();
        for(int i=start;i<items.size() && i<start+30;i++)result.add(1,listEntry(items.get(i)).bytes());
        result.add(2,items.size());return result.bytes();
    }
    private static byte[] mercenaries(JSONObject snapshot,Map<String,String> args)throws Exception {
        long now=System.currentTimeMillis()/1000L;
        String id=argument(args,"guildID","guildid","guildId");
        JSONObject group=id==null?null:groups(snapshot).optJSONObject(id);
        ProtoWire list=new ProtoWire();
        if(id!=null)list.add(1,id.getBytes(StandardCharsets.UTF_8));
        if(group==null)return list.bytes();
        JSONObject entries=group.optJSONObject("mercenaries");
        if(entries==null)return list.bytes();
        for(Iterator<String> it=entries.keys();it.hasNext();) {
            String mapKey=it.next();JSONObject source=entries.getJSONObject(mapKey);
            ProtoWire mercenary=new ProtoWire().add(1,source.getLong("roleId"))
                .add(2,source.optLong("servantId",0)).add(5,source.optLong("garrisonTime",0))
                .add(6,source.optInt("employCount",0)).add(7,mercenaryTimeProfit(source,now))
                .add(8,source.optInt("employProfit",0)).add(9,source.optInt("employDailyProfit",0))
                .add(10,source.optLong("lastEmployTime",0)).add(11,source.optInt("employDailyCount",0))
                .add(12,source.optInt("curImage",1))
                .add(13,source.optString("roleName","").getBytes(StandardCharsets.UTF_8));
            String servantInfo=source.optString("servantInfo","");
            if(!servantInfo.isEmpty())mercenary.add(3,com.codex.witchweapon.host.Base64.decode(servantInfo,0));
            String weaponInfo=source.optString("weaponInfo","");
            if(!weaponInfo.isEmpty())mercenary.add(4,com.codex.witchweapon.host.Base64.decode(weaponInfo,0));
            ProtoWire mapEntry=new ProtoWire().add(1,mapKey.getBytes(StandardCharsets.UTF_8))
                .add(2,mercenary.bytes());
            list.add(2,mapEntry.bytes());
        }
        return list.bytes();
    }
}
