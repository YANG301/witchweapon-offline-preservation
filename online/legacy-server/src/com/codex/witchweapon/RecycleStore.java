package com.codex.witchweapon;

import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;

/** Original resource/recycle protocol, priced by the preserved Item.recycle_value column. */
final class RecycleStore {
    private static final String RESOURCE="/recycle_values.json";
    private static RecycleStore singleton;
    private final JSONObject prices;

    static synchronized RecycleStore bundled()throws Exception {
        if(singleton!=null)return singleton;
        InputStream in=RecycleStore.class.getResourceAsStream(RESOURCE);
        if(in==null)throw new IOException("Original recycle values missing");
        try{
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] block=new byte[4096];int n;
            while((n=in.read(block))!=-1){
                if(out.size()+n>65536)throw new IOException("Recycle catalog too large");
                out.write(block,0,n);
            }
            singleton=new RecycleStore(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }finally{in.close();}
    }

    RecycleStore(JSONObject catalog)throws Exception {
        if(catalog.getInt("schemaVersion")!=1)throw new IOException("Unsupported recycle catalog");
        prices=catalog.getJSONObject("values");
        if(prices.length()!=59)throw new IOException("Incomplete original recycle values");
        for(Iterator<String> it=prices.keys();it.hasNext();){
            String id=it.next();int value=prices.getInt(id);
            if(!id.matches("[1-9][0-9]{7}")||value<1||value>1000000)
                throw new IOException("Invalid original recycle value");
        }
    }

    static boolean handles(String route){
        return route.equals("/resource/recycle/get") || route.equals("/resource/recycle") ||
            route.equals("/game/resource/recycle/get") || route.equals("/game/resource/recycle");
    }

    private static String raw(Map<String,String> args,String primary,String fallback){
        String value=args.get(primary);
        return value==null?args.get(fallback):value;
    }
    private static String[] tokens(String raw)throws IOException {
        if(raw==null||raw.trim().isEmpty())return new String[0];
        if(raw.length()>2048)throw new IOException("Recycle request too large");
        return raw.split("[|,;]",-1);
    }

    byte[] list(JSONObject state,JSONObject catalog)throws Exception {
        LocalEconomy.init(state,catalog);
        JSONObject bag=state.getJSONObject("items");
        ProtoWire output=new ProtoWire();long total=0;
        for(Iterator<String> it=prices.keys();it.hasNext();){
            String id=it.next();long count=bag.optLong(id,0);
            if(count<=0)continue;
            if(count>Integer.MAX_VALUE)throw new IOException("Invalid recyclable item count");
            int price=prices.getInt(id);
            total=Math.addExact(total,Math.multiplyExact(count,price));
            output.add(1,new ProtoWire().set(1,Long.parseLong(id)).set(2,count)
                .set(3,price).bytes());
        }
        if(total>Integer.MAX_VALUE)throw new IOException("Recycle total exceeds protocol limit");
        return output.set(100,total).bytes();
    }

    byte[] sell(JSONObject state,JSONObject catalog,Map<String,String> args)throws Exception {
        if(!state.optBoolean("roleCreated",false))throw new IOException("Role required for recycling");
        LocalEconomy.init(state,catalog);
        JSONObject bag=state.getJSONObject("items");
        String[] ids=tokens(raw(args,"items","itemids"));
        String[] quantities=tokens(raw(args,"itemnums","nums"));
        boolean all=ids.length==0&&quantities.length==0;
        if(!all && (ids.length==0||ids.length!=quantities.length||ids.length>59))
            throw new IOException("Invalid recycle selection");
        JSONObject selected=new JSONObject();
        if(all){
            for(Iterator<String> it=prices.keys();it.hasNext();){
                String id=it.next();long count=bag.optLong(id,0);
                if(count>0)selected.put(id,count);
            }
        }else{
            Set<String> unique=new HashSet<String>();
            for(int i=0;i<ids.length;i++){
                String id=ids[i].trim(),quantity=quantities[i].trim();
                if(!id.matches("[1-9][0-9]{7}")||!quantity.matches("[1-9][0-9]{0,9}")||
                    !prices.has(id)||!unique.add(id))
                    throw new IOException("Invalid recyclable item");
                long count=Long.parseLong(quantity);
                if(count>Integer.MAX_VALUE)throw new IOException("Recycle count exceeds protocol limit");
                selected.put(id,count);
            }
        }
        long total=0;
        for(Iterator<String> it=selected.keys();it.hasNext();){
            String id=it.next();long count=selected.getLong(id),owned=bag.optLong(id,0);
            if(count<1||owned<count)throw new IOException("Recyclable item quantity unavailable");
            total=Math.addExact(total,Math.multiplyExact(count,prices.getInt(id)));
        }
        long current=state.optLong("recycleCurrency",0);
        if(current<0||total>Integer.MAX_VALUE-current)
            throw new IOException("Recycle currency exceeds protocol limit");
        for(Iterator<String> it=selected.keys();it.hasNext();){
            String id=it.next();bag.put(id,bag.getLong(id)-selected.getLong(id));
        }
        state.put("recycleCurrency",current+total);
        return new ProtoWire().text(1,"ok").set(2,new byte[0]).bytes();
    }
}
