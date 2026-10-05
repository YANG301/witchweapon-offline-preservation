package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;

public final class DrawRequestIdempotencyTest {
    private static void check(boolean value,String detail){ if(!value)throw new AssertionError(detail); }
    private static byte[] raw(String value){ return value.getBytes(StandardCharsets.UTF_8); }
    public static void main(String[] unused)throws Exception{
        byte[] request=raw("rid=8&date=123&sign=abc");
        byte[] first=DrawRequestIdempotency.append("/draw/gold/single",
            "application/x-www-form-urlencoded; charset=utf-8",request);
        byte[] retry=DrawRequestIdempotency.append("/draw/gold/single",
            "application/x-www-form-urlencoded",request);
        check(Arrays.equals(first,retry),"Same network request lost its replay key");
        DrawRequestIdempotency.confirm("/draw/gold/single",request);
        check(!Arrays.equals(first,DrawRequestIdempotency.append("/draw/gold/single",
            "application/x-www-form-urlencoded",request)),"Second real click reused completed draw");
        byte[] next=DrawRequestIdempotency.append("/draw/gold/single",
            "application/x-www-form-urlencoded",raw("rid=8&date=124&sign=def"));
        check(!Arrays.equals(first,next),"Distinct draw reused the previous key");
        byte[] guide=raw("rid=8&guidedrawserial=1");
        check(Arrays.equals(guide,DrawRequestIdempotency.append("/guide/draw",
            "application/x-www-form-urlencoded",guide)),"Tutorial request was modified");
        byte[] nativeKey=raw("rid=8&idempotency=old-time-derived-key&time=123");
        byte[] replaced=DrawRequestIdempotency.append("/draw/rmb/ten",
            "application/x-www-form-urlencoded",nativeKey);
        String form=new String(replaced,StandardCharsets.UTF_8);
        check(form.startsWith("rid=8&time=123&idempotency=")&&
            !form.contains("old-time-derived-key"),"Original draw key was not replaced");
        check(Arrays.equals(replaced,DrawRequestIdempotency.append("/draw/rmb/ten",
            "application/x-www-form-urlencoded",nativeKey)),"Uncertain retry changed key");
        DrawRequestIdempotency.confirm("/draw/rmb/ten",nativeKey);
        check(!Arrays.equals(replaced,DrawRequestIdempotency.append("/draw/rmb/ten",
            "application/x-www-form-urlencoded",nativeKey)),"Second draw merged after success");
        System.out.println("DRAW_BRIDGE_OK");
    }
}
