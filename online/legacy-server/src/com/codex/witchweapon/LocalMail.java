package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.text.SimpleDateFormat;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TimeZone;
import java.util.regex.Pattern;

/**
 * Original Mailmod wire contract backed by one account's atomic LocalSave.
 * All methods are called while holding the account's LocalSave monitor.
 * The caller passes a copied save for mutations and commits it once after
 * this class returns; an exception must never commit a partial reward.
 */
final class LocalMail {
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final Pattern UUID_V4 = Pattern.compile(
        "[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}");
    private static final Pattern MAIL_ID = Pattern.compile("[1-9][0-9]{0,18}");
    private static final Set<String> SEND_KEYS = new HashSet<String>(Arrays.asList(
        "expectedRevision","requestId","reason","title","sender","content","attachments"));
    private static final Set<String> ATTACHMENT_KEYS = new HashSet<String>(
        Arrays.asList("type","id","count"));
    private static final int MAX_PENDING = 200;
    private static final int MAX_SEND_REQUESTS = 50000;
    private static final int MAX_PROCESSED = 50000;
    private LocalMail() {}

    static boolean handles(String path) {
        return path.equals("/mail/fetch") || path.equals("/mail/getAttachAndDelete")
            || path.equals("/mail/deleteMails") || path.equals("/mail/updateMailState")
            || path.equals("/mail/updateSpecialMailState");
    }

    static final class Action {
        final byte[] response;
        final boolean changed;
        Action(byte[] response,boolean changed) {
            this.response=response;this.changed=changed;
        }
    }
    static final class Delivery {
        final String id;
        final boolean duplicate;
        Delivery(String id,boolean duplicate){this.id=id;this.duplicate=duplicate;}
        String response(long revision) throws Exception {
            JSONObject value=new JSONObject();
            value.put("id",id);
            value.put("revision",Long.toString(revision));
            value.put("duplicate",duplicate);
            return value.toString();
        }
    }
    private static final class Attachment {
        final int type;
        final long id,count;
        Attachment(int type,long id,long count){this.type=type;this.id=id;this.count=count;}
        JSONObject json() throws Exception {
            return new JSONObject().put("type",type).put("id",id).put("count",count);
        }
        ProtoWire wire() {
            // Lootmod.LootObject: Type=1, id=2, Value=3, Num=4.
            return new ProtoWire().set(1,type).set(2,id).set(3,count).set(4,count);
        }
    }

