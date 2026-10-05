package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;

/** Isolated mail-contract checks. This class never opens a real player save. */
public final class MailSelfTest {
    private static void yes(boolean condition,String message) {
        if(!condition)throw new AssertionError(message);
    }
    private static JSONObject catalog() throws Exception {
        JSONObject item=new JSONObject().put("max_stack",99);
        return new JSONObject()
            .put("items",new JSONObject().put("40130001",item))
            .put("equips",new JSONObject().put("1411001",new JSONObject()))
            .put("servants",new JSONObject());
    }
    private static JSONObject player() throws Exception {
        return new JSONObject()
            .put("version",1).put("name","mail-test").put("roleCreated",true)
            .put("legacyRoleId",123L).put("gold",10L).put("rmb",20L)
            .put("ownedServants",new JSONObject())
            .put("items",new JSONObject().put("40130001",10L))
            .put("equips",new JSONObject().put("1411001",0L));
    }
    private static Map<String,String> send(String id,String revision,String attachments) {
        Map<String,String> args=new LinkedHashMap<String,String>();
        args.put("expectedRevision",revision);
        args.put("requestId",id);
        args.put("reason","test grant");
        args.put("title","测试物资");
        args.put("sender","系统管理员");
        args.put("content","欢迎回到新丰洲\n请在邮件内领取。");
        args.put("attachments",attachments);
        return args;
    }
    private static Map<String,String> mailids(String id) {
        Map<String,String> args=new LinkedHashMap<String,String>();
        args.put("roleid","123");
        args.put("mailids",id);
        return args;
    }
    private static void rejected(RunnableWithError action,Class<? extends Exception> expected)
            throws Exception {
        try{action.run();throw new AssertionError("Expected "+expected.getName());}
        catch(Exception ex){if(!expected.isInstance(ex))throw ex;}
    }
    private interface RunnableWithError {void run() throws Exception;}
    public static void main(String[] args) throws Exception {
        JSONObject catalog=catalog(),save=player();
        String idempotency="11111111-1111-4111-8111-111111111111";
        String gifts="[{\"type\":13,\"id\":0,\"count\":5},{\"type\":98,\"id\":0,\"count\":7},"
            +"{\"type\":3,\"id\":40130001,\"count\":3},{\"type\":2,\"id\":1411001,\"count\":1}]";
        Map<String,String> request=send(idempotency,"7",gifts);
        LocalMail.Delivery first=LocalMail.deliver(save,catalog,request,7,1700000000000L);
        yes(!first.duplicate && first.id.matches("[1-9][0-9]{0,18}"),"Unique numeric mail ID");
        JSONObject reply=new JSONObject(first.response(8));
        yes(reply.getString("id").equals(first.id) && reply.getString("revision").equals("8")
            && !reply.getBoolean("duplicate"),"Admin response types");
        LocalMail.Delivery same=LocalMail.deliver(save,catalog,request,8,1700000005000L);
        yes(same.duplicate && same.id.equals(first.id),"Retry should win before stale revision");
        yes(save.getJSONArray("mailbox").length()==1,"No duplicate delivery");
        Map<String,String> changed=send(idempotency,"8","[]");
        rejected(()->LocalMail.deliver(save,catalog,changed,8,1700000005000L),
            LocalSave.AdminConflict.class);
        Map<String,String> another=send("22222222-2222-4222-8222-222222222222","7","[]");
        rejected(()->LocalMail.deliver(save,catalog,another,8,1700000005000L),
            LocalSave.AdminConflict.class);

        LocalMail.Action fetch=LocalMail.respond(save,catalog,"/mail/fetch",
            new LinkedHashMap<String,String>(),1700000005000L);
        yes(!fetch.changed,"Fetch must be read only");
        ProtoWire result=ProtoWire.parse(fetch.response);
        yes(result.fields.size()==1 && result.fields.get(0).number==2,
            "Attachment mail must use MailResult.SpecialMail wire");
        ProtoWire detail=ProtoWire.parse(result.data(2));
        yes(new String(detail.data(1),StandardCharsets.UTF_8).equals(first.id),"MailDetail.MailID");
        yes(new String(detail.data(2),StandardCharsets.UTF_8).equals("测试物资"),"UTF-8 title");
        yes(detail.number(5,0)==1,"HaveAttach true");
        yes(new String(detail.data(6),StandardCharsets.UTF_8).startsWith("2023-"),"Time string");
        int lootCount=0;
        for(ProtoWire.Field field:detail.fields)if(field.number==9){
            ProtoWire loot=ProtoWire.parse(field.data);
            yes(loot.number(4,0)>0,"LootObject.Num");
            lootCount++;
        }
        yes(lootCount==4,"All supported attachments visible");

        JSONObject plainSave=player();
        String plainId=LocalMail.deliver(plainSave,catalog,send(
            "66666666-6666-4666-8666-666666666666","7","[]"),7,1700000005000L).id;
        ProtoWire plainResult=ProtoWire.parse(LocalMail.respond(plainSave,catalog,
            "/mail/fetch",mailids(plainId),1700000005000L).response);
        yes(plainResult.fields.size()==1 && plainResult.fields.get(0).number==1,
            "No-attachment mail must use MailResult.NormalMail wire");
        ProtoWire plainDetail=ProtoWire.parse(plainResult.data(1));
        yes(plainDetail.number(5,0)==0,"Normal mail has no attachment flag");
        for(ProtoWire.Field field:plainDetail.fields)
            yes(field.number!=9,"Normal mail has no LootObject");
        LocalMail.Action plainRead=LocalMail.respond(plainSave,catalog,
            "/mail/updateMailState",mailids(plainId),1700000005500L);
        yes(plainRead.changed && plainSave.getJSONArray("mailbox").getJSONObject(0)
            .getBoolean("readed"),"Original normal-mail read route works");

        String[] mutationRoutes={"/mail/updateMailState","/mail/updateSpecialMailState",
            "/mail/getAttachAndDelete","/mail/deleteMails"};
        for(String route:mutationRoutes){
            Map<String,String> missing=mailids(first.id);
            missing.remove("roleid");
            rejected(()->LocalMail.respond(save,catalog,route,missing,1700000005000L),
                LocalDaily.InvalidRequest.class);
            Map<String,String> foreign=mailids(first.id);
            foreign.put("roleid","456");
            rejected(()->LocalMail.respond(save,catalog,route,foreign,1700000005000L),
                LocalDaily.InvalidRequest.class);
        }
        Map<String,String> invalidField=mailids(first.id);
        invalidField.put("rid","123");
        rejected(()->LocalMail.respond(save,catalog,"/mail/updateMailState",invalidField,
            1700000005000L),java.io.IOException.class);
        Map<String,String> fetchWithRole=new LinkedHashMap<String,String>();
        fetchWithRole.put("roleid","456");
        rejected(()->LocalMail.respond(save,catalog,"/mail/fetch",fetchWithRole,
            1700000005000L),LocalDaily.InvalidRequest.class);
        fetchWithRole.put("roleid","123");
        yes(!LocalMail.respond(save,catalog,"/mail/fetch",fetchWithRole,
            1700000005000L).changed,"Fetch accepts matching online role");
        Map<String,String> observedForm=mailids(first.id);
        observedForm.put("enc","0");
        observedForm.put("idempotency","01234567890");
        observedForm.put("hwid","00000000000000000000000000000000");
        observedForm.put("time","1700000000");
        observedForm.put("sign","00000000000000000000000000000000");

        LocalMail.Action read=LocalMail.respond(save,catalog,"/mail/updateSpecialMailState",
            observedForm,1700000005500L);
        yes(read.changed && save.getJSONArray("mailbox").getJSONObject(0).getBoolean("readed"),
            "Original special-mail read route clears unread state");
        yes(!LocalMail.respond(save,catalog,"/mail/updateSpecialMailState",mailids(first.id),
            1700000005600L).changed,"Special read-state replay is harmless");

        rejected(()->LocalMail.respond(new JSONObject(save.toString()),catalog,
            "/mail/deleteMails",mailids(first.id),1700000006000L),java.io.IOException.class);
        JSONObject claimState=new JSONObject(save.toString());
        LocalMail.Action claimed=LocalMail.respond(claimState,catalog,
            "/mail/getAttachAndDelete",mailids(first.id),1700000006000L);
        yes(claimed.changed && new String(ProtoWire.parse(claimed.response).data(1),
            StandardCharsets.UTF_8).equals("ok"),"Claim CommonInfo");
        yes(claimState.getLong("gold")==15 && claimState.getLong("rmb")==27
            && claimState.getJSONObject("items").getLong("40130001")==13
            && claimState.getJSONObject("equips").getLong("1411001")==1,
            "All four gift types are applied once");
        yes(claimState.getJSONArray("mailbox").length()==0,"Claim removes mail");
        LocalMail.Action repeat=LocalMail.respond(claimState,catalog,
            "/mail/getAttachAndDelete",mailids(first.id),1700000007000L);
        yes(!repeat.changed && claimState.getLong("gold")==15,"Claim replay is harmless");

        JSONObject other=player();
        yes(LocalMail.respond(other,catalog,"/mail/fetch",
            new LinkedHashMap<String,String>(),1700000007000L).response.length==0,
            "Mailboxes are separate account states");
        rejected(()->LocalMail.respond(other,catalog,"/mail/getAttachAndDelete",
            mailids(first.id),1700000007000L),java.io.IOException.class);

        Map<String,String> badText=send("33333333-3333-4333-8333-333333333333","9","[]");
        badText.put("content","<color=red>inject</color>");
        rejected(()->LocalMail.deliver(other,catalog,badText,9,1700000007000L),
            LocalSave.AdminValidation.class);
        Map<String,String> badItem=send("44444444-4444-4444-8444-444444444444","9",
            "[{\"type\":3,\"id\":99999999,\"count\":1}]");
        rejected(()->LocalMail.deliver(other,catalog,badItem,9,1700000007000L),
            LocalSave.AdminValidation.class);

        JSONObject full=player().put("items",new JSONObject().put("40130001",99L));
        String blockedId=LocalMail.deliver(full,catalog,send(
            "55555555-5555-4555-8555-555555555555","9",
            "[{\"type\":3,\"id\":40130001,\"count\":1}]"),9,1700000007000L).id;
        JSONObject attempted=new JSONObject(full.toString());
        rejected(()->LocalMail.respond(attempted,catalog,"/mail/getAttachAndDelete",
            mailids(blockedId),1700000008000L),java.io.IOException.class);
        yes(full.getJSONArray("mailbox").length()==1 && full.getJSONObject("items")
            .getLong("40130001")==99,"Full bag preserves gift and inventory");

        JSONArray choices=LocalMail.catalog(catalog).getJSONArray("entries");
        yes(choices.length()==4,"Catalog exposes only valid gift IDs plus currencies");
        System.out.println("MAIL_SELF_TEST_OK");
    }
}
