package com.codex.witchweapon;

import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Original zero-cost recharge must refresh the native C.A.P.H model at once. */
public final class ResourceShopCaphSelfTest {
    private static void check(boolean yes,String why){if(!yes)throw new AssertionError(why);}

    private static Map<String,String> buy(long good,String requestId){
        Map<String,String> args=new HashMap<String,String>();
        args.put("setid","44000007");args.put("shopid","4502990003");
        args.put("goodsid",Long.toString(good));args.put("count","1");
        args.put("idempotency",requestId);return args;
    }

    private static ProtoWire checkCaph(byte[] response,JSONObject state)throws Exception{
        ProtoWire result=ProtoWire.parse(response);
        check("Buy Success".equals(new String(result.data(1),StandardCharsets.UTF_8)),
            "Recharge purchase did not succeed");
        ProtoWire info=ProtoWire.parse(result.data(4));
        check(info.fields.size()==1&&info.fields.get(0).number==100,
            "Recharge BuyResult is missing original ExtraInfo.VipExtra");
        ProtoWire vip=ProtoWire.parse(info.data(100));
        long exp=state.getLong("vipExp"),point=state.getLong("vipPoint");
        check(vip.number(1,-1)==0&&vip.number(2,-1)==0&&
            vip.number(3,-1)==VipSystem.level(exp)&&
            vip.number(4,-1)==VipSystem.progress(exp)&&
            vip.number(5,-1)==point,
            "Recharge C.A.P.H fields differ from the committed account");
        return result;
    }

    public static void main(String[] ignored)throws Exception{
        JSONObject responses=new JSONObject(new String(Files.readAllBytes(Paths.get(
            "D:/Project/魔女兵器在线版/legacy-server/resources/offline_responses.json")),
            StandardCharsets.UTF_8));
        JSONObject catalog=responses.getJSONObject("_catalog");
        ResourceShop shop=ResourceShop.bundled();
        JSONObject state=new JSONObject().put("roleCreated",true).put("legacyRoleId",918001L)
            .put("starterProfile",1).put("gold",1000).put("rmb",0)
            .put("vipExp",900).put("vipPoint",700);
        long now=1790380800L;
        Map<String,String> firstKey=buy(45990010,"recharge-caph-first");
        ResourceShop.Action first=shop.respond(state,catalog,"/shop/buy",firstKey,
            new byte[0],now);
        check(first.changed&&state.getLong("vipExp")==1314&&state.getLong("vipPoint")==1114,
            "First recharge did not add 414 C.A.P.H score exactly once");
        ProtoWire firstWire=checkCaph(first.response,state);
        check(ProtoWire.parse(firstWire.data(4)).data(100).length>0,
            "C.A.P.H refresh payload is empty");
        ResourceShop.Action second=shop.respond(state,catalog,"/shop/buy",
            buy(45990011,"recharge-caph-second"),new byte[0],now);
        check(second.changed&&state.getLong("vipExp")==2004&&state.getLong("vipPoint")==1804,
            "Second recharge did not add 690 C.A.P.H score exactly once");
        checkCaph(second.response,state);
        String committed=state.toString();
        ResourceShop.Action replay=shop.respond(state,catalog,"/shop/buy",firstKey,
            new byte[0],now);
        check(!replay.changed&&committed.equals(state.toString()),
            "Recharge retry changed C.A.P.H or inventory");
        ProtoWire retryWire=checkCaph(replay.response,state);
        check(!Arrays.equals(first.response,replay.response)&&
            Arrays.equals(firstWire.clear(4).bytes(),retryWire.clear(4).bytes()),
            "Recharge retry did not preserve original loot while refreshing absolute score");
        System.out.println("RESOURCE_SHOP_CAPH_OK");
    }
}
