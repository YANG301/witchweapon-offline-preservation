package com.codex.witchweapon;

import com.codex.witchweapon.host.AtomicFile;
import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.security.MessageDigest;
import java.util.*;

/** Versioned local progress. All mutations are committed before returning success. */
final class LocalSave {
    static final long STAGE=3110001002L;
    static final long MAZE_TRIAL=StageCatalog.MAZE_TRIAL;
    // The preserved /role/role seed selects icon and frame 1. Older saves do
    // not contain cosmetic selections, so use those same values without
    // rewriting the save during a read-only role lookup.
    private static final int DEFAULT_HEAD=1;
    private static final int DEFAULT_HEAD_BOX=1;
    // The original head.txt and headbox.txt have unique IDs 1..46 and 1..19.
    // Source SHA-256: head 93999796F3ABF7422BCB280873569493470958A088873849DEBBE6EBBE052841;
    // headbox 9A81B4C0DE366039EC4C83EE3500FF7603E6B97587D2318FC55A21A57CCF0836.
    private static final int MAX_CONFIG_HEAD=46;
    private static final int MAX_CONFIG_HEAD_BOX=19;
    // A new profile starts at the beginning of the original level curve. Saves
    // without this marker are existing preservation accounts and keep their
    // established level and inventory behavior.
    private static final int STARTER_PROFILE=1;
    private static final long STARTER_GOLD=1000L;
    // The preserved 1-2 victory screen awards five role EXP. Use that modest
    // local rule in the simplified campaign/maze until per-stage original
    // server rewards are recovered. The old 2,500-EXP catch-up skipped levels.
    private static final long ROLE_EXP_PER_CLEAR=5L;
    private static final SecureRandom ROLE_ID_RANDOM=new SecureRandom();
    private final AtomicFile file;
    private JSONObject state;
    // Immutable startup catalog, retained so a reward that levels the role can
    // update the AP cap in that same atomic save rather than on the next replay.
    private JSONObject staminaCatalog;
    LocalSave(File dir){file=new AtomicFile(new File(dir,"offline_save_v1.json"));}
    private void loadExistingForAdmin() throws Exception {
        // The ordinary game routes create a first save on demand. Merely viewing
        // an account in the admin UI must never perform that creation, including
        // when another request has cached this LocalSave but has not loaded it.
        File base=file.getBaseFile();
        if(!Files.isRegularFile(base.toPath(),LinkOption.NOFOLLOW_LINKS) &&
                !Files.isRegularFile(new File(base+".bak").toPath(),LinkOption.NOFOLLOW_LINKS))
            throw new AdminMissing();
        load();
    }
    private static long revisionOf(JSONObject value) throws IOException {
        if(!value.has("saveRevision"))return 0;
        Object revision=value.opt("saveRevision");
        if(revision==null || !revision.toString().matches("(?:0|[1-9][0-9]{0,18})"))
            throw new IOException("Invalid save revision");
        try{return Long.parseLong(revision.toString());}
        catch(NumberFormatException e){throw new IOException("Invalid save revision",e);}
    }
    private void load() throws Exception {
        if(state!=null)return;
        if(file.getBaseFile().exists() || new File(file.getBaseFile()+".bak").exists()) {
            state=new JSONObject(new String(file.readFully(),StandardCharsets.UTF_8));
            if(state.getInt("version")!=1)throw new IOException("Unsupported local save version");
            revisionOf(state);
        } else {
            JSONObject s=new JSONObject();s.put("version",1);s.put("name","本地玩家");
            s.put("roleCreated",false);
            s.put("starterProfile",STARTER_PROFILE);s.put("namePending",true);
            // New cosmetic ownership rules apply only to accounts created
            // after this version. Existing online saves keep their access.
            s.put("cosmeticProfile",1);
            s.put("gold",STARTER_GOLD);s.put("rmb",0L);s.put("exp",0L);
            s.put("stamina",200L);s.put("activityStamina",0L);
            s.put("wins",0);s.put("attempts",0);
            s.put("stage",STAGE);s.put("stars",0);s.put("createdAt",System.currentTimeMillis());
            commit(s);
        }
        JSONObject labSeed=new JSONObject(state.toString());
        if(LocalActivityLab.initialize(labSeed,null,System.currentTimeMillis()/1000))commit(labSeed);
    }
    private void commit(JSONObject next) throws Exception {
        long now=System.currentTimeMillis()/1000;
        if(state!=null && staminaCatalog!=null &&
           (next.optLong("exp",0)!=state.optLong("exp",0) ||
            next.optLong("stamina",200)!=state.optLong("stamina",200)))
            StaminaRecovery.reconcileMutation(next,StaminaRecovery.level(next,staminaCatalog),now);
        StaminaRecovery.beforeCommit(state,next,now);
        long revision=state==null?0:revisionOf(state);
        if(revision==Long.MAX_VALUE)throw new IOException("Save revision exhausted");
        next.put("saveRevision",revision+1);
        FileOutputStream out=null;
        try {
            out=file.startWrite();out.write((next.toString(2)+"\n").getBytes(StandardCharsets.UTF_8));
            file.finishWrite(out);state=next;
        } catch(Exception e){if(out!=null)file.failWrite(out);throw e;}
    }
    private static long num(Map<String,String> args,String key,long fallback){
        try{return Long.parseLong(args.get(key));}catch(Exception e){return fallback;}
    }
    private static long requiredPositiveId(Map<String,String> args,String key)throws IOException{
        String value=args.get(key);
        if(value==null || !value.matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid "+key);
        try{
            long id=Long.parseLong(value);
            if(id>0)return id;
        }catch(NumberFormatException ignored){}
        throw new IOException("Invalid "+key);
    }
    private static boolean guidePassed(Map<String,String> args)throws IOException{
        String value=null;
        for(String key:new String[]{"pass","isWin","iswin","win"}){
            if(args.containsKey(key)){
                String candidate=args.get(key);
                if(value!=null && !value.equalsIgnoreCase(candidate))
                    throw new IOException("Conflicting guide battle result");
                value=candidate;
            }
        }
        if(value==null)throw new IOException("Missing guide battle result");
        if(value.equals("1") || value.equalsIgnoreCase("true"))return true;
        if(value.equals("0") || value.equalsIgnoreCase("false"))return false;
        throw new IOException("Invalid guide battle result");
    }
    private int selectedCosmetic(String key,int fallback) throws IOException {
        if(!state.has(key))return fallback;
        Object value=state.opt(key);
        if(!(value instanceof Number))throw new IOException("Invalid role cosmetic");
        Number number=(Number)value;
        long selected=number.longValue();
        if(selected<0 || selected>Integer.MAX_VALUE || number.doubleValue()!=selected)
            throw new IOException("Invalid role cosmetic");
        if(selected==0)return fallback;
        return (int)selected;
    }
    private static boolean ownedUnlock(JSONObject entries,String id) {
        if(entries==null || !entries.has(id))return false;
        Object value=entries.opt(id);
        if(value instanceof Boolean)return (Boolean)value;
        if(value instanceof Number){Number number=(Number)value;
            return number.longValue()==1 && number.doubleValue()==1;}
        return false;
    }
    /** Only fields consumed by the preserved Android Lua UI are mirrored locally. */
    synchronized String mirrorState() throws Exception {
        load();
        JSONObject refreshed=new JSONObject(state.toString());
        if(StaminaRecovery.advanceSaved(refreshed,System.currentTimeMillis()/1000))
            commit(refreshed);
        JSONObject mirror=new JSONObject();
        String[] fields={"version","name","gold","rmb","stamina","activityStamina",
            "storyCurrency","activityStoryCurrency",
            "inventoryRevision","collectionRevision","mazeRound","mazeHP",
            "active","activeStage","battleMazeRound","startKey","labActivity"};
        for(String key:fields)if(state.has(key))mirror.put(key,state.get(key));
        for(Iterator<String> it=state.keys();it.hasNext();){
            String key=it.next();
            if(key.startsWith("mazeEnergy_") && key.length()<64)mirror.put(key,state.get(key));
        }
        return mirror.toString();
    }
    /** Original account UI role summary. A default save is not a created role. */
    synchronized String roleSummary() throws Exception {
        load();
        // Pre-metadata saves may already have completed /role/create while
        // retaining the default name. They require an explicit migration.
        if(!state.has("roleCreated"))throw new IOException("Role metadata migration required");
        JSONObject summary=new JSONObject();
        summary.put("version",1);
        boolean created=state.optBoolean("roleCreated",false);
        long roleId=state.optLong("legacyRoleId",0);
        if(created && roleId<=0)throw new IOException("Created role has no valid ID");
        summary.put("exists",created);
        summary.put("roleId",created?Long.toString(roleId):"");
        summary.put("name",created?state.getString("name"):"");
        summary.put("head",created?selectedCosmetic("curHead",DEFAULT_HEAD):0);
        summary.put("headBox",created?selectedCosmetic("curHeadBox",DEFAULT_HEAD_BOX):0);
        return summary.toString();
    }
    /** The original /role/role level curve, for server-side guild gates. */
    synchronized int guildRoleLevel(JSONObject catalog) throws Exception {
        loadExistingForAdmin();
        if(!state.optBoolean("roleCreated",false) || state.optLong("legacyRoleId",0)<=0)
            throw new IOException("Created role required");
        long exp=state.getLong("exp");int level=initialRoleLevel();
        JSONObject costs=catalog.getJSONObject("roleLevels");
        while(level<100){
            long cost=costs.optLong(String.valueOf(level),Long.MAX_VALUE);
            if(cost<=0 || exp<cost)break;
            exp-=cost;level++;
        }
        return level;
    }
    /** A stable strength estimate from the same owned servants and weapon tables used by combat. */
    synchronized long guildCombatEffectiveness(JSONObject catalog)throws Exception {
        loadExistingForAdmin();
        if(!state.optBoolean("roleCreated",false) || state.optLong("legacyRoleId",0)<=0)
            throw new IOException("Created role required");
        JSONObject owned=state.optJSONObject("ownedServants");
        if(owned==null || owned.length()==0)return guildRoleLevel(catalog)*100L;
        JSONObject weapons=catalog.getJSONObject("weapons");
        JSONObject modifiers=catalog.getJSONObject("weaponMods");
        long[] strongest=new long[4];
        for(java.util.Iterator<String> it=owned.keys();it.hasNext();) {
            String id=it.next();
            Object encoded=owned.opt(id);
            if(!(encoded instanceof String))continue;
            ProtoWire servant=LocalEconomy.decode((String)encoded);
            if(servant.number(1,0)<=0)continue;
            long level=Math.max(1,Math.min(100,servant.number(2,1)));
            long rank=Math.max(1,Math.min(10,servant.number(4,1)));
            long star=Math.max(1,Math.min(10,servant.number(5,1)));
            JSONObject table=modifiers.optJSONObject(id);
            long weaponLevel=Math.max(1,Math.min(100,servant.number(12,1)));
            double modifier=table==null?1:table.optLong(Long.toString(weaponLevel),10000)/10000.0;
            double bestWeapon=0;
            for(ProtoWire.Field field:servant.fields)if(field.number==13 && field.type==2) {
                ProtoWire weapon=ProtoWire.parse(field.data);
                JSONObject definition=weapons.optJSONObject(Long.toString(weapon.number(1,0)));
                if(definition==null)continue;
                int weaponRank=(int)Math.max(1,Math.min(2,weapon.number(4,1)))-1;
                double damage=definition.getJSONArray("physical").getDouble(weaponRank)
                    +definition.getJSONArray("magical").getDouble(weaponRank);
                bestWeapon=Math.max(bestWeapon,damage*modifier);
            }
            double growth=1+0.05*Math.max(0,level-5)+0.08*(rank-1)+0.1*(star-1)
                +0.01*Long.bitCount(servant.number(7,0)&63);
            long power=Math.round((bestWeapon+60*level)*growth);
            for(int i=0;i<strongest.length;i++)if(power>strongest[i]) {
                for(int j=strongest.length-1;j>i;j--)strongest[j]=strongest[j-1];
                strongest[i]=power;break;
            }
        }
        long total=0;for(long power:strongest)total+=power;
        return Math.max(guildRoleLevel(catalog)*100L,total);
    }
    private int initialRoleLevel(){
        return state.optInt("starterProfile",0)==STARTER_PROFILE?1:5;
    }
    /** Authoritative owned servant payloads used to validate guild mercenary garrisons. */
    synchronized JSONObject guildOwnedServants(JSONObject catalog) throws Exception {
        loadExistingForAdmin();
        if(!state.optBoolean("roleCreated",false) || state.optLong("legacyRoleId",0)<=0)
            throw new GuildStore.Conflict("Created role required");
        JSONObject next=new JSONObject(state.toString());
        LocalEconomy.init(next,catalog);
        if(!next.toString().equals(state.toString()))commit(next);
        JSONObject owned=state.optJSONObject("ownedServants");
        if(owned==null)throw new IOException("Owned servant save is unavailable");
        return new JSONObject(owned.toString());
    }
    /** Idempotent debit for a guild operation recorded in the shared intent log. */
    synchronized void guildRequireFunds(long roleId,String currency,long amount)throws Exception {
        loadExistingForAdmin();
        if(state.optLong("legacyRoleId",0)!=roleId ||
            !(currency.equals("rmb") || currency.equals("gold")) || amount<1)
            throw new GuildStore.Forbidden();
        if(state.optLong(currency,currency.equals("rmb")?100000L:0L)<amount)
            throw new GuildStore.Conflict("Insufficient guild currency");
    }
    /** Idempotent debit for a guild operation recorded in the shared intent log. */
    synchronized void guildDebit(String transaction,long roleId,String currency,long amount)throws Exception {
        loadExistingForAdmin();
        if(!transaction.matches("[a-f0-9-]{36}") ||
            !(currency.equals("rmb") || currency.equals("gold")) || amount<1 ||
            amount>1000000000000L || state.optLong("legacyRoleId",0)!=roleId)
            throw new GuildStore.Forbidden();
        JSONObject ledger=state.optJSONObject("guildDebits");
        if(ledger!=null && ledger.has(transaction)) {
            JSONObject entry=ledger.getJSONObject(transaction);
            if(entry.getLong("roleId")!=roleId || !currency.equals(entry.getString("currency")) ||
                entry.getLong("amount")!=amount)throw new IOException("Guild debit ID conflict");
            return;
        }
        long balance=state.optLong(currency,currency.equals("rmb")?100000L:0L);
        if(balance<amount)throw new GuildStore.Conflict("Insufficient guild currency");
        JSONObject next=new JSONObject(state.toString());
        next.put(currency,balance-amount);
        JSONObject nextLedger=next.optJSONObject("guildDebits");
        if(nextLedger==null){nextLedger=new JSONObject();next.put("guildDebits",nextLedger);}
        if(nextLedger.length()>=10000)throw new IOException("Guild debit ledger limit reached");
        nextLedger.put(transaction,new JSONObject().put("roleId",roleId)
            .put("currency",currency).put("amount",amount));
        commit(next);
    }
    /** Called by a validated guild operation; the daily objective is capped at one. */
    synchronized void guildTaskCompleted(long roleId,boolean donation,long eventTime)throws Exception {
        loadExistingForAdmin();
        if(state.optLong("legacyRoleId",0)!=roleId)throw new GuildStore.Forbidden();
        JSONObject next=new JSONObject(state.toString());
        if(donation)LocalDaily.recordGuildDonation(next,eventTime);
        else LocalDaily.recordGuildSupport(next,eventTime);
        ProgressionTasks.recordGuildMembership(next);
        if(!next.toString().equals(state.toString()))commit(next);
    }
    synchronized boolean guildDebitDone(String transaction,long roleId,String currency,long amount)throws Exception {
        loadExistingForAdmin();
        if(state.optLong("legacyRoleId",0)!=roleId)throw new GuildStore.Forbidden();
        JSONObject ledger=state.optJSONObject("guildDebits");
        if(ledger==null || !ledger.has(transaction))return false;
        JSONObject entry=ledger.getJSONObject(transaction);
        if(entry.getLong("roleId")!=roleId || !currency.equals(entry.getString("currency")) ||
            entry.getLong("amount")!=amount)throw new IOException("Guild debit ID conflict");
        return true;
    }
    /** Idempotent payout for a guild mercenary recall recorded in GuildStore. */
    synchronized void guildCredit(String transaction,long roleId,long guildCurrency,long gold)throws Exception {
        loadExistingForAdmin();
        if(!transaction.matches("[a-f0-9-]{36}") || state.optLong("legacyRoleId",0)!=roleId ||
            guildCurrency<0 || gold<0 || guildCurrency>1000000000000L || gold>1000000000000L)
            throw new GuildStore.Forbidden();
        JSONObject ledger=state.optJSONObject("guildCredits");
        if(ledger!=null && ledger.has(transaction)) {
            JSONObject entry=ledger.getJSONObject(transaction);
            if(entry.getLong("roleId")!=roleId || entry.getLong("guildCurrency")!=guildCurrency ||
                entry.getLong("gold")!=gold)throw new IOException("Guild credit ID conflict");
            return;
        }
        long nextCurrency=Math.addExact(state.optLong("guildCurrency",0),guildCurrency);
        long nextGold=Math.addExact(state.optLong("gold",0),gold);
        if(nextCurrency>1000000000000L || nextGold>1000000000000L)
            throw new IOException("Guild credit balance limit");
        JSONObject next=new JSONObject(state.toString());
        next.put("guildCurrency",nextCurrency).put("gold",nextGold);
        JSONObject nextLedger=next.optJSONObject("guildCredits");
        if(nextLedger==null){nextLedger=new JSONObject();next.put("guildCredits",nextLedger);}
        if(nextLedger.length()>=10000)throw new IOException("Guild credit ledger limit reached");
        nextLedger.put(transaction,new JSONObject().put("roleId",roleId)
            .put("guildCurrency",guildCurrency).put("gold",gold));
        commit(next);
    }
    /** Redacted account summary for the private administration service. */
    synchronized String adminSummary() throws Exception {
        loadExistingForAdmin();
        checkAdminRoleMetadata();
        JSONObject summary=new JSONObject();
        summary.put("version",1);
        summary.put("revision",revisionOf(state));
        summary.put("name",state.getString("name"));
        summary.put("gold",state.getLong("gold"));
        summary.put("roleCreated",state.optBoolean("roleCreated",false));
        long roleId=state.optLong("legacyRoleId",0);
        summary.put("roleId",roleId>0?Long.toString(roleId):"");
        for(String field:new String[]{"exp","wins","attempts","stars","mazeWins",
                "mazeAttempts","mazeStars"})summary.put(field,state.optLong(field,0));
        summary.put("mazeRound",state.optLong("mazeRound",1));
        for(String field:new String[]{"drawCount","createdAt","lastSettlementAt"})
            if(state.has(field))summary.put(field,state.get(field));
        summary.put("active",state.optBoolean("active",false));
        return summary.toString();
    }
    private void checkAdminRoleMetadata() throws Exception {
        if(!(state.opt("roleCreated") instanceof Boolean))
            throw new IOException("Role metadata migration required");
        boolean created=state.getBoolean("roleCreated");
        long roleId=state.optLong("legacyRoleId",0);
        if((created && roleId<=0) || (!created && state.has("legacyRoleId")))
            throw new IOException("Invalid role metadata");
    }
    private static boolean validAdminText(String text,int min,int max) {
        if(text==null || text.isEmpty() || text.codePointCount(0,text.length())<min ||
                text.codePointCount(0,text.length())>max ||
                text.getBytes(StandardCharsets.UTF_8).length>512)return false;
        int first=text.codePointAt(0),last=text.codePointBefore(text.length());
        if(Character.isWhitespace(first)||Character.isSpaceChar(first)||
                Character.isWhitespace(last)||Character.isSpaceChar(last))return false;
        for(int i=0;i<text.length();){
            int cp=text.codePointAt(i);
            if(Character.isISOControl(cp)||Character.getType(cp)==Character.FORMAT ||
                    (cp>=0xD800&&cp<=0xDFFF))return false;
            i+=Character.charCount(cp);
        }
        return true;
    }
    static final class AdminConflict extends IOException {
        AdminConflict(){super("Save changed; refresh before editing");}
    }
    static final class AdminMissing extends IOException {
        AdminMissing(){super("Account has no game save");}
    }
    static final class AdminValidation extends IOException {
        AdminValidation(String message){super(message);}
    }
    /** Rich editor and recovery paths share the exact monitor used by gameplay. */
    synchronized String adminSave(JSONObject catalog,StageCatalog stages)throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();
        return AdminDataService.view(state,revisionOf(state),catalog,stages).toString();
    }
    synchronized String adminDataPatch(Map<String,String> args,JSONObject catalog,StageCatalog stages,
            boolean preview)throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();long revision=revisionOf(state);
        AdminDataService.expected(args,revision,"changes");
        AdminDataService.Plan plan=AdminDataService.plan(state,catalog,stages,args.get("changes"));
        if(preview)return plan.preview(revision).toString();
        String backupId="";
        if(plan.changes.length()>0){
            AdminJournal.Record record=AdminJournal.prepare(file.getBaseFile(),revision,args.get("reason"),
                state,plan.next,"edit",plan.changes);
            backupId=record.id();commit(plan.next);verifyAdminCommit();record.committed(revisionOf(state));
        }
        return new JSONObject().put("revision",Long.toString(revisionOf(state)))
            .put("backupId",backupId).put("changeCount",plan.changes.length()).toString();
    }
    synchronized String adminBackups()throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();return AdminJournal.backups(file.getBaseFile()).toString();
    }
    synchronized String adminBackupCreate(Map<String,String> args)throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();long revision=revisionOf(state);
        AdminDataService.expected(args,revision);
        return AdminJournal.backup(file.getBaseFile(),revision,args.get("reason"),state).toString();
    }
    synchronized byte[] adminBackupRead(Map<String,String> args)throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();
        if(args.size()!=1 || !args.containsKey("backupId"))throw new AdminValidation("Backup ID is required");
        return AdminJournal.readBackupBytes(file.getBaseFile(),args.get("backupId"));
    }
    synchronized String adminBackupRestore(Map<String,String> args,JSONObject catalog,StageCatalog stages,
            boolean preview)throws Exception{
        loadExistingForAdmin();checkAdminRoleMetadata();long revision=revisionOf(state);
        AdminDataService.expected(args,revision,"backupId");
        if(AdminDataService.busy(state))throw new AdminDataService.ActiveBattle();
        JSONObject backup=AdminJournal.readBackup(file.getBaseFile(),args.get("backupId"));
        AdminDataService.Plan plan=AdminDataService.restore(state,backup.getJSONObject("save"),catalog,stages);
        org.json.JSONArray retained=AdminDataService.retainedFields(state);
        if(preview)return plan.preview(revision).put("retainedFields",retained).toString();
        String beforeId="";
        if(plan.changes.length()>0){
            AdminJournal.Record record=AdminJournal.prepare(file.getBaseFile(),revision,args.get("reason"),
                state,plan.next,"restore",plan.changes);
            beforeId=record.id();commit(plan.next);verifyAdminCommit();record.committed(revisionOf(state));
        }
        org.json.JSONArray restored=new org.json.JSONArray();for(String key:plan.changedKeys)restored.put(key);
        return new JSONObject().put("revision",Long.toString(revisionOf(state))).put("backupId",beforeId)
            .put("restoredFrom",args.get("backupId")).put("restoredFields",restored)
            .put("retainedFields",retained).toString();
    }
    private void verifyAdminCommit()throws Exception{
        JSONObject reread=AdminJournal.parseSave(AdminJournal.regularBytes(file.getBaseFile().toPath()));
        if(!AdminJournal.sameJson(state,reread))
            throw new com.codex.witchweapon.host.PersistenceException("Admin save read-back did not match",new IOException("Save verification failed"));
    }
    /** Runs under the same per-account monitor as gameplay and fixture selection. */
    synchronized String adminPatch(Map<String,String> args) throws Exception {
        loadExistingForAdmin();
        checkAdminRoleMetadata();
        for(String field:args.keySet())
            if(!Arrays.asList("expectedRevision","reason","name","gold").contains(field))
                throw new AdminValidation("Unknown admin field");
        String expected=args.get("expectedRevision"),reason=args.get("reason");
        if(expected==null || !expected.matches("(?:0|[1-9][0-9]{0,18})") ||
                !validAdminText(reason,1,200) || (!args.containsKey("name")&&!args.containsKey("gold")))
            throw new AdminValidation("Invalid admin patch");
        long desiredRevision;
        try{desiredRevision=Long.parseLong(expected);}
        catch(NumberFormatException e){throw new AdminValidation("Invalid expected revision");}
        long currentRevision=revisionOf(state);
        if(desiredRevision!=currentRevision)throw new AdminConflict();
        if(AdminDataService.busy(state))throw new AdminDataService.ActiveBattle();
        JSONObject next=new JSONObject(state.toString());
        if(args.containsKey("name")){
            String name=args.get("name");
            if(!state.optBoolean("roleCreated",false) || !validAdminText(name,2,16) ||
                    name.getBytes(StandardCharsets.UTF_8).length>128)
                throw new AdminValidation("Invalid role name");
            next.put("name",name);
        }
        if(args.containsKey("gold")){
            String value=args.get("gold");
            if(value==null || !value.matches("(?:0|[1-9][0-9]{0,12})"))
                throw new AdminValidation("Invalid gold value");
            long gold;
            try{gold=Long.parseLong(value);}
            catch(NumberFormatException e){throw new AdminValidation("Invalid gold value");}
            if(gold>1000000000000L)throw new AdminValidation("Gold exceeds admin limit");
            next.put("gold",gold);
        }
        if(AdminJournal.sameJson(next,state))return adminSummary();
        // A durable, exact pre-change snapshot and prepare record are required
        // before replacing the live save. Crash recovery can inspect the audit
        // record even if the response or completion record was interrupted.
        AdminJournal.Record journal=AdminJournal.prepare(file.getBaseFile(),currentRevision,
            reason,state,next);
        commit(next);
        verifyAdminCommit();
        journal.committed(revisionOf(state));
        return adminSummary();
    }

    /** Deliver one administrator message without touching another account's save. */
    synchronized String adminSendMail(Map<String,String> args,JSONObject catalog) throws Exception {
        loadExistingForAdmin();
        checkAdminRoleMetadata();
        if(!state.getBoolean("roleCreated"))throw new AdminMissing();
        long revision=revisionOf(state);
        JSONObject next=new JSONObject(state.toString());
        LocalMail.Delivery delivered=LocalMail.deliver(next,catalog,args,revision,System.currentTimeMillis());
        if(!delivered.duplicate){
            AdminJournal.Record journal=AdminJournal.prepare(file.getBaseFile(),revision,
                args.get("reason"),state,next);
            commit(next);
            journal.committed(revisionOf(state));
        }
        return delivered.response(revisionOf(state));
    }
    private static long newRoleId(){
        long id;
        do{id=ROLE_ID_RANDOM.nextLong()&Long.MAX_VALUE;}while(id==0);
        return id;
    }
    /** Select an already-owned icon/frame for the authenticated account. */
    synchronized void changeCosmetic(boolean frame,Map<String,String> args,byte[] roleSeed) throws Exception {
        loadExistingForAdmin();
        checkAdminRoleMetadata();
        if(!state.getBoolean("roleCreated"))throw new IOException("Role has not been created");
        long roleId=requiredPositiveId(args,"roleid");
        if(roleId!=state.getLong("legacyRoleId"))throw new IOException("Role ID does not belong to this account");
        String argument=frame?"headbox":"head";
        long requested=requiredPositiveId(args,argument);
        int maximum=frame?MAX_CONFIG_HEAD_BOX:MAX_CONFIG_HEAD;
        if(requested>maximum)throw new IOException("Unknown role cosmetic");
        int id=(int)requested,field=frame?2:1;
        ProtoWire role=ProtoWire.parse(ProtoWire.parse(roleSeed).data(1));
        List<Long> flags=role.integers(field);
        boolean owned=id<=flags.size() && flags.get(id-1)==1;
        JSONObject unlocks=state.optJSONObject("roleUnlocks");
        JSONObject extra=unlocks==null?null:unlocks.optJSONObject(String.valueOf(field));
        if(ownedUnlock(extra,String.valueOf(id)))owned=true;
        if(!owned)throw new IOException("Role cosmetic is not owned");
        String stateKey=frame?"curHeadBox":"curHead";
        if(selectedCosmetic(stateKey,frame?DEFAULT_HEAD_BOX:DEFAULT_HEAD)==id)return;
        JSONObject next=new JSONObject(state.toString());
        next.put(stateKey,id);
        commit(next);
    }
    private ProtoWire sync(long now){
        long midnight=Math.floorDiv(now+28800,86400)*86400-28800;
        int staminaPurchases=state.optLong("staminaPurchaseDay",Long.MIN_VALUE)==LocalDaily.day(now)
            ?state.optInt("staminaPurchaseUsed",0):0;
        ProtoWire roleTime=new ProtoWire().set(1,staminaPurchases)
            .set(6,midnight+18000).set(10,midnight).set(12,8);
        if(state.optInt("starterProfile",0)==STARTER_PROFILE){
            boolean currentDay=state.optLong("drawFreeDay",Long.MIN_VALUE)==LocalDaily.day(now);
            // RoleTimeInstance: 3 free gold uses, 4 next free gold time,
            // 5 free Tarot uses. Publish the server's daily draw counters.
            roleTime.set(3,currentDay?state.optInt("drawGoldFreeUsed",0):0)
                .set(4,currentDay?state.optLong("drawGoldFreeAt",0):0)
                .set(5,currentDay?state.optInt("drawDiamondFreeUsed",0):0);
        }
        return new ProtoWire().set(1,now).set(4,state.optLong("stamina",200))
            .set(5,StaminaRecovery.protocolTime(state,now)).set(6,roleTime.bytes())
            .set(7,state.optLong("activityStamina",200)).set(8,now);
    }
    private void migrateFormerMaze() throws Exception {
        // Old author saves used mainline 1-3 as a placeholder for the twelve
        // round maze. The maze markers distinguish them from a new real 1-3.
        // Record a one-time migration even when this save has no old active
        // maze battle. Otherwise a future real 1-3 battle could be mistaken
        // for the old placeholder just because mazeRound survives in the save.
        if(state.optBoolean("mazeEntryMigrated",false))return;
        JSONObject next=new JSONObject(state.toString());
        if(state.optLong("activeStage",0)==StageCatalog.FORMER_MAZE_ENTRY &&
           (state.has("battleMazeRound") || state.optInt("mazeRound",0)>0))
            next.put("activeStage",MAZE_TRIAL);
        next.put("mazeEntryMigrated",true);
        commit(next);
    }
    private static JSONObject stageProgress(JSONObject save,long id) throws org.json.JSONException {
        JSONObject all=save.optJSONObject("mainlineStages");
        JSONObject progress=all==null?null:all.optJSONObject(Long.toString(id));
        if(progress!=null)return progress;
        JSONObject initial=new JSONObject();
        if(id==STAGE){
            initial.put("wins",save.optInt("wins",0));
            initial.put("attempts",save.optInt("attempts",0));
            initial.put("stars",save.optInt("stars",0));
            initial.put("firstRewardClaimed",save.optInt("wins",0)>0);
        }
        return initial;
    }
    private static JSONObject writableStageProgress(JSONObject save,long id) throws org.json.JSONException {
        JSONObject all=save.optJSONObject("mainlineStages");
        if(all==null){all=new JSONObject();save.put("mainlineStages",all);}
        String key=Long.toString(id);
        JSONObject progress=all.optJSONObject(key);
        if(progress==null){progress=stageProgress(save,id);all.put(key,progress);}
        return progress;
    }
    private boolean stageUnlocked(long id,StageCatalog stages) throws org.json.JSONException {
        if(!stages.supported(id))return false;
        if(stages.openAllMainline())return true;
        if(stageProgress(state,id).optInt("wins",0)>0)return true;
        if(id==3110001001L)return true;
        Long required=stages.prerequisite(id);
        return required==null || stageProgress(state,required).optInt("wins",0)>0;
    }
    private byte[] mainlineProgress(byte[] seed,StageCatalog stages) throws Exception {
        ProtoWire all=ProtoWire.parse(seed);
        int replaced=0;
        for(ProtoWire.Field field:all.fields){
            if(field.number!=1 || field.type!=2)continue;
            ProtoWire chapter=ProtoWire.parse(field.data);
            long chapterId=chapter.number(1,0);
            List<Long> ids=stages.stagesForChapter(chapterId);
            if(!ids.isEmpty()){
                chapter.clear(2);
                for(long id:ids){
                    JSONObject progress=stageProgress(state,id);
                    boolean passed=progress.optInt("wins",0)>0;
                    int stars=progress.optInt("stars",0);
                    // Existing simple-campaign-v1 wins may have been saved
                    // with zero because the original client sent no score.
                    if(passed && stages.openAllMainline())stars=3;
                    ProtoWire level=new ProtoWire().set(1,id)
                        .set(2,passed?1:0).set(3,stars==3?1:0)
                        .set(4,stageUnlocked(id,stages)?1:0)
                        .set(6,progress.optInt("attempts",0))
                        .set(7,StageSweep.eligible(state,stages,stages.stage(id))?1:0);
                    chapter.add(2,level.bytes());
                }
                replaced++;
            }else if(chapterId==3030001L){
                for(ProtoWire.Field levelField:chapter.fields){
                    if(levelField.number!=2 || levelField.type!=2)continue;
                    ProtoWire level=ProtoWire.parse(levelField.data);
                    if(level.number(1,0)!=MAZE_TRIAL)continue;
                    boolean passed=state.optInt("mazeWins",0)>0;
                    level.set(2,passed?1:0).set(3,state.optInt("mazeStars",0)==3?1:0)
                        .set(4,1).set(6,state.optInt("mazeAttempts",0))
                        .set(7,passed?1:0);
                    levelField.data=level.bytes();
                }
            }
            field.data=chapter.bytes();
        }
        if(replaced!=16)throw new IOException("Preserved mainline chapter seed is incomplete");
        return all.bytes();
    }
    private static double roleMaximumHP(byte[] roleTemplate) throws Exception {
        double[] attributes=ProtoWire.parse(roleTemplate).doubles(1);
        double maximum=attributes.length==0?1:attributes[0];
        if(!Double.isFinite(maximum) || maximum<=0)maximum=1;
        return maximum;
    }
    private static int mazeRoleHP(JSONObject snapshot,byte[] roleTemplate) throws Exception {
        double maximum=snapshot.optDouble("mazeRoleMaxHP",roleMaximumHP(roleTemplate));
        if(!Double.isFinite(maximum) || maximum<=0)maximum=roleMaximumHP(roleTemplate);
        double hp=snapshot.optDouble("mazeHP",1);
        if(!Double.isFinite(hp))hp=1;
        return (int)Math.max(1,Math.min(Integer.MAX_VALUE,
            Math.round(maximum*Math.max(0.01,Math.min(1,hp)))));
    }
    private int cscRuleLevel(JSONObject snapshot)throws Exception{
        if(snapshot.optInt("mazePreparedRound",0)==snapshot.optInt("mazeRound",1) &&
           !snapshot.optBoolean("mazeRoundSettled",false)){
            int level=snapshot.optInt("mazePreparedRoleLevel",0);
            if(level>=1 && level<=100)return level;
        }
        return MazeRules.roleLevel(snapshot,staminaCatalog);
    }
    private byte[] cscInfo(JSONObject snapshot,byte[] roleTemplate,long now) throws Exception {
        return BarrierLabyrinth.info(snapshot,roleTemplate,now,cscRuleLevel(snapshot));
    }
    private long cscBattleExp(){return ROLE_EXP_PER_CLEAR;}
    private ProtoWire cscCheckpointLoot(JSONObject snapshot,boolean grant)throws Exception{
        return MazeRules.loot(snapshot,staminaCatalog,BarrierLabyrinth.pendingBonus(snapshot),true,grant);
    }
    private byte[] cscLoot()throws Exception{
        // GetCscLoot.ParseProtoBuf reads LootResult directly, rather than the
        // CscCommit envelope used by battle and chest settlement.
        if(BarrierLabyrinth.pendingBonus(state)>0)return cscCheckpointLoot(state,false).bytes();
        if(state.optInt("mazeRound",1)>BarrierLabyrinth.rounds())return new ProtoWire().bytes();
        long exp=cscBattleExp();
        return MazeRules.loot(state,staminaCatalog,state.optInt("mazeRound",1),false,false)
            .add(1,new ProtoWire().set(1,10).set(3,exp).set(4,exp).bytes()).bytes();
    }
    private byte[] cscRole(byte[] roleTemplate,Map<String,String> args,JSONObject catalog) throws Exception {
        if(catalog==null)throw new IOException("Combat role catalog unavailable");
        BarrierLabyrinth.requireRoleStage(state,args);
        int round=state.optInt("mazeRound",1);
        if(round<1 || round>12)throw new IOException("Maze run already complete");
        Map<String,String> selected=new LinkedHashMap<String,String>(args);
        if(!selected.containsKey("servantcardids") && selected.containsKey("svcardids"))
            selected.put("servantcardids",selected.get("svcardids"));
        if(!selected.containsKey("weaponids") && selected.containsKey("wpids"))
            selected.put("weaponids",selected.get("wpids"));
        JSONObject next=new JSONObject(state.toString());
        LocalEconomy.init(next,catalog);
        BarrierLabyrinth.migrateGroup(next);
        List<Long> party=BarrierLabyrinth.selectBattleParty(next,selected.get("servantcardids"));
        StringJoiner partyIds=new StringJoiner("|");
        for(long servant:party)partyIds.add(Long.toString(servant));
        selected.put("servantcardids",partyIds.toString());
        CosmeticUnlocks.rememberFashion(next,catalog,args);
        byte[] role=LocalEconomy.combat(next,selected,roleTemplate,catalog);
        double maximum=roleMaximumHP(role);
        if(state.optInt("mazePreparedRound",0)!=round || state.optBoolean("mazeRoundSettled",false) ||
           state.optDouble("mazeRoleMaxHP",0)!=maximum){
            JSONObject prepared=new JSONObject(next.toString());
            prepared.put("mazePreparedRound",round);
            prepared.put("mazeRoundSettled",false);
            prepared.put("mazeRoleMaxHP",maximum);
            prepared.put("mazePreparedRoleLevel",MazeRules.roleLevel(next,catalog));
            prepared.put("mazePreparedEnemyLevel",MazeRules.enemyLevel(prepared.getInt("mazePreparedRoleLevel"),round));
            commit(prepared);
        }else if(!next.toString().equals(state.toString()))commit(next);
        ProtoWire wrapper=new ProtoWire();
        wrapper.set(16,mazeRoleHP(state,role));wrapper.set(18,role);
        for(long servant:party){
            wrapper.add(1,servant);
            wrapper.add(2,Math.round(Math.max(0,Math.min(1000,state.optDouble("mazeEnergy_"+servant,1000)))));
        }
        return wrapper.bytes();
    }
    private static String cscCommitIdentity(Map<String,String> args) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        for(String field:new String[]{"levelid","state","hp","servantcardids","energys","data"}){
            String value=args.get(field);
            if(value==null)value="";
            digest.update(field.getBytes(StandardCharsets.UTF_8));digest.update((byte)0);
            digest.update(value.getBytes(StandardCharsets.UTF_8));digest.update((byte)0);
        }
        StringBuilder hex=new StringBuilder(64);
        for(byte part:digest.digest())hex.append(String.format(Locale.ROOT,"%02x",part&255));
        return hex.toString();
    }
    private byte[] cscNormalCommit(Map<String,String> args,byte[] roleTemplate,long now) throws Exception {
        String outcome=args.get("state");
        if(!"0".equals(outcome) && !"1".equals(outcome))
            throw new IOException("Invalid maze settlement result");
        double absoluteHP;
        try{absoluteHP=Double.parseDouble(args.get("hp"));}
        catch(Exception ex){throw new IOException("Invalid maze HP");}
        if(!Double.isFinite(absoluteHP) || absoluteHP<0)throw new IOException("Invalid maze HP");
        String identity=cscCommitIdentity(args);
        if(state.optBoolean("mazeRoundSettled",false) &&
           identity.equals(state.optString("lastCscCommitIdentity","")) &&
            state.has("lastCscCommitResponse"))
            return Base64.decode(state.getString("lastCscCommitResponse"),Base64.DEFAULT);
        // A late unsettled CSC request must not close or reward a newly
        // entered stone slate. Already committed CSC retries above are read-only.
        if(state.optBoolean("active",false) &&
            StoneSlateBattle.contains(state.optLong("activeStage",0)))
            throw new IOException("Maze settlement superseded by stone slate");
        BarrierLabyrinth.requireCurrentStage(state,args.get("levelid"));
        int round=state.optInt("mazeRound",1);
        if(round<1 || round>12 || state.optInt("mazePreparedRound",0)!=round ||
           state.optBoolean("mazeRoundSettled",false))
            throw new IOException("Maze battle was not prepared or was already settled");
        String party=args.containsKey("servantcardids")?args.get("servantcardids"):"";
        String energy=args.containsKey("energys")?args.get("energys"):"";
        String[] servants=party.isEmpty()?new String[0]:party.split("\\|",-1);
        String[] values=energy.isEmpty()?new String[0]:energy.split("\\|",-1);
        if(servants.length!=values.length || servants.length>4)
            throw new IOException("Maze party energy mismatch");
        JSONObject next=new JSONObject(state.toString());
        Set<Long> eligible=new HashSet<Long>(BarrierLabyrinth.availableServants(next));
        Set<Long> settled=new HashSet<Long>();
        next.put("active",false);
        ProtoWire loot=new ProtoWire();
        double maxHP=state.optDouble("mazeRoleMaxHP",roleMaximumHP(roleTemplate));
        if(!Double.isFinite(maxHP) || maxHP<=0)maxHP=roleMaximumHP(roleTemplate);
        next.put("mazeHP",Math.max(0.01,Math.min(1,absoluteHP/maxHP)));
        for(int i=0;i<servants.length;i++){
            if(!servants[i].matches("[1-9][0-9]{0,18}"))throw new IOException("Invalid maze servant");
            long servant=Long.parseLong(servants[i]);
            if(!eligible.contains(servant) || !settled.add(servant))
                throw new IOException("Invalid maze settlement party");
            double power;
            try{power=Double.parseDouble(values[i]);}catch(Exception ex){throw new IOException("Invalid maze energy");}
            if(!Double.isFinite(power) || power<0 || power>1000)
                throw new IOException("Invalid maze energy");
            next.put("mazeEnergy_"+servants[i],power);
        }
        if("1".equals(outcome)){
            next.put("mazeWins",next.optInt("mazeWins",0)+1);
            next.put("mazeStars",Math.max(next.optInt("mazeStars",0),3));
            next.put("mazeRound",round+1);
            BarrierLabyrinth.recordVictory(next,round);
            // Gold and item identities use the original level/drop tables.
            // Original server quantities are absent: grant one listed item.
            long exp=cscBattleExp();
            loot=MazeRules.loot(next,staminaCatalog,round,false,true);
            next.put("exp",Math.addExact(next.getLong("exp"),exp));
            loot.add(1,new ProtoWire().set(1,10).set(3,exp).set(4,exp).bytes());
            if(round%3==0){
                // The fourth node is a claimable chest. Do not credit its
                // reward until the native ReceiveChest action commits it.
                next.put("mazePendingBonus",round);
            }
        }
        next.put("mazeRoundSettled",true);
        next.put("lastCscCommitIdentity",identity);
        next.put("lastSettlementAt",now);
        ProgressionTasks.recordBattleKills(next,args);
        LocalDaily.observe(next,state,"/level/pushMainLineProgress",now);
        byte[] response=new ProtoWire().set(1,cscInfo(next,roleTemplate,now)).set(2,loot.bytes())
            .set(100,new byte[0]).bytes();
        next.put("lastCscCommitResponse",Base64.encodeToString(response,Base64.NO_WRAP));
        commit(next);
        return response;
    }
    private byte[] cscBonusCommit(byte[] roleTemplate,long now)throws Exception{
        int completed=BarrierLabyrinth.pendingBonus(state);
        if(completed==0){
            // Network retry after a successful chest claim is read-only.
            if(state.optInt("mazeLastBonusRound",0)==state.optInt("mazeRound",1)-1 &&
               state.optInt("mazePreparedRound",0)!=state.optInt("mazeRound",1) &&
               state.has("mazeLastBonusResponse"))
                return Base64.decode(state.getString("mazeLastBonusResponse"),Base64.DEFAULT);
            throw new IOException("No maze checkpoint to claim");
        }
        JSONObject next=new JSONObject(state.toString());
        ProtoWire loot=cscCheckpointLoot(next,true);
        next.remove("mazePendingBonus");
        next.put("mazeLastBonusRound",completed);
        next.put("mazeSupplyBoxes",next.optInt("mazeSupplyBoxes",0)+1);
        next.put("mazeHP",Math.min(1,next.optDouble("mazeHP",1)+0.30));
        for(Iterator<String> it=next.keys();it.hasNext();){String key=it.next();
            if(key.startsWith("mazeEnergy_"))
                next.put(key,Math.min(1000,next.optDouble(key,1000)+300));
        }
        next.remove("lastCscCommitIdentity");next.remove("lastCscCommitResponse");
        byte[] response=new ProtoWire().set(1,cscInfo(next,roleTemplate,now))
            .set(2,loot.bytes()).set(100,new byte[0]).bytes();
        next.put("mazeLastBonusResponse",Base64.encodeToString(response,Base64.NO_WRAP));
        commit(next);
        return response;
    }
    synchronized String fixtureKey(String path,Map<String,String> args) throws Exception {
        load();
        long stage=num(args,"instanceid",0);
        if(stage==MAZE_TRIAL || stage==StageCatalog.FORMER_MAZE_ENTRY)migrateFormerMaze();
        if((path.equals("/combat/mob/json") || path.equals("/combat/mob/info")) && stage==MAZE_TRIAL){
            int round=state.optInt("mazeRound",1);
            return BarrierLabyrinth.fixtureKey(path,round);
        }
        return path+"#"+stage;
    }
    synchronized byte[] mazeJson(byte[] seed,JSONObject catalog)throws Exception{
        load();staminaCatalog=catalog;
        return BarrierLabyrinth.dynamicJson(seed,MazeRules.enemyLevel(cscRuleLevel(state),state.optInt("mazeRound",1)));
    }
    synchronized byte[] respond(String path,Map<String,String> args,byte[] seed,JSONObject catalog) throws Exception {
        return respond(path,args,seed,catalog,null,null);
    }
    synchronized byte[] respond(String path,Map<String,String> args,byte[] seed,JSONObject catalog,
                                byte[] storyFixture) throws Exception {
        return respond(path,args,seed,catalog,storyFixture,null);
    }
    synchronized byte[] respond(String path,Map<String,String> args,byte[] seed,JSONObject catalog,
                                byte[] storyFixture,StageCatalog stages) throws Exception {
        return respond(path,args,seed,catalog,storyFixture,stages,null,null);
    }
    synchronized byte[] respond(String path,Map<String,String> args,byte[] seed,JSONObject catalog,
                                byte[] storyFixture,StageCatalog stages,DailyBattle dailyBattles,
                                WeaponFurnace weaponFurnace) throws Exception {
        load();long now=System.currentTimeMillis()/1000;
        if(catalog!=null)staminaCatalog=catalog;
        JSONObject labSeed=new JSONObject(state.toString());
        if(LocalActivityLab.initialize(labSeed,catalog,now))commit(labSeed);
        JSONObject refreshed=new JSONObject(state.toString());
        boolean staminaChanged=StaminaRecovery.advance(refreshed,StaminaRecovery.level(state,catalog),now);
        boolean caphChanged=VipSystem.refresh(refreshed,now);
        if(staminaChanged || caphChanged)
            commit(refreshed);
        if(path.startsWith("/game/"))path=path.substring(5);
        if(LocalActivityLab.intercept(path,args)){
            JSONObject labNext=new JSONObject(state.toString());
            LocalActivityLab.Action labAction=LocalActivityLab.respond(labNext,catalog,path,args,seed,storyFixture,now);
            if(labAction.changed)commit(labNext);
            return labAction.response;
        }
        if(path.equals("/challenge/combat/victory") || path.equals("/challenge/combat/cancel")){
            StoneSlateBattle.Settlement settlement=StoneSlateBattle.bundled().settle(state,args,now,
                path.equals("/challenge/combat/cancel"));
            if(settlement.next!=null)commit(settlement.next);
            return settlement.response;
        }
        if(path.equals("/time/getStamina"))return sync(now).bytes();
        if(path.equals("/resource/buy/stamina")){
            JSONObject next=new JSONObject(state.toString());
            if(StaminaPurchase.apply(next,args,now)){
                ProgressionTasks.recordStaminaPurchase(state,next);
                commit(next);
            }
            return sync(now).bytes();
        }
        if(path.equals("/ap/instance/get"))return CaphActivityAccess.instance(seed);
        if(path.equals("/time/getData"))return CaphActivityAccess.timeData(seed,now);
        if(path.startsWith("/csc/") ||
           (path.equals("/level/startBattle") || path.equals("/level/rebattle") ||
            path.equals("/level/pushMainLineProgress")) &&
           (num(args,"instanceid",0)==MAZE_TRIAL ||
            num(args,"instanceid",0)==StageCatalog.FORMER_MAZE_ENTRY))
            migrateFormerMaze();
        if(path.startsWith("/csc/")){
            if(catalog==null)throw new IOException("Maze catalog unavailable");
            JSONObject prepared=new JSONObject(state.toString());
            LocalEconomy.init(prepared,catalog);BarrierLabyrinth.migrateGroup(prepared);
            if(!prepared.toString().equals(state.toString()))commit(prepared);
        }
        if(path.equals("/csc/mob") || path.equals("/combat/mob/info") &&
           (num(args,"instanceid",0)==MAZE_TRIAL || BarrierLabyrinth.supports(num(args,"instanceid",0))))
            return BarrierLabyrinth.dynamicMob(seed,MazeRules.enemyLevel(cscRuleLevel(state),state.optInt("mazeRound",1)));
        if(path.equals("/csc/info"))return cscInfo(state,seed,now);
        if(path.equals("/csc/loot"))return cscLoot();
        if(path.equals("/csc/role"))return cscRole(seed,args,catalog);
        if(path.equals("/csc/group")){
            if(catalog==null)throw new IOException("Maze servant catalog unavailable");
            JSONObject prepared=new JSONObject(state.toString());
            LocalEconomy.init(prepared,catalog);
            BarrierLabyrinth.Group group=BarrierLabyrinth.group(prepared,args,seed,now,cscRuleLevel(prepared));
            if(!group.state.toString().equals(state.toString()))commit(group.state);
            return group.response;
        }
        if(path.equals("/csc/normal/commit"))return cscNormalCommit(args,seed,now);
        if(path.equals("/csc/commit"))return cscInfo(state,seed,now);
        if(path.equals("/csc/bonus/commit"))return cscBonusCommit(seed,now);
        if(path.equals("/csc/reset")){
            JSONObject next=BarrierLabyrinth.reset(state,now);
            commit(next);
            return cscInfo(state,seed,now);
        }
        if(path.equals("/story/get"))return LocalStarterStory.get(state,seed);
        if(path.equals("/story/buy")){
            JSONObject next=new JSONObject(state.toString());
            byte[] result=LocalStarterStory.buy(next,args,seed,storyFixture);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(path.equals("/guide/get")){
            JSONObject next=new JSONObject(state.toString());
            LocalGuide.restoreFormerOpening(next);
            LocalGuide.restoreNamedStarter(next);
            byte[] result=LocalGuide.get(next);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(path.equals("/guide/update")){
            if(!state.optBoolean("roleCreated",false))
                throw new IOException("Role required for guide progress");
            JSONObject next=new JSONObject(state.toString());
            byte[] result=LocalGuide.update(next,args);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(path.equals("/activity/list/get")){
            JSONObject next=new JSONObject(state.toString());
            LocalDaily.requireRole(next,args);
            ProtoWire list=new ProtoWire();
            ActivityBanner.appendTo(list,next,now);
            LocalDaily.appendTo(list,next,now);
            if(!next.toString().equals(state.toString()))commit(next);
            return list.bytes();
        }
        if(path.equals("/activity/recharge/gain")){
            if(catalog==null)throw new IOException("Welfare-return catalog unavailable");
            JSONObject next=new JSONObject(state.toString());
            byte[] result=WelfareReturn.claim(next,catalog,args);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(catalog!=null && LocalDaily.claimRoute(path)){
            JSONObject next=new JSONObject(state.toString());
            byte[] result=LocalDaily.claim(next,catalog,path,args,now);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(catalog!=null && path.equals("/task/updatemore")){
            JSONObject next=new JSONObject(state.toString());
            if("1".equals(args.get("__verifiedGuildMember")))
                ProgressionTasks.recordGuildMembership(next);
            byte[] result=TaskRewards.claimBatch(next,catalog,args,now,
                "1".equals(args.get("__verifiedGuildMember")));
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(catalog!=null && (path.equals("/achievement/all")||path.equals("/achievement/update"))){
            JSONObject next=new JSONObject(state.toString());
            if("1".equals(args.get("__verifiedGuildMember")))
                ProgressionTasks.recordGuildMembership(next);
            byte[] result=path.equals("/achievement/all")?
                ProgressionTasks.bundled().achievementList(next,catalog,new byte[0]):
                ProgressionTasks.bundled().claimAchievement(next,catalog,args);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(catalog!=null && LocalMail.handles(path)){
            JSONObject next=new JSONObject(state.toString());
            boolean monthlyMail=GiftShop.bundled().advanceMonthCards(next,catalog,now);
            LocalMail.Action action=LocalMail.respond(next,catalog,path,args,System.currentTimeMillis());
            if(action.changed||monthlyMail)commit(next);
            return action.response;
        }
        if(catalog!=null && (path.equals("/shop/allShopSet") ||
                             path.equals("/shop/getSetData"))){
            JSONObject next=new JSONObject(state.toString());
            OriginalShop.Action exchanges=OriginalShop.bundled().respond(next,catalog,path,args,seed,now);
            GiftShop.Action gifts=GiftShop.bundled().respond(
                next,catalog,path,args,exchanges.response,now);
            VipShop.Action caph=VipShop.bundled().respond(
                next,catalog,path,args,gifts.response,now);
            ResourceShop.Action resources=ResourceShop.bundled().respond(
                next,catalog,path,args,caph.response,now);
            if(exchanges.changed||gifts.changed||caph.changed||resources.changed)commit(next);
            return resources.response;
        }
        if(catalog!=null && path.equals("/shop/buy") && GiftShop.giftPurchase(args)){
            JSONObject next=new JSONObject(state.toString());
            GiftShop.Action action=GiftShop.bundled().respond(next,catalog,path,args,seed,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(catalog!=null && path.equals("/shop/buy") && OriginalShop.purchase(args)){
            JSONObject next=new JSONObject(state.toString());
            OriginalShop.Action action=OriginalShop.bundled().respond(
                next,catalog,path,args,seed,now);
            if(action.changed){
                LocalDaily.recordShopPurchase(next,args,now);
                commit(next);
            }
            return action.response;
        }
        if(catalog!=null && path.equals("/shop/buy") && VipShop.purchase(args)){
            JSONObject next=new JSONObject(state.toString());
            VipShop.Action action=VipShop.bundled().respond(
                next,catalog,path,args,seed,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(catalog!=null && path.equals("/shop/buy") && ResourceShop.purchase(args)){
            JSONObject next=new JSONObject(state.toString());
            ResourceShop.Action action=ResourceShop.bundled().respond(
                next,catalog,path,args,seed,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(catalog!=null && path.equals("/shop/refresh") && ResourceShop.refresh(args)){
            JSONObject next=new JSONObject(state.toString());
            ResourceShop.Action action=ResourceShop.bundled().respond(
                next,catalog,path,args,seed,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(catalog!=null && path.equals("/shop/refresh")){
            JSONObject next=new JSONObject(state.toString());
            OriginalShop.Action action=OriginalShop.bundled().respond(
                next,catalog,path,args,seed,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(catalog!=null && RecycleStore.handles(path)){
            JSONObject next=new JSONObject(state.toString());
            RecycleStore recycle=RecycleStore.bundled();
            byte[] result=path.endsWith("/get")?recycle.list(next,catalog):
                recycle.sell(next,catalog,args);
            if(!next.toString().equals(state.toString()))commit(next);
            return result;
        }
        if(VipSystem.handles(path)){
            JSONObject next=new JSONObject(state.toString());
            VipSystem.Action action=VipSystem.respond(next,catalog,path,args,now);
            if(action.changed)commit(next);
            return action.response;
        }
        if(path.equals("/fashion/select")){
            if(catalog==null || !state.optBoolean("roleCreated",false))
                throw new IOException("Created role and fashion catalog required");
            String raw=args.get("fashioncardid");
            if(raw==null || !raw.matches("[1-9][0-9]{0,18}"))
                throw new IOException("Invalid fashioncardid");
            long id;
            try{id=Long.parseLong(raw);}catch(NumberFormatException e){
                throw new IOException("Invalid fashioncardid",e);
            }
            if(!catalog.getJSONObject("fashions").has(raw))
                throw new IOException("Unknown fashioncardid");
            if(!CosmeticUnlocks.ownsFashion(state,id))
                throw new IOException("Fashion is not unlocked");
            if(state.optLong("curFashion",CosmeticUnlocks.STARTER_FASHION)!=id){
                JSONObject next=new JSONObject(state.toString());
                next.put("curFashion",id);
                commit(next);
            }
            return new ProtoWire().text(1,"ok").bytes();
        }
        if(path.equals("/combat/role/info")||path.equals("/challenge/combat/role/info")){
            if(path.equals("/challenge/combat/role/info") &&
                StoneSlateBattle.contains(state.optLong("activeStage",0)))
                return StoneSlateBattle.bundled().role(state,args,seed,catalog);
            JSONObject next=new JSONObject(state.toString());
            CosmeticUnlocks.rememberFashion(next,catalog,args);
            if(path.equals("/challenge/combat/role/info")){
                // GetRestrictedRoleInfoLogic sends the original NetMsgField
                // names svcardids/wpids. rid is the current role ID, not the
                // stage; the scripted party is gated by our activeStage and
                // the original challengeid, not a client-supplied stage ID.
                Map<String,String> restricted=new LinkedHashMap<String,String>(args);
                if(args.containsKey("svcardids"))
                    restricted.put("servantcardids",args.get("svcardids"));
                if(args.containsKey("wpids"))
                    restricted.put("weaponids",args.get("wpids"));
                byte[] combat=LocalEconomy.challengeCombat(next,restricted,seed,catalog);
                if(!next.toString().equals(state.toString()))commit(next);
                return combat;
            }
            byte[] combat=LocalEconomy.basestationCombat(next,args,seed,catalog);
            if(stages!=null && catalog!=null &&
                (args.containsKey("servantcardids") || args.containsKey("svcardids"))){
                LocalEconomy.init(next,catalog);
                MainlineBattleRewards.rememberParty(next,args,now);
            }
            if(!next.toString().equals(state.toString()))commit(next);
            return combat;
        }
        if(catalog!=null && LocalEconomy.handles(path)){
            JSONObject next=new JSONObject(state.toString());
            if((path.equals("/task/all")||path.equals("/task/update"))&&
               "1".equals(args.get("__verifiedGuildMember")))
                ProgressionTasks.recordGuildMembership(next);
            byte[] response;
            if(path.equals("/task/update") && LocalDaily.dailyTask(args.get("jobid")))
                response=LocalDaily.claimTask(next,catalog,args,now,
                    "1".equals(args.get("__verifiedGuildMember")));
            else if(path.equals("/task/update") &&
                    ProgressionTasks.bundled().handlesJob(args.get("jobid")))
                response=ProgressionTasks.bundled().claim(next,catalog,args);
            else if(path.equals("/task/update") &&
                    MainStoryTasks.bundled().handlesJob(args.get("jobid")))
                response=MainStoryTasks.bundled().claim(next,catalog,args);
            else if(path.equals("/task/update") && CosmeticAchievements.handlesJob(args.get("jobid")))
                response=CosmeticAchievements.claim(next,catalog,args);
            else {
                response=LocalEconomy.respond(next,catalog,path,args,seed);
                if(path.equals("/task/all")){
                    response=LocalDaily.taskList(next,response,now);
                    response=CosmeticAchievements.taskList(next,catalog,response);
                    response=ProgressionTasks.bundled().taskList(next,catalog,response);
                    response=MainStoryTasks.bundled().taskList(next,response);
                }
                LocalDaily.observe(next,state,path,now);
            }
            if(!next.toString().equals(state.toString()))commit(next);
            return response;
        }
        if(path.equals("/role/create")){
            String name=args.get("name");
            JSONObject next=new JSONObject(state.toString());
            boolean firstCreate=!next.optBoolean("roleCreated",false);
            if(name!=null && !name.trim().isEmpty()){
                if(name.trim().getBytes(StandardCharsets.UTF_8).length>128)
                    throw new IOException("Invalid role name");
                // The original client sends a provisional name at creation,
                // then asks the player to name the character in GuideScenePanel.
                // Only /role/rename completes that guide step. Replayed create
                // requests must not overwrite the confirmed name.
                if(initialRoleLevel()!=1 || firstCreate)next.put("name",name.trim());
            }
            next.put("roleCreated",true);
            if(next.optLong("legacyRoleId",0)<=0)next.put("legacyRoleId",newRoleId());
            commit(next);
        }
        if(path.equals("/role/userlogin")){
            // Native RoleCreateAndLogin sends zoneid and userid in both modes.
            // Only isCreate=true omits roleid. A missing roleid on an existing
            // character is never permission to create or replace that role.
            if(!(state.opt("roleCreated") instanceof Boolean))
                throw new IOException("Role metadata migration required");
            requiredPositiveId(args,"userid");
            if(!"1".equals(args.get("zoneid")))throw new IOException("Invalid zoneid");
            if(args.containsKey("roleid")){
                long requested=requiredPositiveId(args,"roleid");
                long stored=state.optLong("legacyRoleId",0);
                if(!state.getBoolean("roleCreated") || stored<=0 || requested!=stored)
                    throw new IOException("Role ID does not belong to this account");
            }else{
                if(state.getBoolean("roleCreated") || state.has("legacyRoleId"))
                    throw new IOException("Role already exists or metadata is inconsistent");
                JSONObject next=new JSONObject(state.toString());
                next.put("roleCreated",true);
                next.put("legacyRoleId",newRoleId());
                commit(next);
            }
        }
        if(path.equals("/role/create")||path.equals("/role/userlogin")){
            // The descriptor uses RoleID=1, Time=2 (verified by the generator).
            ProtoWire login=ProtoWire.parse(seed).set(2,sync(now).bytes());
            if(state.optBoolean("roleCreated",false))login.set(1,state.getLong("legacyRoleId"));
            return login.bytes();
        }
        if(path.equals("/role/login")||path.equals("/time/sync"))return sync(now).bytes();
        if(path.equals("/timer/sync"))return ProtoWire.parse(seed).set(1,now).bytes();
        if(path.equals("/role/role")){
            if(catalog!=null){
                JSONObject next=new JSONObject(state.toString());
                if(GiftShop.bundled().advanceMonthCards(next,catalog,now))commit(next);
            }
            ProtoWire m=ProtoWire.parse(seed),r=ProtoWire.parse(m.data(1));
            long level=initialRoleLevel(),exp=state.getLong("exp");
            JSONObject costs=catalog==null?null:catalog.optJSONObject("roleLevels");
            while(costs!=null&&level<100){long cost=costs.optLong(String.valueOf(level),Long.MAX_VALUE);
                if(cost<=0||exp<cost)break;exp-=cost;level++;}
            r.text(111,state.getString("name")).set(105,state.getLong("gold")).set(106,exp).set(104,level);
            if(state.optBoolean("roleCreated",false))r.set(101,state.getLong("legacyRoleId"));
            r.set(102,VipSystem.level(state.optLong("vipExp",0)))
                .set(103,state.optLong("rmb",100000))
                .set(124,VipSystem.progress(state.optLong("vipExp",0)))
                .set(125,state.optLong("vipPoint",0));
            r.set(112,state.optLong("cscCurrency",0))
                .set(113,state.optLong("activeCurrencyRed",0))
                .set(114,state.optLong("activeCurrencyYellow",0))
                .set(115,state.optLong("activeCurrencyBlue",0))
                .set(116,state.optLong("activeCurrencyGreen",0))
                .set(120,state.optLong("guildCurrency",0))
                .set(126,state.optLong("drawCurrency",0))
                .set(135,state.optLong("recycleCurrency",0));
            r.set(128,state.optLong("storyCurrency",r.number(128,0)));
            r.set(129,state.optLong("activityStoryCurrency",r.number(129,0)));
            r.set(107,state.optLong("stamina",200))
                .set(108,StaminaRecovery.protocolTime(state,now))
                .set(121,state.optLong("activityStamina",200)).set(122,now);
            r.set(117,r.number(117,0)|StoneSlateBattle.challengeBits(state));
            r.set(118,selectedCosmetic("curHead",DEFAULT_HEAD)).set(119,selectedCosmetic("curHeadBox",DEFAULT_HEAD_BOX));
            JSONObject unlocked=state.optJSONObject("roleUnlocks");
            if(unlocked!=null)for(Iterator<String> it=unlocked.keys();it.hasNext();){
                String key=it.next();int field=Integer.parseInt(key);JSONObject entries=unlocked.getJSONObject(key);
                List<Long> flags=r.integers(field);
                for(Iterator<String> ei=entries.keys();ei.hasNext();){String ownedId=ei.next();
                    if(!ownedUnlock(entries,ownedId))continue;
                    int index=Integer.parseInt(ownedId)-1;
                    while(flags.size()<=index)flags.add(0L);flags.set(index,1L);}
                r.clear(field);for(long flag:flags)r.add(field,flag);
            }
            r.set(127,state.optLong("curBoard",1));
            if(catalog!=null)CosmeticUnlocks.applyStarterRole(state,catalog,r,m);
            GiftShop.bundled().monthCardRole(r,state,now);
            JSONObject runes=state.optJSONObject("fashionRunes");
            if(runes!=null)for(ProtoWire.Field f:m.fields)if(f.number==3&&f.type==2){
                ProtoWire fashion=ProtoWire.parse(f.data);
                org.json.JSONArray slots=runes.optJSONArray(String.valueOf(fashion.number(1,0)));
                if(slots!=null){ProtoWire layout=new ProtoWire();for(int i=0;i<slots.length();i++)layout.add(1,slots.getLong(i));fashion.set(3,layout.bytes());f.data=fashion.bytes();}
            }
            return m.set(1,r.bytes()).set(2,sync(now).data(6)).set(4,level).bytes();
        }
        if(path.equals("/level/getAllProgress")){
            if(stages!=null){
                byte[] progress=mainlineProgress(seed,stages);
                if(dailyBattles!=null)progress=dailyBattles.progress(progress,state,now,
                    stages.openAllMainline());
                if(weaponFurnace!=null){
                    ProtoWire all=ProtoWire.parse(progress);
                    weaponFurnace.appendProgress(all,state,WeaponFurnace.roleLevel(state,catalog),
                        now,stages.openAllMainline());
                    progress=all.bytes();
                }
                return StoneSlateBattle.bundled().progress(progress,state);
            }
            ProtoWire m=ProtoWire.parse(seed);
            for(ProtoWire.Field f:m.fields)if(f.number==1&&f.type==2){
                ProtoWire chap=ProtoWire.parse(f.data);
                for(ProtoWire.Field l:chap.fields)if(l.number==2&&l.type==2){
                    ProtoWire level=ProtoWire.parse(l.data);
                    if(level.number(1,0)==STAGE){
                        boolean passed=state.getInt("wins")>0;
                        level.set(2,passed?1:0).set(4,1).set(7,passed?1:0).set(6,state.getInt("attempts"));
                        level.set(3,state.getInt("stars")==3?1:0);
                        l.data=level.bytes();
                    }
                    if(level.number(1,0)==MAZE_TRIAL){
                        boolean passed=state.optInt("mazeWins")>0;
                        level.set(2,passed?1:0).set(4,1).set(7,passed?1:0).set(6,state.optInt("mazeAttempts"));
                        level.set(3,state.optInt("mazeStars")==3?1:0);
                        l.data=level.bytes();
                    }
                }
                f.data=chap.bytes();
            }
            return m.bytes();
        }
        if(path.equals("/level/sweep")){
            long sweepStage=StageSweep.positive(args,"instanceid");
            if(dailyBattles!=null && dailyBattles.supports(sweepStage)){
                DailyBattle.Settlement sweep=dailyBattles.sweep(state,catalog,args,now,
                    stages!=null && stages.openAllMainline());
                if(sweep.state!=state){
                    LocalDaily.observe(sweep.state,state,path,now);
                    commit(sweep.state);
                }
                return sweep.response;
            }
            if(weaponFurnace!=null && WeaponFurnace.contains(sweepStage)){
                WeaponFurnace.Settlement sweep=weaponFurnace.sweep(state,catalog,args,now,
                    stages!=null && stages.openAllMainline());
                if(sweep.next!=null){
                    LocalDaily.observe(sweep.next,state,path,now);
                    commit(sweep.next);
                }
                return sweep.response;
            }
            StageSweep.Result sweep=StageSweep.settle(state,stages,catalog,args,now);
            if(sweep.state!=state){
                ProgressionTasks.recordMainlineStaminaSpent(state,sweep.state);
                LocalDaily.observe(sweep.state,state,path,now);
                commit(sweep.state);
            }
            return sweep.response;
        }
        if(path.equals("/level/startBattle")||path.equals("/level/rebattle")){
            String requestedStage=args.get("instanceid");
            if(requestedStage!=null){
                if(!requestedStage.matches("[1-9][0-9]{0,18}"))
                    throw new IOException("Invalid battle instance ID");
                try{Long.parseLong(requestedStage);}catch(NumberFormatException invalid){
                    throw new IOException("Invalid battle instance ID",invalid);
                }
            }
            long stage=num(args,"instanceid",STAGE);
            if(StoneSlateBattle.contains(stage)){
                JSONObject next=StoneSlateBattle.bundled().begin(state,stage,args,now);
                if(next!=state)commit(next);
                return seed;
            }
            if(dailyBattles!=null && dailyBattles.supports(stage)){
                JSONObject next=dailyBattles.begin(state,stage,args,now,
                    stages!=null && stages.openAllMainline());
                if(next!=state)commit(next);
                return seed;
            }
            if(weaponFurnace!=null && WeaponFurnace.contains(stage)){
                String key=args.get("idempotency");
                if(key==null || key.isEmpty() || key.length()>128)
                    throw new IOException("Missing furnace start identity");
                // A native rebattle/resume carries no weapon field. Keep an
                // existing battle and its bound selection instead of starting
                // a second one or consuming another daily opportunity.
                if(state.optBoolean("active",false) && stage==state.optLong("activeStage",0))
                    return seed;
                if(!key.equals(state.optString("startKey")) || stage!=state.optLong("activeStage",0)){
                    weaponFurnace.validateStart(state,catalog,stage,
                        WeaponFurnace.roleLevel(state,catalog),now,
                        stages!=null && stages.openAllMainline(),args.get("wantweapon"));
                    JSONObject next=new JSONObject(state.toString());
                    next.put("startKey",key).put("active",true).put("activeStage",stage)
                        .put("battleStartedAt",now)
                        .put("furnaceBattleWeapon",args.get("wantweapon"));
                    weaponFurnace.recordStart(next,stage);
                    commit(next);
                }
                return seed;
            }
            if(stages==null){
                if(stage!=STAGE && stage!=MAZE_TRIAL && !TutorialBattleFixtures.handles(stage))
                    throw new IOException("Local encounter unavailable");
            }else if(stage!=MAZE_TRIAL && !TutorialBattleFixtures.handles(stage) &&
                    (!stages.supported(stage) || !stageUnlocked(stage,stages)))
                throw new IOException("Mainline encounter unavailable or locked");
            // Both the original basestation 1001 and the former local 1004
            // opening are one-time lessons. Failed attempts can be retried;
            // a settled victory must not replay the opening or award it twice.
            if((stage==3150001001L || stage==3150001004L) &&
                    state.optInt("tutorialWins_"+stage,0)>0 &&
                    !(state.optBoolean("active",false) &&
                      state.optLong("activeStage",0)==stage))
                throw new IOException("Opening tutorial already completed");
            String key=args.get("idempotency");
            if(key==null)throw new IOException("Missing start request identity");
            if(!key.equals(state.optString("startKey")) || stage!=state.optLong("activeStage",STAGE)){
                JSONObject next=new JSONObject(state.toString());next.put("startKey",key);
                if(stages!=null && stages.supported(stage)){
                    // Original Instance has separate entry and victory AP
                    // charges. Reserve enough for a successful run, then take
                    // only the entry charge now. A lost battle costs entry AP.
                    JSONObject stageRow=stages.stage(stage);
                    long entry=stageRow.optLong("staminaEnter",-1);
                    long victory=stageRow.optLong("staminaVictory",-1);
                    if(entry<0 || entry>100 || victory<1 || victory>100)
                        throw new IOException("Invalid mainline stamina cost");
                    long stamina=state.optLong("stamina",200);
                    if(stamina<Math.addExact(entry,victory))
                        throw new IOException("Insufficient stamina for mainline battle");
                    next.put("stamina",stamina-entry);
                    next.put("battleStaminaEnterPaid",entry);
                    next.put("battleStaminaStage",stage);
                }
                String counter=stage==MAZE_TRIAL?"mazeAttempts":
                    TutorialBattleFixtures.handles(stage)?"tutorialAttempts_"+stage:
                    stage==STAGE?"attempts":"mainlineAttempts";
                next.put("active",true);next.put("activeStage",stage);
                if(stage==MAZE_TRIAL){
                    BarrierLabyrinth.stageForRound(next.optInt("mazeRound",1));
                    next.put("battleMazeRound",next.optInt("mazeRound",1));
                }else if(stages!=null && stages.contains(stage)){
                    JSONObject progress=writableStageProgress(next,stage);
                    progress.put("attempts",progress.optInt("attempts",0)+1);
                }
                next.put(counter,next.optInt(counter)+1);next.put("battleStartedAt",now);
                if(stages!=null && stages.supported(stage)){
                    if(catalog==null)throw new IOException("Mainline reward catalog unavailable");
                    LocalEconomy.init(next,catalog);
                    MainlineBattleRewards.beginBattle(next,args,now);
                }
                next.remove("battleResponse");
                next.remove("guideBattleResponse");
                if(stages!=null && stages.supported(stage))
                    ProgressionTasks.recordMainlineStaminaSpent(state,next);
                commit(next);
            }
            return seed;
        }
        if(path.equals("/level/pushDailyProgress") && dailyBattles!=null &&
                dailyBattles.supports(state.optLong("dailyBattleStage",0))){
            DailyBattle.Settlement settlement=dailyBattles.settle(state,catalog,args,now);
            if(settlement.state!=state){
                LocalDaily.observe(settlement.state,state,path,now);
                commit(settlement.state);
            }
            return settlement.response;
        }
        if(path.equals("/level/pushMaterialProgress") && weaponFurnace!=null &&
                WeaponFurnace.contains(state.optLong("activeStage",0))){
            WeaponFurnace.Settlement settlement=weaponFurnace.settle(state,catalog,args,now);
            if(settlement.next!=null){
                LocalDaily.observe(settlement.next,state,path,now);
                commit(settlement.next);
            }
            return settlement.response;
        }
        if(path.equals("/level/chooseMaterials") && weaponFurnace!=null &&
                (state.has("furnacePendingChoiceItems") || state.has("furnaceChoiceResponse"))){
            WeaponFurnace.Settlement choice=weaponFurnace.chooseMaterials(state,catalog,args,now);
            if(choice.next!=null)commit(choice.next);
            return choice.response;
        }
        if(path.equals("/level/pushGuideProgress")){
            long stage=state.optLong("activeStage",0);
            if(!TutorialBattleFixtures.handles(stage))
                throw new IOException("No active tutorial encounter");
            if(args.containsKey("instanceid") &&
                    num(args,"instanceid",-1)!=stage)
                throw new IOException("Unexpected tutorial settlement stage");
            if(state.has("guideBattleResponse") && !state.optBoolean("active"))
                return Base64.decode(state.getString("guideBattleResponse"),Base64.DEFAULT);
            if(!state.optBoolean("active"))throw new IOException("No active tutorial battle");
            boolean win=guidePassed(args);
            // PushGuideStoryProgress.ParseProtoBuf passes BattleResult.ExtraInfo
            // to ProtocolManager before the next LessonTrigger event. Persisting
            // only /task/all would leave the current client session one job behind.
            JSONObject next=new JSONObject(state.toString());
            next.put("active",false);
            if(win){
                String key="tutorialWins_"+stage;
                next.put(key,next.optInt(key)+1);
                // Keep the original level-one tutorial from triggering catch-up
                // experience before all guide battles and naming are finished.
                next.put("exp",Math.addExact(next.getLong("exp"),5L));
            }
            next.put("lastSettlementAt",now);
            next.put("lastGuideBattle",new JSONObject(args));
            LocalDaily.observe(next,state,path,now);
            byte[] response=win?LocalDaily.guideBattleResult(next,stage,seed):seed;
            next.put("guideBattleResponse",Base64.encodeToString(response,Base64.NO_WRAP));
            commit(next);
            return response;
        }
        if(path.equals("/level/pushMainLineProgress")){
            long stage=num(args,"instanceid",0);
            boolean mainline=stages!=null && stages.supported(stage);
            if((!mainline && stage!=MAZE_TRIAL && stage!=STAGE) ||
                    (stages!=null && !mainline && stage!=MAZE_TRIAL) ||
                    stage!=state.optLong("activeStage",STAGE))
                throw new IOException("Unexpected settlement stage");
            if(state.has("battleResponse"))return Base64.decode(state.getString("battleResponse"),Base64.DEFAULT);
            if(!state.optBoolean("active"))throw new IOException("No active local battle");
            boolean win=num(args,"pass",0)==1;int stars=(int)Math.max(0,Math.min(3,num(args,"stars",0)));
            // The temporary one-enemy mainline profile is a guaranteed
            // three-star clear on victory. The preserved client often omits
            // stars entirely, so do not strand legitimate wins at zero.
            if(win && mainline && stages.openAllMainline())stars=3;
            boolean firstMainlineClear=win && mainline && stageProgress(state,stage).optInt("wins",0)==0;
            JSONObject next=new JSONObject(state.toString());next.put("active",false);
            if(mainline){
                JSONObject stageRow=stages.stage(stage);
                long entry=stageRow.optLong("staminaEnter",-1);
                long victory=stageRow.optLong("staminaVictory",-1);
                if(entry<0 || entry>100 || victory<1 || victory>100)
                    throw new IOException("Invalid mainline stamina cost");
                long paid=0;
                if(state.has("battleStaminaEnterPaid")){
                    if(state.optLong("battleStaminaStage",0)!=stage)
                        throw new IOException("Mismatched mainline entry payment");
                    paid=state.getLong("battleStaminaEnterPaid");
                    if(paid!=entry)throw new IOException("Invalid mainline entry payment");
                }
                // Older in-flight saves have no entry marker. Charge their
                // omitted entry once at settlement, while normal runs paid it
                // at start. A win then pays only the victory component.
                long due=Math.addExact(entry-paid,win?victory:0);
                long stamina=state.optLong("stamina",200);
                if(stamina<due)throw new IOException("Insufficient stamina at mainline settlement");
                next.put("stamina",stamina-due);
                next.remove("battleStaminaEnterPaid");
                next.remove("battleStaminaStage");
            }
            ProtoWire result=new ProtoWire().set(1,next.optLong("stamina",200))
                .set(2,StaminaRecovery.protocolTime(next,now)).set(4,new byte[0]);
            if(win){
                if(stage==MAZE_TRIAL){
                    next.put("mazeWins",next.optInt("mazeWins")+1);
                    next.put("mazeStars",Math.max(next.optInt("mazeStars"),stars));
                }else if(mainline){
                    JSONObject progress=writableStageProgress(next,stage);
                    boolean first=!progress.optBoolean("firstRewardClaimed",false) &&
                        progress.optInt("wins",0)==0;
                    progress.put("wins",progress.optInt("wins",0)+1);
                    progress.put("stars",Math.max(progress.optInt("stars",0),stars));
                    progress.put("firstRewardClaimed",true);
                    if(stage==STAGE){
                        next.put("wins",next.optInt("wins")+1);
                        next.put("stars",Math.max(next.optInt("stars"),stars));
                    }else next.put("mainlineWins",next.optInt("mainlineWins",0)+1);
                    if(first){
                        org.json.JSONArray rewards=stages.stage(stage).getJSONArray("rewards");
                        for(int i=0;i<rewards.length();i++){
                            JSONObject reward=rewards.getJSONObject(i);
                            if(reward.getInt("type")!=25)continue;
                            long amount=reward.optLong("value",0);
                            if(amount<=0 || amount>10000)throw new IOException("Invalid stage story reward");
                            next.put("storyCurrency",Math.addExact(next.optLong("storyCurrency",0),amount));
                            result.add(3,new ProtoWire().set(1,25).set(3,amount).set(4,amount).bytes());
                        }
                    }
                }else{
                    next.put("wins",next.optInt("wins")+1);
                    next.put("stars",Math.max(next.optInt("stars"),stars));
                }
                // Local catch-up begins only after the three preserved guide
                // battles and the original naming scene have completed.
                // These milestones are observable without guessing the
                // undocumented recID=99 request payload.
                if(stage==MAZE_TRIAL || mainline || stages==null && stage==STAGE){
                    // Use the conservative local clear reward; do not
                    // reintroduce the old 2,500-EXP catch-up grant.
                    long awardedExp=ROLE_EXP_PER_CLEAR;
                    next.put("gold",next.getLong("gold")+1000);next.put("exp",next.getLong("exp")+awardedExp);
                    result.set(5,awardedExp).add(3,new ProtoWire().set(1,13).set(3,1000).set(4,1000).bytes());
                }
                if(mainline){
                    // Battles started before this reward upgrade did not
                    // necessarily create an inventory yet.
                    LocalEconomy.init(next,catalog);
                    ProtoWire stageDrop=MainlineBattleRewards.grantListedDrop(next,catalog,
                        stages.stage(stage),stageProgress(state,stage).optLong("wins",0));
                    result.add(3,stageDrop.bytes());
                    ProtoWire servantExp=MainlineBattleRewards.grantPartyExperience(next,catalog);
                    if(servantExp!=null)result.add(3,servantExp.bytes());
                }
                if(stage==MAZE_TRIAL){
                    int round=next.optInt("battleMazeRound",1);
                    next.put("mazeRound",round+1);
                    double hp=1;
                    try{hp=Double.parseDouble(args.get("hp"));}catch(Exception ignored){}
                    next.put("mazeHP",Math.max(0.01,Math.min(1,hp)));
                    // The Android Lua writes an energy snapshot in its own sandbox.
                    // The HTTPS loopback adapter attaches that snapshot to settlement;
                    // only the currently active battle key may update this account.
                    if(next.optString("startKey").equals(args.get("energyStartKey"))){
                        int accepted=0;
                        for(Map.Entry<String,String> entry:args.entrySet()){
                            String k=entry.getKey();
                            if(!k.matches("mazeEnergy_[0-9]{1,18}"))continue;
                            if(++accepted>16)throw new IOException("Too many maze energy slots");
                            double power;
                            try{power=Double.parseDouble(entry.getValue());}catch(Exception ignored){continue;}
                            if(Double.isNaN(power)||Double.isInfinite(power))continue;
                            next.put(k,Math.max(0,Math.min(1000,power)));
                        }
                    }
                    if(round%3==0){
                        long supply=10000L;
                        next.put("gold",next.getLong("gold")+supply);
                        result.add(3,new ProtoWire().set(1,13).set(3,supply).set(4,supply).bytes());
                        next.put("mazeSupplyBoxes",next.optInt("mazeSupplyBoxes")+1);
                        // Local camp: apply once with the checkpoint, not on retries/login.
                        next.put("mazeHP",Math.min(1,next.optDouble("mazeHP",1)+0.30));
                        for(Iterator<String> it=next.keys();it.hasNext();){String k=it.next();
                            if(k.startsWith("mazeEnergy_"))next.put(k,Math.min(1000,next.optDouble(k,1000)+300));
                        }
                    }
                }
                if(firstMainlineClear || mainline && stages.openAllMainline()){
                    // PushStoryLineProgress immediately applies LevelEvent
                    // from BattleResult.ExtraInfo to the current Unity scene.
                    // In the open-all profile, reaffirm this cleared icon on
                    // every win; the native panel may close it while applying
                    // the battle result before it parses these level events.
                    ProtoWire extra=new ProtoWire(),open=new ProtoWire().text(1,"OpenLevel");
                    ProtoWire chapters=new ProtoWire().text(1,"NextChapter");
                    long sourceChapter=stages.chapterOf(stage);
                    java.util.HashSet<Long> chapterIds=new java.util.HashSet<Long>();
                    if(stages.openAllMainline())
                        open.add(2,Long.toString(stage).getBytes(StandardCharsets.UTF_8));
                    if(firstMainlineClear)for(long unlocked:stages.unlockedAfter(stage)){
                            open.add(2,Long.toString(unlocked).getBytes(StandardCharsets.UTF_8));
                            long destinationChapter=stages.chapterOf(unlocked);
                            if(destinationChapter!=sourceChapter && chapterIds.add(destinationChapter))
                                chapters.add(2,Long.toString(destinationChapter).getBytes(StandardCharsets.UTF_8));
                    }
                    if(open.fields.size()>1)extra.add(1,open.bytes());
                    if(chapters.fields.size()>1)extra.add(1,chapters.bytes());
                    result.set(4,extra.bytes());
                }
            }
            next.remove("activeBattleServants");
            next.put("lastSettlementAt",now);next.put("lastBattle",new JSONObject(args));
            ProgressionTasks.recordBattleKills(next,args);
            LocalDaily.observe(next,state,path,now);
            byte[] response=result.bytes();next.put("battleResponse",Base64.encodeToString(response,Base64.NO_WRAP));
            if(mainline)ProgressionTasks.recordMainlineStaminaSpent(state,next);
            commit(next);return response;
        }
        return seed;
    }
}
