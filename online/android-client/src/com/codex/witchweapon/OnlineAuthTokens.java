package com.codex.witchweapon;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Calendar;
import java.util.Locale;
import java.util.TimeZone;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

/** Short-lived access token plus the rotating, 30-day refresh credential. */
final class OnlineAuthTokens {
    private static final Pattern TOKEN = Pattern.compile("[A-Za-z0-9_-]{43}");
    private static final Pattern RFC3339 = Pattern.compile(
            "(\\d{4})-(\\d{2})-(\\d{2})T(\\d{2}):(\\d{2}):(\\d{2})"
            + "(?:\\.(\\d{1,9}))?(Z|[+-]\\d{2}:\\d{2})");
    final String access;
    final String refresh;
    final long refreshExpiresAt;

    private OnlineAuthTokens(String access, String refresh, long refreshExpiresAt) {
        this.access = access;
        this.refresh = refresh;
        this.refreshExpiresAt = refreshExpiresAt;
    }

    static OnlineAuthTokens parse(byte[] answer) throws IOException {
        if (answer == null || answer.length == 0 || answer.length > 65536)
            throw new IOException("Invalid auth response size");
        try {
            JSONObject json = new JSONObject(new String(answer, StandardCharsets.UTF_8));
            String access = json.getString("token");
            String refresh = json.getString("refreshToken");
            if (!TOKEN.matcher(access).matches() || !TOKEN.matcher(refresh).matches())
                throw new IOException("Invalid auth token");
            long expiry = parseExpiry(json.getString("refreshExpiresAt"));
            if (expiry <= System.currentTimeMillis()) throw new IOException("Expired refresh token");
            return new OnlineAuthTokens(access, refresh, expiry);
        } catch (IOException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IOException("Invalid auth response");
        }
    }

    static long parseExpiry(String value) throws IOException {
        Matcher match = RFC3339.matcher(value);
        if (!match.matches()) throw new IOException("Invalid refresh expiry");
        try {
            Calendar date = Calendar.getInstance(TimeZone.getTimeZone("UTC"), Locale.ROOT);
            date.clear();
            date.setLenient(false);
            date.set(Integer.parseInt(match.group(1)), Integer.parseInt(match.group(2)) - 1,
                    Integer.parseInt(match.group(3)), Integer.parseInt(match.group(4)),
                    Integer.parseInt(match.group(5)), Integer.parseInt(match.group(6)));
            String fraction = match.group(7);
            if (fraction != null)
                date.set(Calendar.MILLISECOND, Integer.parseInt((fraction + "000").substring(0, 3)));
            long result = date.getTimeInMillis();
            String zone = match.group(8);
            if (!"Z".equals(zone)) {
                int hours = Integer.parseInt(zone.substring(1, 3));
                int minutes = Integer.parseInt(zone.substring(4, 6));
                if (hours > 23 || minutes > 59) throw new IOException("Invalid refresh timezone");
                long offset = (hours * 60L + minutes) * 60000L;
                result += zone.charAt(0) == '+' ? -offset : offset;
            }
            return result;
        } catch (IOException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IOException("Invalid refresh expiry");
        }
    }

    static OnlineAuthTokens refresh(OnlineEndpoint endpoint, String refreshToken) throws IOException {
        if (endpoint == null || refreshToken == null || !TOKEN.matcher(refreshToken).matches())
            throw new IOException("Refresh unavailable");
        HttpsURLConnection connection = endpoint.open("/api/v1/auth/refresh");
        try {
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            connection.setRequestProperty("Accept", "application/json");
            JSONObject request = new JSONObject();
            request.put("refreshToken", refreshToken);
            byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(body); }
            int status = connection.getResponseCode();
            if (status == 401) throw new Unauthorized();
            if (status != 200) throw new IOException("Refresh server unavailable");
            try (InputStream input = connection.getInputStream()) { return parse(readBounded(input)); }
        } catch (IOException failed) {
            throw failed;
        } catch (Exception failed) {
            throw new IOException("Refresh request failed");
        } finally {
            connection.disconnect();
        }
    }

    /** Local sign-out takes effect first; remote revocation is best effort. */
    static void revoke(OnlineEndpoint endpoint, String refreshToken) {
        if (endpoint == null || refreshToken == null || !TOKEN.matcher(refreshToken).matches()) return;
        HttpsURLConnection connection = null;
        try {
            connection = endpoint.open("/api/v1/auth/revoke");
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
            JSONObject request = new JSONObject();
            request.put("refreshToken", refreshToken);
            byte[] body = request.toString().getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(body.length);
            try (OutputStream output = connection.getOutputStream()) { output.write(body); }
            connection.getResponseCode();
        } catch (Exception ignored) {
            // The encrypted local credential was already removed.
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static byte[] readBounded(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) >= 0) {
            output.write(buffer, 0, count);
            if (output.size() > 65536) throw new IOException("Auth response too large");
        }
        return output.toByteArray();
    }

    static final class Unauthorized extends IOException {
        Unauthorized() { super("Refresh token rejected"); }
    }
}