    private static boolean text(String value,int min,int max,int maxBytes,boolean multiline) {
        if(value==null || value.codePointCount(0,value.length())<min ||
                value.codePointCount(0,value.length())>max ||
                value.getBytes(StandardCharsets.UTF_8).length>maxBytes)return false;
        int first=value.codePointAt(0),last=value.codePointBefore(value.length());
        if(Character.isWhitespace(first)||Character.isSpaceChar(first)||
                Character.isWhitespace(last)||Character.isSpaceChar(last))return false;
        for(int i=0;i<value.length();) {
            int cp=value.codePointAt(i);
            if(cp=='<'||cp=='>'||Character.getType(cp)==Character.FORMAT ||
                    (cp>=0xD800&&cp<=0xDFFF) ||
                    (Character.isISOControl(cp) && !(multiline && cp=='\n')))
                return false;
            i+=Character.charCount(cp);
        }
        return true;
    }
    private static long strictLong(Object value,long minimum,long maximum) throws LocalSave.AdminValidation {
        if(!(value instanceof Number) || !value.toString().matches("(?:0|[1-9][0-9]{0,18})"))
            throw new LocalSave.AdminValidation("Invalid mail attachment number");
        long number;
        try{number=Long.parseLong(value.toString());}
        catch(NumberFormatException e){throw new LocalSave.AdminValidation("Invalid mail attachment number");}
        if(number<minimum||number>maximum)throw new LocalSave.AdminValidation("Mail attachment outside limit");
        return number;
    }
    private static List<Attachment> parseAttachments(String raw,JSONObject catalog)
            throws LocalSave.AdminValidation {
        if(raw==null || raw.getBytes(StandardCharsets.UTF_8).length>2048)
            throw new LocalSave.AdminValidation("Invalid mail attachments");
        JSONArray input;
        try{input=new JSONArray(raw);}
        catch(Exception e){throw new LocalSave.AdminValidation("Invalid mail attachments");}
        if(input.length()>5)throw new LocalSave.AdminValidation("Too many mail attachments");
        List<Attachment> output=new ArrayList<Attachment>();
        Set<String> unique=new HashSet<String>();
        for(int i=0;i<input.length();i++) {
            JSONObject object=input.optJSONObject(i);
            if(object==null || object.length()!=3)
                throw new LocalSave.AdminValidation("Invalid mail attachment");
            for(java.util.Iterator<String> keys=object.keys();keys.hasNext();)
                if(!ATTACHMENT_KEYS.contains(keys.next()))
                    throw new LocalSave.AdminValidation("Unknown mail attachment field");
            int type=(int)strictLong(object.opt("type"),0,100);
            long id=strictLong(object.opt("id"),0,Long.MAX_VALUE);
            long maximum=type==13?1000000:type==98?100000:999;
            long count=strictLong(object.opt("count"),1,maximum);
            if(type==13||type==98) {
                if(id!=0)throw new LocalSave.AdminValidation("Currency mail attachment ID must be zero");
            }else if(type==2||type==3) {
                String group=type==2?"equips":"items";
                JSONObject definitions=catalog.optJSONObject(group);
                if(id==0 || definitions==null || !definitions.has(Long.toString(id)))
                    throw new LocalSave.AdminValidation("Unknown mail attachment ID");
            }else throw new LocalSave.AdminValidation("Unsupported mail attachment type");
            if(!unique.add(type+":"+id))
                throw new LocalSave.AdminValidation("Duplicate mail attachment");
            output.add(new Attachment(type,id,count));
        }
        return output;
    }
    private static String digest(String reason,String title,String sender,String content,List<Attachment> attachments)
            throws Exception {
        StringBuilder canonical=new StringBuilder();
        for(String part:new String[]{reason,title,sender,content})
            canonical.append(part.length()).append(':').append(part);
        canonical.append(attachments.size()).append(':');
        for(Attachment a:attachments)
            canonical.append(a.type).append(',').append(a.id).append(',').append(a.count).append(';');
        byte[] bytes=MessageDigest.getInstance("SHA-256").digest(
            canonical.toString().getBytes(StandardCharsets.UTF_8));
        StringBuilder hex=new StringBuilder(64);
        for(byte b:bytes)hex.append(String.format(Locale.ROOT,"%02x",b&255));
        return hex.toString();
    }
    private static JSONObject requests(JSONObject save) throws IOException {
        Object value=save.opt("mailSendRequests");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid mail request ledger");
        return (JSONObject)value;
    }
    private static JSONArray mailbox(JSONObject save) throws IOException {
        Object value=save.opt("mailbox");
        if(value==null)return new JSONArray();
        if(!(value instanceof JSONArray))throw new IOException("Invalid mailbox");
        return (JSONArray)value;
    }
    private static JSONObject processed(JSONObject save) throws IOException {
        Object value=save.opt("mailProcessed");
        if(value==null)return new JSONObject();
        if(!(value instanceof JSONObject))throw new IOException("Invalid mail process ledger");
        return (JSONObject)value;
    }
    private static String newMailId(JSONArray mails,JSONObject sent,JSONObject processed) throws Exception {
        for(int tries=0;tries<100;tries++) {
            String candidate=Long.toString(RANDOM.nextLong()&Long.MAX_VALUE);
            if(candidate.equals("0")||processed.has(candidate))continue;
            boolean found=false;
            for(int i=0;i<mails.length();i++)if(candidate.equals(mails.getJSONObject(i).optString("id")))found=true;
            for(java.util.Iterator<String> keys=sent.keys();keys.hasNext();)
                if(candidate.equals(sent.optJSONObject(keys.next()).optString("id")))found=true;
            if(!found)return candidate;
        }
        throw new IllegalStateException("Mail ID generator exhausted");
    }

