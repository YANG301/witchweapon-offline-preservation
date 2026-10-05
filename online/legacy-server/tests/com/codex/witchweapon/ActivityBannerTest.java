package com.codex.witchweapon;

import java.util.Arrays;
import org.json.JSONObject;

/** Wire-level check for the original activitymod.ActivityListLua consumer. */
public final class ActivityBannerTest {
    public static void main(String[] args) throws Exception {
        long now = 1789999999L;
        ProtoWire list = new ProtoWire();
        byte[] sentinel = new ProtoWire().set(1, 14).set(2, 25).bytes();
        list.add(1, sentinel);
        ActivityBanner.appendTo(list,
            new JSONObject().put("virtualPurchaseCents", 21400L), now);
        ProtoWire wire = ProtoWire.parse(list.bytes());
        if (wire.fields.size() != 2 ||
                !Arrays.equals(sentinel, wire.fields.get(0).data))
            throw new AssertionError("Existing daily activity changed");
        ProtoWire entry = ProtoWire.parse(wire.fields.get(1).data);
        if (entry.number(1, -1) != 2 ||
                entry.number(2, -1) != ActivityBanner.WELFARE_RETURN_ID ||
                entry.number(3, -1) != now || entry.number(5, -1) != now)
            throw new AssertionError("Original welfare-return entry missing");
        ProtoWire progress = ProtoWire.parse(entry.data(101));
        if (progress.number(1, -1) != 214 ||
                progress.number(2, -1) != 1 || progress.number(3, -1) != 0)
            throw new AssertionError("Welfare progress or first claimable tier incorrect");
        for (ProtoWire.Field field : wire.fields) {
            ProtoWire activity = ProtoWire.parse(field.data);
            if (activity.number(1, -1) == 16)
                throw new AssertionError("Synthetic carousel AD still present");
        }
        ProtoWire fresh = new ProtoWire();
        ActivityBanner.appendTo(fresh, new JSONObject(), now);
        if (ProtoWire.parse(ProtoWire.parse(fresh.bytes()).fields.get(0).data)
                .number(2, -1) != ActivityBanner.WELFARE_RETURN_ID)
            throw new AssertionError("New account welfare page missing");
        System.out.println("ACTIVITY_ORIGINAL_HOME_WELFARE_PROTO_OK");
    }
}
