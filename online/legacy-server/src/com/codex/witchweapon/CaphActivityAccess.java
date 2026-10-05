package com.codex.witchweapon;

import java.io.IOException;
import java.util.Iterator;

/** Original activity and explicitly scheduled star-shop product clocks. */
final class CaphActivityAccess {
    static final long SERIAL=1;
    static final long TIME_ID=1030001;
    // Original core/costume Goods rows require these keys even when their
    // inventory reset is controlled independently by ShopSet.StopTime.
    static final long[] STAR_GOODS_TIME_IDS=StarShopEvents.IDS;

    private CaphActivityAccess() {}

    static boolean shopOpen(long now) {
        // No special action is scheduled or implemented yet. Keep the same
        // closed state as instance(); Serial alone must not open its shop.
        return false;
    }

    static byte[] instance(byte[] preserved) throws IOException {
        // Apmod.ActivityGameInstance: Serial=2, ActOpen=12.  ActOpen=1 starts
        // the original activity initialization chain; its other responses
        // are not yet implemented, so the client never finishes login.
        // Preserve the original closed switch until that chain is complete.
        return ProtoWire.parse(preserved).set(1,0).set(2,SERIAL).set(12,0).bytes();
    }

    static byte[] timeData(byte[] preserved,long now) throws IOException {
        return timeData(preserved,now,StarShopEvents.bundled());
    }
    static byte[] timeData(byte[] preserved,long now,StarShopEvents events) throws IOException {
        // Timermod.TimeDatas.Data is a map<long,TimeData> at field 1.  Its
        // original CN ActivityGames row 1 points to time_id 1030001.  Keep
        // every unrelated server time entry. Native RefrashShop dereferences
        // the Goods.time_id entry without a null guard: omitting a product
        // clock aborts the whole cube shelf, leaving the previous page visible.
        ProtoWire times=ProtoWire.parse(preserved);
        // Supply a non-null closed clock for the native lookup, including
        // its two-day currency-clear grace period. Never fabricate an event.
        putTime(times,TIME_ID,0,0);
        // Missing historical event dates do not imply permanent availability.
        // Keep non-null closed clocks for old cached clients; scheduled events
        // receive their real start/end and inventory resets remain independent.
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
