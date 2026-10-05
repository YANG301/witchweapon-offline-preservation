package com.codex.witchweapon;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Connects only the explicitly selected guest account to the PC local service. */
final class LocalModeBridge {
    static final String ORIGIN = "http://127.0.0.1:19876";
    static final String UNITY_ORIGIN = "http://127.0.0.1:19878";
    private static final int MAX_ACCOUNT = 65536;
    private static final int MAX_GAME = 16 * 1024 * 1024;

    static final class Reply {
        final int status;
        final String contentType;
        final byte[] body;

        Reply(int status, String contentType, byte[] body) {
            this.status = status;
            this.contentType = contentType;
            this.body = body;
        }
    }

    private LocalModeBridge() { }

    /** The original VisitorBtn sends the legacy registration form with usertype=3. */
    static boolean isGuestAccount(String method, String path, String contentType, byte[] body) {
        if (!"POST".equals(method) || !("/account/user/regist".equals(path)
                || "/account/user/login".equals(path))) return false;
        return hasExactFormField(contentType, body, "usertype", "3");
    }

    /** The original client may repeat its fixed guest token on process restart. */
    static boolean isGuestToken(String method, String path, String contentType, byte[] body) {
        if (!"POST".equals(method) || !"/account/user/tokenlogin".equals(path)
                || !hasExactFormField(contentType, body, "token", "offline-local")) return false;
        String account = formField(contentType, body, "useraccount");
        return account != null && account.matches("[0-9a-f]{10}");
    }

    private static boolean hasExactFormField(String contentType, byte[] body,
                                              String wantedKey, String wantedValue) {
        return wantedValue.equals(formField(contentType, body, wantedKey));
    }

    private static String formField(String contentType, byte[] body, String wantedKey) {
        if (contentType == null || body == null || body.length == 0 || body.length > 8192
                || !contentType.toLowerCase(Locale.ROOT)
                .startsWith("application/x-www-form-urlencoded")) return null;
        String form = new String(body, StandardCharsets.US_ASCII);
        String found = null;
        for (String pair : form.split("&", -1)) {
            int equal = pair.indexOf('=');
            if (equal <= 0) return null;
            if (!wantedKey.equals(pair.substring(0, equal))) continue;
            if (found != null) return null;
            found = pair.substring(equal + 1);
        }
        return found;
    }

    /** A health check prevents silently connecting to a different app on port 19876. */
    static Reply openGuest(String accountPath) throws IOException {
        if (!("/account/user/regist".equals(accountPath)
                || "/account/user/login".equals(accountPath)
                || "/account/user/tokenlogin".equals(accountPath)))
            throw new IOException("Unsupported local account path");
        Reply health = request("GET", "/health", null, null, MAX_ACCOUNT);
        if (health.status != 200) throw new IOException("Local service health failed");
        try {
            JSONObject state = new JSONObject(new String(health.body, StandardCharsets.UTF_8));
            if (!"ok".equals(state.optString("status"))
                    || !"single-user-local".equals(state.optString("mode"))
                    || state.optInt("responseEntries") < 1)
                throw new IOException("Unexpected local service identity");
        } catch (IOException failed) {
            throw failed;
        } catch (Exception invalid) {
            throw new IOException("Invalid local health response", invalid);
        }
        Reply account = request("POST", accountPath,
                "application/x-www-form-urlencoded; charset=utf-8", new byte[0], MAX_ACCOUNT);
        validateAccount(account);
        return rewriteAccountZone(account);
    }

