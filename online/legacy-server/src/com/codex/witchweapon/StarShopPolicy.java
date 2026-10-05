package com.codex.witchweapon;

import java.util.Calendar;
import java.util.GregorianCalendar;
import java.util.TimeZone;
import org.json.JSONObject;

/** Calendar periods documented by the original starshop_1 help text. */
final class StarShopPolicy {
    private StarShopPolicy() {}
    static boolean daily(JSONObject set) {
        long id=set.optLong("id");return id>=44000042L&&id<=44000051L;
    }
    static boolean naturalMonths(JSONObject set) {
        long id=set.optLong("id");return id==44000052L||id==44000053L;
    }
    static boolean star(JSONObject set) {
        long id=set.optLong("id");return id>=44000042L&&id<=44000054L;
    }
    static boolean cubeDevice(JSONObject set) {
        long id=set.optLong("id");return id>=44000042L&&id<=44000046L;
    }
    static boolean activitySet(JSONObject set) {
        long id=set.optLong("id");return id==44000053L||id==44000054L;
    }
    private static Calendar calendar(long now) {
        Calendar date=new GregorianCalendar(TimeZone.getTimeZone("GMT+08:00"));
        date.setTimeInMillis(Math.multiplyExact(now,1000L));return date;
    }
    static long monthBucket(long now) {
        Calendar date=calendar(now);
        return date.get(Calendar.YEAR)*6L+date.get(Calendar.MONTH)/2;
    }
    static long monthStart(long now,boolean end) {
        Calendar date=calendar(now);
        int year=date.get(Calendar.YEAR),month=(date.get(Calendar.MONTH)/2)*2;
        date.clear();date.set(year,month,1,0,0,0);
        if(end)date.add(Calendar.MONTH,2);
        return date.getTimeInMillis()/1000L;
    }
    static long legacyBucket(JSONObject set,long now) {
        int hours=set.optInt("periodHours");
        if(hours<=0)return 0;
        if(hours%24==0)return Math.floorDiv(Math.floorDiv(now+28800L,86400L),hours/24);
        return Math.floorDiv(now+28800L,hours*3600L);
    }
    static boolean legacyStock(JSONObject record,JSONObject set,long now,long effectiveAt) {
        // Preserve already-spent stock during the release's current calendar
        // period. Never extend a legacy 60-day claim into a future month pair.
        if(!star(set)||record.optInt("periodRule",0)==2||effectiveAt<=0)return false;
        boolean samePeriod=naturalMonths(set)?monthBucket(now)==monthBucket(effectiveAt):
            daily(set)?Math.floorDiv(now+28800L,86400L)==Math.floorDiv(effectiveAt+28800L,86400L):true;
        return samePeriod&&record.optLong("bucket",Long.MIN_VALUE)==legacyBucket(set,effectiveAt);
    }
}
