package com.codex.witchweapon;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONObject;

/** Explicit product windows; never infer an activity from an inventory cycle. */
final class StarShopEvents {
    static final long[] IDS={1010008,1010009,1010012,1010013};
    private final Map<Long,long[]> windows=new HashMap<Long,long[]>();
    private static StarShopEvents singleton;

    StarShopEvents(JSONObject catalog)throws IOException {
        JSONObject policy=catalog.optJSONObject("policy");
        JSONArray source=policy==null?null:policy.optJSONArray("starEventWindows");
        if(source==null)return;
        try {
            for(int i=0;i<source.length();i++) {
                JSONObject window=source.getJSONObject(i);
                long id=window.getLong("timeId"),start=window.getLong("start"),end=window.getLong("end");
                boolean known=false;for(long candidate:IDS)if(candidate==id)known=true;
                if(!known||start<=0||end<=start||windows.containsKey(id))
                    throw new IOException("Invalid star product activity window "+id);
                windows.put(id,new long[]{start,end});
            }
        }catch(org.json.JSONException invalid) {throw new IOException("Invalid star product activity config",invalid);}
    }
    static synchronized StarShopEvents bundled()throws IOException {
        if(singleton!=null)return singleton;
        try(InputStream in=StarShopEvents.class.getResourceAsStream("/exchange_shop_catalog.json")) {
            if(in==null)throw new IOException("Missing star product activity config");
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int n;
            while((n=in.read(buffer))!=-1) {
                if(out.size()+n>1024*1024)throw new IOException("Star catalog too large");
                out.write(buffer,0,n);
            }
            singleton=new StarShopEvents(new JSONObject(new String(out.toByteArray(),StandardCharsets.UTF_8)));
            return singleton;
        }catch(org.json.JSONException invalid) {throw new IOException("Invalid star catalog",invalid);}
    }
    long start(long id) {long[] window=windows.get(id);return window==null?0:window[0];}
    long end(long id) {long[] window=windows.get(id);return window==null?0:window[1];}
    boolean open(long id,long now) {return start(id)>0&&now>=start(id)&&now<end(id);}
    boolean anyOpen(long now) {for(long id:IDS)if(open(id,now))return true;return false;}
}
