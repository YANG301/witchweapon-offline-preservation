package com.codex.witchweapon;

import java.util.Arrays;

/** CAPH access uses only the original activity serial/time key. */
public final class CaphActivityAccessSelfTest {
    private static void check(boolean condition,String message){
        if(!condition)throw new AssertionError(message);
    }
    public static void main(String[] args)throws Exception{
        long now=1770000000L;
        ProtoWire original=new ProtoWire().set(1,1).set(2,9)
            .set(9,new byte[0]).set(12,0).set(100,new byte[]{7});
        ProtoWire activity=ProtoWire.parse(CaphActivityAccess.instance(original.bytes()));
        check(activity.number(1,-1)==0,"Special-action battle must remain closed");
        check(activity.number(2,0)==1&&activity.number(12,1)==0,
            "Original serial without entering unfinished special-action chain");
        check(activity.data(100).length==1&&activity.data(100)[0]==7,
            "Unrelated original activity data must survive");

        ProtoWire other=new ProtoWire().set(1,1030002)
            .set(2,new ProtoWire().set(1,100).set(2,200).bytes());
        ProtoWire expired=new ProtoWire().set(1,1030001)
            .set(2,new ProtoWire().set(1,100).set(2,200).bytes());
        ProtoWire preserved=new ProtoWire().add(1,other.bytes())
            .add(1,expired.bytes()).set(3,55);
        ProtoWire times=ProtoWire.parse(CaphActivityAccess.timeData(preserved.bytes(),now));
        int relevant=0,otherCount=0;
        for(ProtoWire.Field field:times.fields)if(field.number==1&&field.type==2){
            ProtoWire entry=ProtoWire.parse(field.data);
            if(entry.number(1,0)==1030001){
                relevant++;
                ProtoWire period=ProtoWire.parse(entry.data(2));
                check(period.number(1,-1)==0&&period.number(2,-1)==0&&
                    period.number(3,-1)==0,
                    "Unscheduled CAPH activity must have a non-null closed clock");
            }else if(entry.number(1,0)==1030002){
                otherCount++;
                check(Arrays.equals(other.bytes(),field.data),
                    "Other activity time must be preserved");
            }else if(entry.number(1,0)<1010008||entry.number(1,0)>1010013)
                throw new AssertionError("Unexpected activity time key");
        }
        check(relevant==1&&otherCount==1&&times.number(3,0)==55,
            "Original CAPH serial and unrelated clock survive star availability restoration");
        check(!CaphActivityAccess.shopOpen(now)&&!CaphActivityAccess.shopOpen(now+400*86400L),
            "Passing time must never open an unscheduled CAPH shop");
        System.out.println("CAPH activity access OK");
    }
}
