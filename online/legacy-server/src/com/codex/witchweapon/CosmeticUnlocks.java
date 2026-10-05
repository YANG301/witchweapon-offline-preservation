package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.IOException;
import java.util.Map;

/** Original role fashion and Kanban ownership for new online accounts. */
final class CosmeticUnlocks {
    static final long STARTER_FASHION=70000001L;
    static final long FASHION_COUPON=40350013L;
    static final int STARTER_BOARD=1;

    private CosmeticUnlocks(){}

    static boolean starter(JSONObject save){
        return save.optInt("starterProfile",0)==1 && save.optInt("cosmeticProfile",0)==1;
    }

    static boolean ownsFashion(JSONObject save,long fashionId){
        if(!starter(save))return true; // Existing preservation accounts keep their inventory.
        if(fashionId==STARTER_FASHION)return true;
        JSONObject owned=save.optJSONObject("fashionOwned");
        return owned!=null && owned.optBoolean(String.valueOf(fashionId),false);
    }

    /** The client sends its worn costume with battle setup. Persist that choice
     * in this account's save, never in the Android process-wide PlayerPrefs. */
    static long selectedFashion(JSONObject save,JSONObject catalog,Map<String,String> args)
            throws IOException{
        long selected=save.optLong("curFashion",STARTER_FASHION);
        String requested=args==null?null:args.get("fashioncardid");
        if(requested!=null && !requested.isEmpty()){
            long id;
            try{id=Long.parseLong(requested);}catch(NumberFormatException e){
                throw new IOException("Invalid fashioncardid",e);
            }
            if(id<0)throw new IOException("Invalid fashioncardid");
            if(id>0)selected=id; // 0 is the original client's unset sentinel.
        }
        JSONObject fashions=catalog==null?null:catalog.optJSONObject("fashions");
        if(selected<=0 || fashions==null || !fashions.has(String.valueOf(selected)) ||
           !ownsFashion(save,selected))selected=STARTER_FASHION;
        return selected;
    }

    static void rememberFashion(JSONObject save,JSONObject catalog,Map<String,String> args)
            throws Exception{
        long selected=selectedFashion(save,catalog,args);
        // An absent key in an older save means the original default. Avoid a
        // read-only migration; an explicit/effective change is saved normally.
        if(selected!=save.optLong("curFashion",STARTER_FASHION))
            save.put("curFashion",selected);
        else if(args!=null && args.containsKey("fashioncardid") &&
                !save.has("curFashion"))save.put("curFashion",selected);
    }

    static void grantFashion(JSONObject save,JSONObject catalog,long fashionId)throws Exception{
        if(!catalog.getJSONObject("fashions").has(String.valueOf(fashionId)))
            throw new IOException("Unknown fashion "+fashionId);
        JSONObject owned=save.optJSONObject("fashionOwned");
        if(owned==null)owned=new JSONObject();
        owned.put(String.valueOf(fashionId),true);
        save.put("fashionOwned",owned);
        LocalEconomy.collectionChanged(save);
    }

    /** Costs are the unique Fashion.asset rows in the preserved original APK. */
    static int couponCost(long fashionId)throws IOException{
        if(fashionId==70000002L || fashionId==70000003L)return 100;
        if(fashionId==70000004L || fashionId==70000005L ||
           fashionId==70000006L || fashionId==70000007L ||
           fashionId==70000008L || fashionId==70000009L ||
           fashionId==70000011L || fashionId==70000013L)return 120;
        if(fashionId==70000010L)return 9999;
        throw new IOException("Fashion is not exchangeable");
    }

    static void compose(JSONObject save,JSONObject catalog,long fashionId)throws Exception{
        if(!catalog.getJSONObject("fashions").has(String.valueOf(fashionId)))
            throw new IOException("Unknown fashion "+fashionId);
        if(ownsFashion(save,fashionId))throw new IOException("Fashion already owned");
        int cost=couponCost(fashionId);
        JSONObject items=save.getJSONObject("items");
        String key=Long.toString(FASHION_COUPON);
        long count=items.optLong(key,0);
        if(count<cost)throw new IOException("Not enough fashion coupons");
        items.put(key,count-cost);
        grantFashion(save,catalog,fashionId);
        save.put("inventoryRevision",Math.addExact(save.optLong("inventoryRevision",0),1));
    }

    static boolean ownsBoard(JSONObject save,int id){
        if(!starter(save))return true;
        if(id==STARTER_BOARD)return true;
        JSONObject all=save.optJSONObject("roleUnlocks");
        JSONObject boards=all==null?null:all.optJSONObject("5");
        return boards!=null && boards.optBoolean(String.valueOf(id),false);
    }

    static void applyStarterRole(JSONObject save,JSONObject catalog,ProtoWire role,
                                 ProtoWire response)throws Exception{
        if(!starter(save) || !catalog.has("boards") || !catalog.has("fashions"))return;
        // Original RoleInstanceProto.Board (field 5) has one flag per Kanban
        // row. Preserve its index layout, but publish ownership from this save.
        org.json.JSONArray boards=catalog.getJSONArray("boards");
        role.clear(5);
        for(int i=0;i<boards.length();i++){
            int id=boards.getInt(i);
            if(id!=i+1)throw new IOException("Unexpected Kanban catalog order");
            role.add(5,ownsBoard(save,id)?1:0);
        }
        if(!ownsBoard(save,(int)role.number(127,STARTER_BOARD)))
            role.set(127,STARTER_BOARD);

        // RoleInstanceProto's companion FashionInstance list is field 3 of
        // the role response; Own is field 5 of each FashionInstance.
        for(ProtoWire.Field field:response.fields)if(field.number==3 && field.type==2){
            ProtoWire fashion=ProtoWire.parse(field.data);
            long id=fashion.number(1,0);
            if(!catalog.getJSONObject("fashions").has(String.valueOf(id)))continue;
            fashion.set(5,ownsFashion(save,id)?1:0);
            field.data=fashion.bytes();
        }
    }
}
