package com.codex.witchweapon;

import java.io.IOException;
import java.util.Iterator;

/** Independent lab clock; ID5 is open only in this shadow jar. */
final class CaphActivityAccess {
    static final long SERIAL=5;
    static final long TIME_ID=1030005;
    static final long[] STAR_GOODS_TIME_IDS=StarShopEvents.IDS;

    private CaphActivityAccess() {}

    static boolean shopOpen(long now) {
        return now>=LocalActivityLab.OPEN_START && now<LocalActivityLab.OPEN_END;
    }

    static byte[] instance(byte[] preserved) throws IOException {
        return ProtoWire.parse(preserved).set(1,1).set(2,SERIAL).set(12,1).bytes();
    }

    static byte[] timeData(byte[] preserved,long now) throws IOException {
        return timeData(preserved,now,StarShopEvents.bundled());
    }
    static byte[] timeData(byte[] preserved,long now,StarShopEvents events) throws IOException {
        ProtoWire times=ProtoWire.parse(preserved);
        putTime(times,TIME_ID,LocalActivityLab.OPEN_START,LocalActivityLab.OPEN_END);
        for(long id:STAR_GOODS_TIME_IDS)putTime(times,id,events.start(id),events.end(id));
        return times.bytes();
    }

    private static void putTime(ProtoWire times,long id,long start,long end) throws IOException {
        ProtoWire value=new ProtoWire();
        for(Iterator<ProtoWire.Field> it=times.fields.iterator();it.hasNext();) {
            ProtoWire.Field field=it.next();
            if(field.number==1&&field.type==2&&
               ProtoWire.parse(field.data).number(1,0)==id) {
                byte[] period=ProtoWire.parse(field.data).data(2);
                if(period!=null)value=ProtoWire.parse(period);
                it.remove();
            }
        }
        value.set(1,start).set(2,end).set(3,end);
        times.add(1,new ProtoWire().set(1,id).set(2,value.bytes()).bytes());
    }
}
