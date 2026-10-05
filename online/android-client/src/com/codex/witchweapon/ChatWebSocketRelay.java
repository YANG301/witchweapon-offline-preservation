package com.codex.witchweapon;

import android.util.Base64;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Locale;
import java.util.Map;
import javax.net.ssl.SSLSocket;

/**
 * Bridges only the original LeanCloud JSON WebSocket to the authenticated
 * game gateway. The original Unity UI and SDK remain responsible for all
 * frame contents and chat interactions.
 */
final class ChatWebSocketRelay {
    private static final String GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";
    private static final int MAX_HEADER_LINES = 64;

    private ChatWebSocketRelay() { }

    static boolean isChatTarget(String target) {
        String prefix = "/rtm?subprotocol=lc.json.";
        if (target == null || !target.startsWith(prefix)) return false;
        String version = target.substring(prefix.length());
        return version.matches("[A-Za-z0-9._-]{1,64}");
    }

    static boolean isRouteTarget(String target) {
        return target != null && target.matches("/v1/route\\?appId=[A-Za-z0-9_-]{8,80}&secure=1");
    }

    static byte[] routeBody() {
        String server = "ws://127.0.0.1:19878/rtm";
        long expires = System.currentTimeMillis() / 1000L + 3600L;
        String json = "{\"server\":\"" + server + "\",\"secondary\":\"" + server
                + "\",\"ttl\":3600,\"expire\":" + expires + ",\"groupId\":\"ww-chat\"}";
        return json.getBytes(StandardCharsets.US_ASCII);
    }

    static boolean validRequest(String method, String target, Map<String, String> headers,
                                int contentLength) {
        if (!"GET".equals(method) || !isChatTarget(target) || contentLength != 0) return false;
        if (!tokenContains(headers.get("upgrade"), "websocket")
                || !tokenContains(headers.get("connection"), "upgrade")
                || !"13".equals(headers.get("sec-websocket-version"))) return false;
        String key = headers.get("sec-websocket-key");
        if (key == null || !key.matches("[A-Za-z0-9+/]{22}==")) return false;
        try { return Base64.decode(key, Base64.NO_WRAP).length == 16; }
        catch (IllegalArgumentException invalid) { return false; }
    }

    static String acceptValue(String key) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-1")
                    .digest((key + GUID).getBytes(StandardCharsets.US_ASCII));
            return Base64.encodeToString(digest, Base64.NO_WRAP);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    /** Returns an HTTP status; 101 means the bridge ran until the socket closed. */
    static int relay(Socket client, InputStream clientInput, OnlineEndpoint endpoint,
                     String bearer, String target, Map<String, String> headers) throws IOException {
        if (endpoint == null || bearer == null || !bearer.matches("[A-Za-z0-9_-]{43}")) return 401;
        if (!validRequest("GET", target, headers, 0)) return 400;
        String key = headers.get("sec-websocket-key");
        String expected = acceptValue(key);
        try (SSLSocket upstream = endpoint.openChatSocket()) {
            OutputStream output = upstream.getOutputStream();
            String request = "GET /api/v1/chat/rtm?" + target.substring(target.indexOf('?') + 1)
                    + " HTTP/1.1\r\nHost: " + endpoint.hostHeader()
                    + "\r\nAuthorization: Bearer " + bearer
                    + "\r\nUpgrade: websocket\r\nConnection: Upgrade"
                    + "\r\nSec-WebSocket-Key: " + key
                    + "\r\nSec-WebSocket-Version: 13\r\n\r\n";
            output.write(request.getBytes(StandardCharsets.US_ASCII));
            output.flush();
            InputStream upstreamInput = new BufferedInputStream(upstream.getInputStream());
            String statusLine = readLine(upstreamInput);
            if (statusLine == null) return 502;
            String[] statusParts = statusLine.split(" ", 3);
            if (statusParts.length < 2 || !"HTTP/1.1".equals(statusParts[0])) return 502;
            int status;
            try { status = Integer.parseInt(statusParts[1]); }
            catch (NumberFormatException invalid) { return 502; }
            java.util.HashMap<String, String> response = new java.util.HashMap<>();
            for (int count = 0; count < MAX_HEADER_LINES; count++) {
                String line = readLine(upstreamInput);
                if (line == null) return 502;
                if (line.isEmpty()) break;
                int colon = line.indexOf(':');
                if (colon <= 0) return 502;
                String name = line.substring(0, colon).trim().toLowerCase(Locale.ROOT);
                if (response.put(name, line.substring(colon + 1).trim()) != null) return 502;
                if (count == MAX_HEADER_LINES - 1) return 502;
            }
            if (status != 101) return status == 401 ? 401 : 502;
            if (!tokenContains(response.get("upgrade"), "websocket")
                    || !tokenContains(response.get("connection"), "upgrade")
                    || !expected.equals(response.get("sec-websocket-accept"))
                    || response.containsKey("sec-websocket-protocol")
                    || response.containsKey("sec-websocket-extensions")) return 502;
            String accepted = "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket"
                    + "\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + expected + "\r\n\r\n";
            OutputStream clientOutput = client.getOutputStream();
            clientOutput.write(accepted.getBytes(StandardCharsets.US_ASCII));
            clientOutput.flush();
            client.setSoTimeout(0);
            upstream.setSoTimeout(0);
            Thread reverse = new Thread(new Runnable() {
                @Override public void run() {
                    try { copy(upstreamInput, clientOutput); }
                    catch (IOException closed) { }
                    finally {
                        try { client.close(); } catch (IOException ignored) { }
                        try { upstream.close(); } catch (IOException ignored) { }
                    }
                }
            }, "witch-chat-relay-reverse");
            reverse.setDaemon(true);
            reverse.start();
            try { copy(clientInput, output); }
            catch (IOException closed) { }
            finally {
                try { client.close(); } catch (IOException ignored) { }
                try { upstream.close(); } catch (IOException ignored) { }
                try { reverse.join(5000); }
                catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); }
            }
            return 101;
        }
    }

    private static boolean tokenContains(String value, String token) {
        if (value == null) return false;
        for (String part : value.split(",")) {
            if (token.equalsIgnoreCase(part.trim())) return true;
        }
        return false;
    }

    private static String readLine(InputStream input) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        while (true) {
            int value = input.read();
            if (value < 0) return line.size() == 0 ? null : line.toString("US-ASCII");
            if (value == '\n') return line.toString("US-ASCII");
            if (value != '\r') line.write(value);
            if (line.size() > 8192) throw new IOException("WebSocket header too long");
        }
    }

    private static void copy(InputStream input, OutputStream output) throws IOException {
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            output.write(buffer, 0, count);
            output.flush();
        }
    }
}
