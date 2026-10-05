package com.codex.witchweapon;

import java.util.Arrays;

/** Regression for the native cube shelf's unguarded Goods.time_id lookup. */
public final class StarShopTimeDataSelfTest {
    private static void check(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
    private static ProtoWire entry(ProtoWire all,long id)throws Exception {
        ProtoWire found=null;
        for(ProtoWire.Field field:all.fields)if(field.number==1&&field.type==2) {
            ProtoWire value=ProtoWire.parse(field.data);
            if(value.number(1,0)==id) {
                check(found==null,"Duplicate availability key "+id);
                found=value;
            }
        }
        return found;
    }
    public static void main(String[] args)throws Exception {
        long now=1790904000L;
        ProtoWire empty=ProtoWire.parse(CaphActivityAccess.timeData(new byte[0],now));
        for(long id:new long[]{1010008,1010009,1010012,1010013}) {
            ProtoWire clock=entry(empty,id);
            check(clock!=null,"Missing original star product clock "+id);
            ProtoWire period=ProtoWire.parse(clock.data(2));
            check(period.number(1,-1)==0&&period.number(2,-1)==0,
                "Unscheduled event goods stay closed without null native clocks "+id);
            check(period.number(3,0)==period.number(2,0),"Close/end consistency");
        }
        ProtoWire unrelated=new ProtoWire().set(1,1030002)
            .set(2,new ProtoWire().set(1,100).set(2,200).bytes());
        ProtoWire obsolete=new ProtoWire().set(1,1010008)
            .set(2,new ProtoWire().set(1,100).set(2,200).set(9,777).bytes());
        ProtoWire input=new ProtoWire().add(1,unrelated.bytes())
            .add(1,obsolete.bytes()).set(3,55);
        byte[] original=input.bytes();
        ProtoWire restored=ProtoWire.parse(CaphActivityAccess.timeData(original,now));
        check(Arrays.equals(unrelated.bytes(),entry(restored,1030002).bytes()),
            "Unrelated activity window is unchanged");
        check(restored.number(3,0)==55,"Envelope fields survive");
        check(ProtoWire.parse(entry(restored,1010008).data(2)).number(9,0)==777,
            "Unrelated product metadata survives");
        check(Arrays.equals(input.bytes(),original),"Input is immutable");
        ProtoWire repeated=ProtoWire.parse(CaphActivityAccess.timeData(restored.bytes(),now));
        check(Arrays.equals(restored.bytes(),repeated.bytes()),"Refresh is idempotent");
        ProtoWire renewed=ProtoWire.parse(CaphActivityAccess.timeData(restored.bytes(),now+400*86400L));
        check(ProtoWire.parse(entry(renewed,1010013).data(2)).number(2,-1)==0,
            "Passing time never fabricates an event");
        System.out.println("STAR_PRODUCT_CLOCKS_OK four closed keys; metadata and unrelated activities preserved");
    }
}
