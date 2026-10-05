package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/** Whole-page refresh and event windows, with synthetic isolated role saves. */
public final class StarShopRotationSelfTest {
    private static int checks;
    private static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
    private static JSONObject role()throws Exception {
        return new JSONObject().put("version",1).put("roleCreated",true).put("starterProfile",1)
            .put("legacyRoleId",54321).put("vipExp",23000).put("recycleCurrency",50000).put("exp",0);
    }
    private static ProtoWire sets(OriginalShop shop,JSONObject role,JSONObject catalog,long now)throws Exception {
        return ProtoWire.parse(shop.respond(role,catalog,"/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response);
    }
    private static ProtoWire set(ProtoWire all,long id)throws Exception {
        for(ProtoWire.Field field:all.fields)if(field.number==1&&field.type==2) {
            ProtoWire value=ProtoWire.parse(field.data);if(value.number(1,0)==id)return value;
        }
        throw new AssertionError("Missing set "+id);
    }
    private static long good(ProtoWire set)throws Exception {
        return ProtoWire.parse(ProtoWire.parse(set.data(5)).data(2)).number(1,0);
    }
    private static int count(ProtoWire set)throws Exception {
        int count=0;
        for(ProtoWire.Field f:set.fields)if(f.number==5&&f.type==2)
            for(ProtoWire.Field g:ProtoWire.parse(f.data).fields)if(g.number==2&&g.type==2)count++;
        return count;
    }
    private static JSONObject window(long id,long start,long end)throws Exception {
        return new JSONObject().put("timeId",id).put("start",start).put("end",end);
    }
    public static void main(String[] args)throws Exception {
        JSONObject catalog=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8)).getJSONObject("_catalog");
        JSONObject shelves=new JSONObject(new String(Files.readAllBytes(Paths.get(args[1])),StandardCharsets.UTF_8));
        long now=1790904000L;OriginalShop shop=OriginalShop.bundled();JSONObject role=role();
        ProtoWire before=sets(shop,role,catalog,now);int devices=0;
        for(long id=44000042;id<=44000046;id++)devices+=count(set(before,id));
        check(devices==5,"Cube shelf must expose exactly five devices, not its entire candidate pool");
        check(count(set(before,44000052))==6,"The six ordinary resources remain available");
        check(set(before,44000053).number(9,-1)==0&&count(set(before,44000053))==0,"No unscheduled cores");
        check(set(before,44000054).number(9,-1)==0&&count(set(before,44000054))==0,"No unscheduled costumes");
        Map<Long,Set<Long>> seen=new HashMap<Long,Set<Long>>();
        for(long id=44000047;id<=44000051;id++) {
            seen.put(id,new HashSet<Long>());seen.get(id).add(good(set(before,id)));
        }
        for(int round=1;round<=4;round++) {
            Map<String,String> request=new HashMap<String,String>();request.put("setid","44000047");request.put("idempotency","rotation-"+round);
            long balance=role.getLong("recycleCurrency");
            OriginalShop.Action action=shop.respond(role,catalog,"/shop/refresh",request,new byte[0],now);
            check(action.changed&&ProtoWire.parse(action.response).number(1,0)==44000047,"Refresh keeps the native single-SetInfo receipt");
            check(role.getLong("recycleCurrency")==balance-150,"Whole page costs one 150-fragment charge");
            ProtoWire after=sets(shop,role,catalog,now);
            for(long id=44000047;id<=44000051;id++) {
                ProtoWire slot=set(after,id);check(slot.number(8,-1)==round,"Every slot advances its refresh counter");
                check(count(slot)==1&&seen.get(id).add(good(slot)),"Every slot changes without repeating inside the day's five rotations");
            }
            check(java.util.Arrays.equals(after.bytes(),sets(shop,role,catalog,now).bytes()),"Opening a page does not reroll");
            OriginalShop.Action retry=shop.respond(role,catalog,"/shop/refresh",request,new byte[0],now);
            check(!retry.changed&&java.util.Arrays.equals(retry.response,action.response)&&role.getLong("recycleCurrency")==balance-150,"Refresh retry is idempotent");
        }
        Map<String,String> exhausted=new HashMap<String,String>();exhausted.put("setid","44000051");
        String unchanged=role.toString();boolean rejected=false;
        try{shop.respond(role,catalog,"/shop/refresh",exhausted,new byte[0],now);}catch(java.io.IOException expected){rejected=true;}
        check(rejected&&unchanged.equals(role.toString()),"A different slot cannot bypass the four-refresh page limit");
        ProtoWire tomorrow=sets(shop,role,catalog,now+86400);
        for(long id=44000047;id<=44000051;id++)check(set(tomorrow,id).number(8,-1)==0,"All refresh allowances reset together next China day");
        JSONObject active=new JSONObject(shelves.toString());
        active.getJSONObject("policy").put("starEventWindows",new JSONArray().put(window(1010008,now,now+100)));
        OriginalShop eventShop=new OriginalShop(active);
        check(count(set(sets(eventShop,role,catalog,now-1),44000053))==0,"Future event not open early");
        ProtoWire during=sets(eventShop,role,catalog,now);
        check(count(set(during,44000053))==1&&count(set(during,44000054))==4,"Only the active event's core and four costumes appear");
        ProtoWire core=set(during,44000053);Map<String,String> stale=new HashMap<String,String>();
        stale.put("setid","44000053");stale.put("shopid",""+ProtoWire.parse(core.data(5)).number(1,0));
        stale.put("goodsid",""+good(core));stale.put("count","1");
        unchanged=role.toString();OriginalShop.Action closed=eventShop.respond(role,catalog,"/shop/buy",stale,new byte[0],now+100);
        check(!closed.changed&&unchanged.equals(role.toString()),"Cached expired event offer cannot charge or grant");
        check(count(set(sets(eventShop,role,catalog,now+100),44000053))==0,"End time is exclusive");
        StarShopEvents events=new StarShopEvents(active);
        ProtoWire times=ProtoWire.parse(CaphActivityAccess.timeData(new byte[0],now,events));
        for(ProtoWire.Field f:times.fields)if(f.number==1&&f.type==2) {
            ProtoWire e=ProtoWire.parse(f.data);if(e.number(1,0)!=1010008)continue;
            ProtoWire clock=ProtoWire.parse(e.data(2));
            check(clock.number(1,0)==now&&clock.number(2,0)==now+100,"Native clock exactly matches the configured product window");
        }
        for(JSONObject bad:new JSONObject[]{window(1010008,0,now),window(999,now,now+1),window(1010008,now,now)}) {
            JSONObject invalid=new JSONObject(active.toString());invalid.getJSONObject("policy").put("starEventWindows",new JSONArray().put(bad));
            rejected=false;try{new StarShopEvents(invalid);}catch(java.io.IOException expected){rejected=true;}
            check(rejected,"Invalid event config is rejected");
        }
        System.out.println("StarShopRotationSelfTest: "+checks+" checks passed");
    }
}
