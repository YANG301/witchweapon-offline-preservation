package com.codex.witchweapon;

import org.json.JSONObject;

/**
 * Activity-overview additions used by the isolated online service.
 *
 * The three synthetic AD cards have been withdrawn. With no AD entries the
 * original UIActivities.lua displays its original, non-clickable default art.
 * Base ID 11 is the original welfare-return page (Activity.csv format 61).
 */
final class ActivityBanner {
    static final long WELFARE_RETURN_ID = 11L;

    private ActivityBanner() { }

    static void appendTo(ProtoWire activityListLua, JSONObject state, long nowSeconds) {
        if (activityListLua == null || state == null || nowSeconds < 86400L)
            throw new IllegalArgumentException("Invalid activity list, state or server time");

        // The account ledger stores simulated list-price purchases in cents.
        // This is a free preservation-server progress counter, not a payment.
        long cents = Math.max(0L, state.optLong("virtualPurchaseCents", 0L));
        ProtoWire progress = new ProtoWire()
            .set(1, cents / 100L) // RechargeReward.Recharge
            .set(2, WelfareReturn.eligibleMask(cents))
            .set(3, WelfareReturn.claimedMask(state));
        ProtoWire entry = new ProtoWire()
            .set(1, 2L) // ActivityModel.ActivityType.Recharge
            .set(2, WELFARE_RETURN_ID)
            .set(3, nowSeconds)
            .set(4, nowSeconds)
            .set(5, nowSeconds) // equal start/close means permanent in original UI
            .set(101, progress.bytes());
        activityListLua.add(1, entry.bytes());
    }
}
