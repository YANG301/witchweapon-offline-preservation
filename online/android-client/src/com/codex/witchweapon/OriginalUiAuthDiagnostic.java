package com.codex.witchweapon;

import android.util.Log;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/**
 * One-off emulator diagnostics, enabled only by a candidate-only asset.
 * It never logs request values, bodies, raw field names, headers or tokens.
 */
final class OriginalUiAuthDiagnostic {
    private static final String TAG = "WW-AUTH-FORM";
    private static final String[] KEYS = {
        "useraccount", "usertype", "password", "cdkey", "sms",
        "bundleid", "cid", "date", "sign"
    };
    private static final byte[][] KEY_BYTES = new byte[KEYS.length][];
    static {
        for (int i = 0; i < KEYS.length; i++)
            KEY_BYTES[i] = KEYS[i].getBytes(StandardCharsets.US_ASCII);
    }

    private OriginalUiAuthDiagnostic() { }

    static void rejected(String path, String contentType, byte[] form,
                         String stage, String reason, int upstreamStatus) {
        String endpoint = "/account/user/regist".equals(path) ? "regist"
                : "/account/user/login".equals(path) ? "login" : "other";
        int known = 0;
        int unknown = 0;
        int repeated = 0;
        if (form != null && form.length <= 8192) {
            for (int start = 0; start < form.length;) {
                int end = start;
                while (end < form.length && form[end] != '&') end++;
                int equal = start;
                while (equal < end && form[equal] != '=') equal++;
                int index = keyIndex(form, start, equal);
                if (index < 0) unknown++;
                else if ((known & (1 << index)) != 0) repeated++;
                else known |= 1 << index;
                start = end + 1;
            }
        }
        // Every printable variable below is from a fixed vocabulary or a
        // count/bitmask. Neither input bytes nor exception text is rendered.
        Log.i(TAG, "POST " + endpoint + " legacyStatus=200 upstreamStatus="
                + (upstreamStatus >= 100 && upstreamStatus <= 599 ? upstreamStatus : 0)
                + " stage=" + safeStage(stage) + " reason=" + safeReason(reason)
                + " media=" + mediaClass(contentType)
                + " knownMask=" + Integer.toHexString(known)
                + " unknownCount=" + Math.min(unknown, 8192)
                + " repeatedKnown=" + Math.min(repeated, 8192));
    }

    private static int keyIndex(byte[] form, int start, int end) {
        for (int i = 0; i < KEY_BYTES.length; i++) {
            byte[] key = KEY_BYTES[i];
            if (end - start != key.length) continue;
            boolean equal = true;
            for (int j = 0; j < key.length; j++) {
                if (form[start + j] != key[j]) { equal = false; break; }
            }
            if (equal) return i;
        }
        return -1;
    }

    private static String mediaClass(String contentType) {
        if (contentType == null || contentType.isEmpty()) return "missing";
        int semicolon = contentType.indexOf(';');
        String media = (semicolon < 0 ? contentType : contentType.substring(0, semicolon))
                .trim().toLowerCase(Locale.ROOT);
        if ("application/x-www-form-urlencoded".equals(media)) return "urlencoded";
        if ("multipart/form-data".equals(media)) return "multipart";
        if ("application/json".equals(media)) return "json";
        return "other";
    }

    private static String safeStage(String value) {
        if ("dependencies".equals(value) || "parse".equals(value)
                || "open".equals(value) || "send".equals(value)
                || "status".equals(value) || "read".equals(value)
                || "bearer".equals(value) || "role".equals(value)
                || "fixture".equals(value) || "session".equals(value)) return value;
        return "other";
    }

    private static String safeReason(String value) {
        if ("missing_dependency".equals(value) || "form_type".equals(value)
                || "form_shape".equals(value) || "fields".equals(value)
                || "field_length".equals(value) || "account_type".equals(value)
                || "account".equals(value) || "password".equals(value)
                || "metadata".equals(value) || "utf8".equals(value)
                || "upstream_status".equals(value) || "exception".equals(value)) return value;
        return "other";
    }
}