    private static void validateAccount(Reply account) throws IOException {
        if (account.status != 200 || !account.contentType.toLowerCase(Locale.ROOT)
                .startsWith("application/json"))
            throw new IOException("Local account response failed");
        try {
            JSONObject envelope = new JSONObject(new String(account.body, StandardCharsets.UTF_8));
            JSONObject value = envelope.getJSONObject("Value");
            JSONArray zones = value.getJSONArray("ZoneInfo");
            if (!"".equals(envelope.getString("Ecode")) || value.getInt("UID") != 1
                    || value.getInt("UserType") != 3
                    || !"offline-local".equals(value.getString("Token"))
                    || !"offline-local".equals(value.getString("LoginToken"))
                    || zones.length() != 1
                    || !ORIGIN.equals(zones.getJSONObject(0).getString("ServerIP")))
                throw new IOException("Unexpected local account identity");
        } catch (IOException failed) {
            throw failed;
        } catch (Exception invalid) {
            throw new IOException("Invalid local account response", invalid);
        }
    }

    private static Reply rewriteAccountZone(Reply account) throws IOException {
        try {
            JSONObject envelope = new JSONObject(new String(account.body, StandardCharsets.UTF_8));
            JSONObject zone = envelope.getJSONObject("Value").getJSONArray("ZoneInfo")
                    .getJSONObject(0);
            zone.put("ServerIP", UNITY_ORIGIN);
            zone.put("ZoneName", "本地模式");
            return new Reply(account.status, account.contentType,
                    envelope.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception invalid) {
            throw new IOException("Cannot adapt local account zone", invalid);
        }
    }

    static Reply requestGame(String method, String target, String contentType, byte[] body)
            throws IOException {
        Reply reply = request(method, target, contentType, body, MAX_GAME);
        if (("/account/user/login".equals(target) || "/account/user/regist".equals(target)
                || "/account/user/tokenlogin".equals(target)
                || "/account/user/token/get".equals(target)
                || "/account/user/getZone".equals(target)) && reply.status == 200
                && reply.contentType.toLowerCase(Locale.ROOT).startsWith("application/json")) {
            validateAccount(reply);
            return rewriteAccountZone(reply);
        }
        return reply;
    }

    private static Reply request(String method, String target, String contentType, byte[] body,
                                 int limit) throws IOException {
        if (!("GET".equals(method) || "POST".equals(method)) || target == null
                || !target.startsWith("/") || target.indexOf('#') >= 0
                || target.indexOf('\r') >= 0 || target.indexOf('\n') >= 0)
            throw new IOException("Invalid local request");
        HttpURLConnection upstream = (HttpURLConnection) new URL(ORIGIN + target).openConnection();
        try {
            upstream.setConnectTimeout(3000);
            upstream.setReadTimeout(10000);
            upstream.setUseCaches(false);
            upstream.setInstanceFollowRedirects(false);
            upstream.setRequestMethod(method);
            if ("POST".equals(method)) {
                byte[] payload = body == null ? new byte[0] : body;
                if (payload.length > 1024 * 1024) throw new IOException("Local request too large");
                upstream.setDoOutput(true);
                upstream.setRequestProperty("Content-Type", contentType == null
                        ? "application/x-www-form-urlencoded; charset=utf-8" : contentType);
                upstream.setFixedLengthStreamingMode(payload.length);
                try (OutputStream output = upstream.getOutputStream()) { output.write(payload); }
            }
            int status = upstream.getResponseCode();
            if (status >= 300 && status < 400) throw new IOException("Local redirect refused");
            InputStream stream = status < 400 ? upstream.getInputStream() : upstream.getErrorStream();
            byte[] data;
            if (stream == null) data = new byte[0];
            else try (InputStream input = stream) { data = readBounded(input, limit); }
            String type = upstream.getContentType();
            if (type == null || type.length() > 128 || type.indexOf('\r') >= 0
                    || type.indexOf('\n') >= 0) type = "application/octet-stream";
            return new Reply(status, type, data);
        } finally {
            upstream.disconnect();
        }
    }

    private static byte[] readBounded(InputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] block = new byte[8192];
        int size;
        while ((size = input.read(block)) != -1) {
            if (output.size() + size > limit) throw new IOException("Local response too large");
            output.write(block, 0, size);
        }
        return output.toByteArray();
    }
}
