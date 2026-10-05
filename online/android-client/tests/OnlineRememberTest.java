package com.codex.witchweapon;

import android.content.Context;
import android.content.ContextWrapper;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

/** Device-side checks for token parsing and the actual Android Keystore codec. */
public final class OnlineRememberTest {
    private static int checks;

    private static void require(boolean value, String label) {
        checks++;
        if (!value) throw new AssertionError(label);
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass an empty writable test directory");
        File dir = new File(args[0]);
        if (!dir.isDirectory() && !dir.mkdir()) throw new IllegalStateException("Cannot make test directory");
        final File storage = dir;
        Context context = new ContextWrapper(null) {
            @Override public File getNoBackupFilesDir() { return storage; }
            @Override public String getPackageName() { return "com.codex.witchweapon.remember.selftest"; }
        };
        String access = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        String refresh = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB";
        String nextRefresh = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC";
        String nonce = "1234567890abcdef1234567890abcdef1234567890abcdef";
        String reply = "{\"token\":\"" + access + "\",\"refreshToken\":\"" + refresh
                + "\",\"refreshExpiresAt\":\"2099-01-01T00:00:00Z\"}";
        OnlineAuthTokens parsed = OnlineAuthTokens.parse(reply.getBytes(StandardCharsets.UTF_8));
        require(access.equals(parsed.access) && refresh.equals(parsed.refresh), "auth reply tokens");
        require(OnlineAuthTokens.parseExpiry("2099-01-01T08:00:00+08:00")
                == OnlineAuthTokens.parseExpiry("2099-01-01T00:00:00Z"), "timezone offset");
        require(OnlineAuthTokens.parseExpiry("2099-01-01T00:00:00.123456789Z")
                - OnlineAuthTokens.parseExpiry("2099-01-01T00:00:00Z") == 123,
                "fractional seconds");
        try {
            OnlineAuthTokens.parseExpiry("2099-13-01T00:00:00Z");
            throw new AssertionError("Accepted invalid month");
        } catch (java.io.IOException expected) { checks++; }

        OnlineSessionStore store = new OnlineSessionStore(context);
        store.clear();
        require(store.read() == null, "empty store");
        store.write(new OnlineSessionStore.Entry("alice@example.com", nonce,
                refresh, parsed.refreshExpiresAt));
        OnlineSessionStore.Entry saved = store.read();
        require(saved != null && "alice@example.com".equals(saved.email)
                && nonce.equals(saved.nonce) && refresh.equals(saved.refresh), "encrypted round trip");
        byte[] raw = java.nio.file.Files.readAllBytes(
                new File(dir, "online_refresh_v1.bin").toPath());
        require(!new String(raw, StandardCharsets.ISO_8859_1).contains(refresh),
                "refresh is absent from stored ciphertext");
        store.write(new OnlineSessionStore.Entry("alice@example.com", nonce,
                nextRefresh, parsed.refreshExpiresAt));
        require(nextRefresh.equals(store.read().refresh), "rotated credential replaces old one");
        raw[raw.length - 1] ^= 1;
        try (FileOutputStream output = new FileOutputStream(new File(dir, "online_refresh_v1.bin"))) {
            output.write(raw);
        }
        // The previous raw bytes were from the first write and have an invalid tag.
        try {
            store.read();
            throw new AssertionError("Accepted tampered ciphertext");
        } catch (OnlineSessionStore.Corrupt expected) { checks++; }
        store.clear();
        require(store.read() == null, "logout removes credential");
        require(!new File(dir, "online_refresh_v1.bin").exists(), "logout removes ciphertext");
        if (!dir.delete()) throw new IllegalStateException("Cannot remove test directory");
        System.out.println("ONLINE_REMEMBER_DEVICE_TEST_OK " + checks + " assertions");
    }
}
