package com.codex.witchweapon;

import org.json.JSONArray;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Original shelf selection, finite origin stock, discounts and batch debits. */
public final class OriginalShopCatalogSelfTest {
    private static int checks;
    private static final long NOW=1790942400L;
    private static void check(boolean b,String why){checks++;if(!b)throw new AssertionError(why);}
    private static JSONObject role(JSONObject catalog,int level)throws Exception{
        long exp=0;for(int i=1;i<level;i++)exp+=catalog.getJSONObject("roleLevels").getLong(""+i);
        return new JSONObject().put("version",1).put("roleCreated",true).put("starterProfile",1)
            .put("legacyRoleId",111).put("exp",exp).put("gold",10000000).put("rmb",100000)
            .put("activeCurrencyGreen",100000).put("guildCurrency",100000).put("cscCurrency",100000);
    }
    private static List<ProtoWire> children(ProtoWire w,int field)throws Exception{
        List<ProtoWire> r=new ArrayList<ProtoWire>();
        for(ProtoWire.Field f:w.fields)if(f.number==field&&f.type==2)r.add(ProtoWire.parse(f.data));
        return r;
    }
    private static ProtoWire set(OriginalShop store,JSONObject state,JSONObject catalog,long id,long now)throws Exception{
        byte[] all=store.respond(state,catalog,"/shop/allShopSet",new HashMap<String,String>(),new byte[0],now).response;
        for(ProtoWire w:children(ProtoWire.parse(all),1))if(w.number(1,0)==id)return w;
        throw new AssertionError("Missing set "+id);
    }
    private static Map<String,String> buy(long set,long shop,long good,int count){
        Map<String,String> r=new HashMap<String,String>();r.put("setid",""+set);r.put("shopid",""+shop);
        r.put("goodsid",""+good);r.put("count",""+count);return r;
    }
    private static String status(byte[] w)throws Exception{return new String(ProtoWire.parse(w).data(1),StandardCharsets.UTF_8);}
    private static int visibleCount(ProtoWire set)throws Exception{
        int n=0;for(ProtoWire sh:children(set,5))if(sh.number(3,0)==1)n+=children(sh,2).size();return n;
    }
    public static void main(String[] args)throws Exception{
        JSONObject catalog=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8)).getJSONObject("_catalog");
        OriginalShop store=OriginalShop.bundled();
        for(int level:new int[]{1,25,26,39,40,46,47,60,61,67,68,75,76,91,92,100}){
            JSONObject p=role(catalog,level);
            check(visibleCount(set(store,p,catalog,44000188L,NOW))==13,"Powder must show 13 original goods, not every level tier");
            int expected=level<=25?8:level<=46?10:5;
            check(visibleCount(set(store,p,catalog,44000016L,NOW))==expected,"Guild original level-band quantity at "+level);
        }
        JSONObject p=role(catalog,50);
        ProtoWire guild=set(store,p,catalog,44000016L,NOW);
        check(java.util.Arrays.equals(guild.bytes(),set(store,p,catalog,44000016L,NOW).bytes()),"Reopening must not reroll goods or discounts");
        boolean bought=false;
        for(ProtoWire sh:children(guild,5))if(sh.number(3,0)==1){
            check(sh.number(4,0)==-1,"Origin must not display shared daily count");
            for(ProtoWire g:children(sh,2)){
                check(g.number(3,-1)==1,"Guild origin stock must be one");
                check(g.number(4,0)==0||g.number(4,0)==1000,"Configured ten-percent discount");
                check(g.number(5,0)==(g.number(4,0)>0?1:0),"Original discount badge flag");
                if(!bought){
                    long before=p.getLong("guildCurrency"),cost=g.number(2,0)*(10000-g.number(4,0))/10000;
                    Map<String,String> req=buy(44000016L,sh.number(1,0),g.number(1,0),1);
                    check("Buy Success".equals(status(store.respond(p,catalog,"/shop/buy",req,new byte[0],NOW).response)),"Guild purchase");
                    check(p.getLong("guildCurrency")==before-cost,"Actual charge matches displayed discounted price");
                    check("Sold Out".equals(status(store.respond(p,catalog,"/shop/buy",req,new byte[0],NOW).response)),"Second purchase must be sold out");
                    check(p.getLong("guildCurrency")==before-cost,"Sold-out retry never debits");
                    bought=true;
                }
            }
        }
        check(bought,"Finite guild purchase exercised");
        JSONObject batch=role(catalog,1);
        ProtoWire powder=set(store,batch,catalog,44000188L,NOW);
        boolean batchBought=false;
        for(ProtoWire sh:children(powder,5))if(sh.number(3,0)==1&&sh.number(1,0)==4501060001L){
            ProtoWire g=children(sh,2).get(0);long balance=batch.getLong("activeCurrencyGreen");
            byte[] response=store.respond(batch,catalog,"/shop/buy",buy(44000188L,sh.number(1,0),g.number(1,0),3),new byte[0],NOW).response;
            check("Buy Success".equals(status(response)),"Three material units in one purchase");
            check(batch.getLong("activeCurrencyGreen")==balance-3*g.number(2,0),"Batch debit exact");
            ProtoWire loot=ProtoWire.parse(ProtoWire.parse(response).data(5));
            check(loot.number(3,0)==3&&loot.number(4,0)==3,"Batch grant/display exact");
            batchBought=true;
        }
        check(batchBought,"Batch stock fixture present");
        // A guaranteed policy exercises 1130 -> 1017 without relying on an
        // arbitrary real player's random shelf or changing any live account.
        JSONObject shelves=new JSONObject(new String(Files.readAllBytes(Paths.get(args[1])),StandardCharsets.UTF_8));
        shelves.put("guildOriginDiscount",new JSONObject().put("chanceBasisPoints",10000).put("discountBasisPoints",1000));
        OriginalShop guaranteed=new OriginalShop(shelves);
        boolean purple=false,example=false;int discounted=0,total=0;
        Map<Long,Long> equipment=new HashMap<Long,Long>();
        for(int i=0;i<shelves.getJSONArray("sets").length();i++){
            JSONObject st=shelves.getJSONArray("sets").getJSONObject(i);if(st.getLong("id")!=44000016L)continue;
            JSONArray shs=st.getJSONArray("shops");for(int j=0;j<shs.length();j++){
                JSONArray gs=shs.getJSONObject(j).getJSONArray("goods");for(int k=0;k<gs.length();k++)
                    equipment.put(gs.getJSONObject(k).getLong("id"),gs.getJSONObject(k).getLong("itemId"));
            }
        }
        for(int day=0;day<60;day++){
            ProtoWire view=set(store,role(catalog,50),catalog,44000016L,NOW+day*86400L);
            for(ProtoWire sh:children(view,5))if(sh.number(3,0)==1)for(ProtoWire g:children(sh,2)){
                total++;if(g.number(5,0)==1)discounted++;
                long item=equipment.get(g.number(1,0));if(item>=1440000&&item<1450000)purple=true;
            }
            ProtoWire forced=set(guaranteed,role(catalog,50),catalog,44000016L,NOW+day*86400L);
            for(ProtoWire sh:children(forced,5))if(sh.number(3,0)==1)for(ProtoWire g:children(sh,2))
                if(g.number(2,0)==1130){check(g.number(4,0)==1000&&g.number(5,0)==1,"Original ten-percent badge");
                    check(g.number(2,0)*(10000-g.number(4,0))/10000==1017,"Screenshot original price example");example=true;}
        }
        check(purple,"Purple equipment remains in original rotating pools");
        check(example,"1130 base price exercised");
        check(discounted>total/10&&discounted<total*3/10,"Configured probability exercised across deterministic periods");
        for(ProtoWire sh:children(set(store,role(catalog,1),catalog,44000002L,NOW),5))
            for(ProtoWire g:children(sh,2))check(g.number(3,0)==-1,"Maze origin keeps native unlimited semantics");
        System.out.println("OriginalShopCatalogSelfTest: "+checks+" checks passed; discounts "+discounted+"/"+total);
    }
}
