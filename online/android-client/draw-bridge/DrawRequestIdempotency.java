package com.codex.witchweapon;

import java.io.IOException;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/** Adds a replay key only to the four ordinary, in-game-currency draw routes. */
final class DrawRequestIdempotency {
    private static final long UNCERTAIN_RETRY_NANOS = 45_000_000_000L;
    private static final int MAX_RECENT = 64;
    private static final LinkedHashMap<String, Entry> RECENT = new LinkedHashMap<>();

    private static final class Entry {
        final String key;
        long at;
        Entry(String key, long at) { this.key = key; this.at = at; }
    }

    private DrawRequestIdempotency() {}

    static byte[] append(String path, String contentType, byte[] body) throws IOException {
        String canonical = path.startsWith("/game/") ? path.substring(5) : path;
        if (!(canonical.equals("/draw/gold/single") || canonical.equals("/draw/gold/ten") ||
              canonical.equals("/draw/rmb/single") || canonical.equals("/draw/rmb/ten"))) return body;
        if (contentType == null || !contentType.toLowerCase(Locale.ROOT)
                .startsWith("application/x-www-form-urlencoded"))
            throw new IOException("Draw request must use a form body");
        if (body == null || body.length > 8192)
            throw new IOException("Invalid draw request size");
        String form = new String(body, StandardCharsets.UTF_8);
        StringBuilder forwarded = new StringBuilder(form.length() + 52);
        for (String pair : form.split("&", -1)) {
            String name = pair.split("=", 2)[0];
            try { name = URLDecoder.decode(name, "UTF-8"); }
            catch (IllegalArgumentException badForm) { throw new IOException("Invalid draw form", badForm); }
            // NetMsgBase can supply its own time-derived key. Its value can
            // recur across distinct draws, so the bridge owns this one field.
            if (name.equals("idempotency")) continue;
            if (forwarded.length() != 0) forwarded.append('&');
            forwarded.append(pair);
        }
        final String fingerprint = fingerprint(canonical, body);
        final long now = System.nanoTime();
        final String key;
        synchronized (RECENT) {
            for (Iterator<Map.Entry<String, Entry>> it = RECENT.entrySet().iterator(); it.hasNext();) {
                Map.Entry<String, Entry> entry = it.next();
                if (now - entry.getValue().at > UNCERTAIN_RETRY_NANOS || now < entry.getValue().at)
                    it.remove();
            }
            Entry existing = RECENT.get(fingerprint);
            if (existing == null) {
                existing = new Entry(UUID.randomUUID().toString(), now);
                RECENT.put(fingerprint, existing);
            }
            while (RECENT.size() > MAX_RECENT) RECENT.remove(RECENT.keySet().iterator().next());
            key = existing.key;
        }
        if (forwarded.length() != 0) forwarded.append('&');
        forwarded.append("idempotency=").append(key);
        return forwarded.toString().getBytes(StandardCharsets.UTF_8);
    }

    /** Once the complete upstream response is read, the next tap is a new draw. */
    static void confirm(String path, byte[] originalBody) {
        String canonical = path.startsWith("/game/") ? path.substring(5) : path;
        try {
            String fingerprint = fingerprint(canonical, originalBody);
            synchronized (RECENT) {
                RECENT.remove(fingerprint);
            }
        } catch (IOException unavailable) { /* The request already finished. */ }
    }

    private static String fingerprint(String path, byte[] body) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            digest.update(path.getBytes(StandardCharsets.US_ASCII));
            digest.update((byte) 0);
            digest.update(body);
            byte[] hash = digest.digest();
            StringBuilder text = new StringBuilder(hash.length * 2);
            for (byte b : hash) text.append(Character.forDigit((b >>> 4) & 15, 16))
                .append(Character.forDigit(b & 15, 16));
            return text.toString();
        } catch (Exception unavailable) {
            throw new IOException("Draw replay hashing unavailable", unavailable);
        }
    }
}
