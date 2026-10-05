package com.codex.witchweapon;

import java.util.HashMap;
import java.util.Map;

/** Static protocol checks; no player message or network request is sent. */
public final class ChatWebSocketRelayTest {
    private static int checks;

    private static void require(boolean condition, String label) {
        checks++;
        if (!condition) throw new AssertionError(label);
    }

    public static void main(String[] args) {
        Map<String, String> headers = new HashMap<>();
        headers.put("upgrade", "websocket");
        headers.put("connection", "keep-alive, Upgrade");
        headers.put("sec-websocket-version", "13");
        headers.put("sec-websocket-key", "dGhlIHNhbXBsZSBub25jZQ==");
        require(ChatWebSocketRelay.validRequest("GET", "/rtm?subprotocol=lc.json.3",
                headers, 0), "original WS request");
        require("s3pPLMBiTxaQ9kYGzzhZRbK+xOo=".equals(
                ChatWebSocketRelay.acceptValue(headers.get("sec-websocket-key"))),
                "RFC 6455 accept value");
        require(!ChatWebSocketRelay.validRequest("POST", "/rtm?subprotocol=lc.json.3",
                headers, 0), "reject POST");
        require(!ChatWebSocketRelay.validRequest("GET", "/rtm?subprotocol=lc.json.3",
                headers, 1), "reject WS request body");
        require(!ChatWebSocketRelay.isChatTarget("/rtm?subprotocol=lc.json.3&host=evil"),
                "reject second query parameter");
        require(!ChatWebSocketRelay.isChatTarget("/rtm/../other?subprotocol=lc.json.3"),
                "reject other path");
        require(!ChatWebSocketRelay.isChatTarget("/rtm?subprotocol=lc.json.3%0d%0a"),
                "reject encoded header injection");
        headers.put("sec-websocket-version", "12");
        require(!ChatWebSocketRelay.validRequest("GET", "/rtm?subprotocol=lc.json.3",
                headers, 0), "reject old version");
        headers.put("sec-websocket-version", "13");
        headers.put("sec-websocket-key", "wrong");
        require(!ChatWebSocketRelay.validRequest("GET", "/rtm?subprotocol=lc.json.3",
                headers, 0), "reject malformed key");
        require(ChatWebSocketRelay.isRouteTarget("/v1/route?appId=abcdefgh1234&secure=1"),
                "fixed route query");
        require(!ChatWebSocketRelay.isRouteTarget(
                "/v1/route?appId=abcdefgh1234&secure=1&server=evil"),
                "reject route injection");
        require(new String(ChatWebSocketRelay.routeBody(), java.nio.charset.StandardCharsets.US_ASCII)
                .contains("ws://127.0.0.1:19878/rtm"), "local route target");
        System.out.println("CHAT_WS_RELAY_STATIC_TEST_OK " + checks + " assertions");
    }
}