    static Delivery deliver(JSONObject save,JSONObject catalog,Map<String,String> args,long revision,long nowMillis)
            throws Exception {
        if(args.size()!=SEND_KEYS.size() || !args.keySet().equals(SEND_KEYS))
            throw new LocalSave.AdminValidation("Invalid mail send fields");
        String requestId=args.get("requestId"),reason=args.get("reason"),title=args.get("title");
        String sender=args.get("sender"),content=args.get("content");
        if(requestId==null||!UUID_V4.matcher(requestId).matches()||
                !text(reason,1,200,512,false)||!text(title,1,60,256,false)||
                !text(sender,1,24,128,false)||!text(content,1,1000,4096,true))
            throw new LocalSave.AdminValidation("Invalid mail send content");
        List<Attachment> attachments=parseAttachments(args.get("attachments"),catalog);
        String hash=digest(reason,title,sender,content,attachments);
        JSONObject sent=requests(save);
        if(sent.has(requestId)) {
            JSONObject previous=sent.optJSONObject(requestId);
            if(previous==null || !hash.equals(previous.optString("digest")))
                throw new LocalSave.AdminConflict();
            String id=previous.optString("id");
            if(!MAIL_ID.matcher(id).matches())throw new IOException("Invalid mail request ledger ID");
            return new Delivery(id,true);
        }
        String expected=args.get("expectedRevision");
        if(expected==null || !expected.matches("(?:0|[1-9][0-9]{0,18})"))
            throw new LocalSave.AdminValidation("Invalid expected revision");
        long desired;
        try{desired=Long.parseLong(expected);}
        catch(NumberFormatException e){throw new LocalSave.AdminValidation("Invalid expected revision");}
        if(desired!=revision)throw new LocalSave.AdminConflict();
        JSONArray mails=mailbox(save);
        if(mails.length()>=MAX_PENDING || sent.length()>=MAX_SEND_REQUESTS)
            throw new LocalSave.AdminValidation("Mail storage limit reached");
        JSONObject done=processed(save);
        String id=newMailId(mails,sent,done);
        JSONArray gifts=new JSONArray();
        for(Attachment gift:attachments)gifts.put(gift.json());
        JSONObject mail=new JSONObject();
        mail.put("id",id).put("title",title).put("sender",sender).put("content",content)
            .put("receivedAt",nowMillis).put("readed",false).put("attachments",gifts);
        mails.put(mail);
        sent.put(requestId,new JSONObject().put("id",id).put("digest",hash));
        save.put("mailbox",mails).put("mailSendRequests",sent);
        return new Delivery(id,false);
    }
    /** Queue one original month-card chest as claimable mail. The account
     * transaction also advances lastGrantDay, so login and fetch retries cannot
     * enqueue the same calendar day's reward again, even after it was claimed.
     * A full mailbox leaves the day due for a later request.
     */
    static boolean queueMonthCard(JSONObject save,JSONObject catalog,long cardId,long chestId,
                                  long grantDay,long nowMillis) throws Exception {
        if(cardId!=1 && cardId!=6 || chestId!=(cardId==1?40950003L:40950029L))
            throw new IOException("Unknown monthly-card chest");
        JSONArray mails=mailbox(save);
        if(mails.length()>=MAX_PENDING)return false;
        JSONObject chest=catalog.getJSONObject("items").getJSONObject(Long.toString(chestId));
        if(chest.getInt("item_type")!=9 || chest.getInt("item_sub_type")!=5)
            throw new IOException("Monthly reward is not an original chest");
        JSONArray rewards=chest.getJSONArray("rewards"),attachmentJson=new JSONArray();
        if(rewards.length()<1||rewards.length()>5)
            throw new IOException("Invalid monthly reward count");
        for(int i=0;i<rewards.length();i++) {
            JSONObject reward=rewards.getJSONObject(i);
            int type=reward.getInt("type");
            if(type!=3&&type!=13&&type!=99)
                throw new IOException("Unsupported monthly mail reward type");
            long id=reward.getLong("id"),units=reward.getLong("count");
            long value=reward.getLong("value"),count=units>0?units:value;
            if(count<=0 || (type!=3&&id!=0) || (type!=3&&units!=0) ||
                    (type==3&&id<=0))
                throw new IOException("Invalid monthly mail reward");
            attachmentJson.put(new JSONObject().put("type",type==99?98:type)
                .put("id",id).put("count",count));
        }
        List<Attachment> attachments=parseAttachments(attachmentJson.toString(),catalog);
        JSONArray gifts=new JSONArray();
        for(Attachment attachment:attachments)gifts.put(attachment.json());
        String title=cardId==1?"普通月卡每日奖励":"高级月卡每日奖励";
        String date=LocalDate.ofEpochDay(grantDay).toString();
        String content=date+" 的月卡奖励已送达，请领取邮件附件。";
        String id=newMailId(mails,requests(save),processed(save));
        mails.put(new JSONObject().put("id",id).put("title",title)
            .put("sender","系统").put("content",content)
            .put("receivedAt",nowMillis).put("readed",false)
            .put("attachments",gifts).put("source","monthCard")
            .put("cardId",cardId).put("grantDay",grantDay));
        save.put("mailbox",mails);
        return true;
    }
    static JSONObject catalog(JSONObject source) throws Exception {
        JSONObject output=new JSONObject();
        JSONArray entries=new JSONArray();
        entries.put(new JSONObject().put("type",13).put("id",0).put("name","金币").put("maxCount",1000000));
        entries.put(new JSONObject().put("type",98).put("id",0).put("name","钻石").put("maxCount",100000));
        for(int type:new int[]{3,2}) {
            JSONObject definitions=source.getJSONObject(type==3?"items":"equips");
            List<Long> ids=new ArrayList<Long>();
            for(java.util.Iterator<String> keys=definitions.keys();keys.hasNext();)
                ids.add(Long.parseLong(keys.next()));
            java.util.Collections.sort(ids);
            for(long id:ids) {
                long cap=type==3?Math.min(999,Math.max(1,definitions.getJSONObject(Long.toString(id)).optLong("max_stack",999))):999;
                entries.put(new JSONObject().put("type",type).put("id",id)
                    .put("name",(type==3?"物品 ":"装备 ")+id).put("maxCount",cap));
            }
        }
        output.put("version",1).put("entries",entries);
        return output;
    }
    private static List<String> mailIds(Map<String,String> args) throws IOException {
        String raw=args.get("mailids");
        if(raw==null||raw.isEmpty()||raw.length()>1024)
            throw new IOException("Invalid mail IDs");
        for(String key:args.keySet())
            if(!key.equals("mailids")&&!Arrays.asList("roleid","enc","idempotency","hwid","time","sign").contains(key))
                throw new IOException("Unknown mail form field");
        String[] parts=raw.split("[,|;]",-1);
        if(parts.length<1||parts.length>50)throw new IOException("Invalid mail batch size");
        List<String> ids=new ArrayList<String>();
        Set<String> seen=new HashSet<String>();
        for(String id:parts){
            if(!MAIL_ID.matcher(id).matches()||!seen.add(id))
                throw new IOException("Invalid or duplicate mail ID");
            ids.add(id);
        }
        return ids;
    }
    private static void award(JSONObject save,JSONObject catalog,JSONObject mail) throws Exception {
        JSONArray gifts=mail.getJSONArray("attachments");
        if(gifts.length()==0)return;
        // Existing offline saves start with a very full bag. Never silently
        // truncate an awarded item at stackCap: keep the mail claimable instead.
        LocalEconomy.init(save,catalog);
        for(int i=0;i<gifts.length();i++) {
            JSONObject gift=gifts.getJSONObject(i);
            int type=gift.getInt("type");
            long id=gift.getLong("id"),count=gift.getLong("count");
            if(type==2||type==3){
                String bagKey=type==2?"equips":"items",key=Long.toString(id);
                JSONObject bag=save.getJSONObject(bagKey);
                long before=bag.optLong(key),cap=type==3?LocalEconomy.stackCap(catalog,key):9999;
                if(before<0 || before>cap || count>cap-before)
                    throw new IOException("Mail reward exceeds bag stack capacity");
            }
            JSONObject reward=new JSONObject().put("type",type).put("id",id)
                .put("value",count).put("count",count);
            LocalEconomy.grantItemReward(save,catalog,reward,1);
        }
        save.put("inventoryRevision",Math.addExact(save.optLong("inventoryRevision"),1));
    }
    private static String receiveTime(long millis) {
        SimpleDateFormat format=new SimpleDateFormat("yyyy-MM-dd HH:mm:ss",Locale.ROOT);
        format.setTimeZone(TimeZone.getTimeZone("Asia/Shanghai"));
        return format.format(new java.util.Date(millis));
    }
    private static byte[] detail(JSONObject mail) throws Exception {
        JSONArray gifts=mail.getJSONArray("attachments");
        ProtoWire result=new ProtoWire();
        result.text(1,mail.getString("id")).text(2,mail.getString("title"))
            .text(3,mail.getString("sender")).text(4,mail.getString("content"))
            .set(5,gifts.length()>0?1:0)
            .text(6,receiveTime(mail.getLong("receivedAt")))
            .text(7,"0").set(12,mail.optBoolean("readed",false)?1:0);
        for(int i=0;i<gifts.length();i++) {
            JSONObject gift=gifts.getJSONObject(i);
            result.add(9,new Attachment(gift.getInt("type"),gift.getLong("id"),gift.getLong("count")).wire().bytes());
        }
        return result.bytes();
    }
    static Action respond(JSONObject save,JSONObject catalog,String path,Map<String,String> args,long nowMillis)
            throws Exception {
        JSONArray mails=mailbox(save);
        if(path.equals("/mail/fetch")) {
            // Older offline callers omitted roleid; the original online
            // client includes it, so reject a mismatched supplied role.
            if(args.containsKey("roleid"))LocalDaily.requireRole(save,args);
            ProtoWire result=new ProtoWire();
            for(int i=mails.length()-1;i>=0;i--) {
                JSONObject mail=mails.getJSONObject(i);
                // MailResult field 1 is NormalMail. The original UI only
                // renders attachment controls for field 2 (SpecialMail).
                result.add(mail.getJSONArray("attachments").length()>0?2:1,detail(mail));
            }
            return new Action(result.bytes(),false);
        }
        if(!path.equals("/mail/getAttachAndDelete")&&!path.equals("/mail/deleteMails")&&
                !path.equals("/mail/updateMailState")&&!path.equals("/mail/updateSpecialMailState"))
            throw new IOException("Unknown mail route");
        // The original client sends roleid with every mail mutation. Bind it
        // to the authenticated account's created role before touching mail.
        LocalDaily.requireRole(save,args);
        List<String> ids=mailIds(args);
        JSONObject done=processed(save);
        if(path.equals("/mail/updateMailState")||path.equals("/mail/updateSpecialMailState")) {
            boolean changed=false;
            Set<String> requested=new HashSet<String>(ids);
            for(int i=0;i<mails.length();i++) {
                JSONObject mail=mails.getJSONObject(i);
                if(requested.remove(mail.getString("id")) && !mail.optBoolean("readed",false)) {
                    mail.put("readed",true);
                    changed=true;
                }
            }
            for(String id:requested)if(!done.has(id))throw new IOException("Unknown mail ID");
            return new Action(new ProtoWire().text(1,"ok").bytes(),changed);
        }
        JSONArray kept=new JSONArray();
        List<JSONObject> selected=new ArrayList<JSONObject>();
        Set<String> requested=new HashSet<String>(ids);
        for(int i=0;i<mails.length();i++) {
            JSONObject mail=mails.getJSONObject(i);
            if(requested.contains(mail.getString("id")))selected.add(mail);
            else kept.put(mail);
        }
        for(String id:ids){
            boolean found=false;
            for(JSONObject mail:selected)if(id.equals(mail.getString("id")))found=true;
            if(!found&&!done.has(id))throw new IOException("Unknown mail ID");
        }
        if(path.equals("/mail/deleteMails"))
            for(JSONObject mail:selected)if(mail.getJSONArray("attachments").length()>0)
                throw new IOException("Unclaimed attachments cannot be discarded");
        if(done.length()+selected.size()>MAX_PROCESSED)
            throw new IOException("Mail processing ledger full");
        if(path.equals("/mail/getAttachAndDelete"))
            for(JSONObject mail:selected)award(save,catalog,mail);
        for(JSONObject mail:selected)done.put(mail.getString("id"),nowMillis);
        if(!selected.isEmpty())save.put("mailbox",kept).put("mailProcessed",done);
        return new Action(new ProtoWire().text(1,"ok").bytes(),!selected.isEmpty());
    }
}
