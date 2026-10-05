"""Build a two-zone variant of the original online Android adapter in memory.

The original account flow stays online. The local game zone gets its own
loopback listener, so selecting another zone never leaves a sticky mode flag.
"""

from __future__ import annotations

import hashlib

from patch_local_mode_bridge import ONLINE_APPLICATION, ONLINE_APPLICATION_SHA256


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"OfflineApplication anchor count {source.count(old)}: {old[:80]}")
    return source.replace(old, new, 1)


def patch(source: bytes) -> bytes:
    if hashlib.sha256(source).hexdigest() != ONLINE_APPLICATION_SHA256:
        raise ValueError("Online adapter source changed; review anchors first")
    text = source.decode("utf-8")
    text = replace_once(text,
        "import org.json.JSONObject;\n",
        "import org.json.JSONArray;\nimport org.json.JSONObject;\n")
    text = replace_once(text,
        "    private static final int ORIGINAL_UI_PORT = 19878;\n",
        "    private static final int ORIGINAL_UI_PORT = 19878;\n"
        "    private static final int LOCAL_GAME_PORT = 19879;\n")
    text = replace_once(text,
        "    private boolean originalUiAuth;\n",
        "    private boolean originalUiAuth;\n"
        "    private volatile boolean localMirrorActive;\n"
        "    private final Object zoneMirrorLock = new Object();\n")
    text = replace_once(text,
        "        listener.start();\n    }\n\n    OnlineEndpoint endpoint()",
        "        listener.start();\n"
        "        if (originalUiAuth) {\n"
        "            Thread localListener = new Thread(new Runnable() {\n"
        "                @Override public void run() { listen(LOCAL_GAME_PORT, true); }\n"
        "            }, \"witch-local-game-loopback\");\n"
        "            localListener.setDaemon(true);\n"
        "            localListener.start();\n"
        "        }\n"
        "    }\n\n    OnlineEndpoint endpoint()")
    text = replace_once(text,
        "    private void listen() {\n",
        "    private void listen() { listen(listenPort, false); }\n\n"
        "    private void listen(int port, final boolean localEndpoint) {\n")
    text = replace_once(text,
        'server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), listenPort), 16);',
        'server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port), 16);')
    text = replace_once(text,
        "@Override public void run() { handle(client); }",
        "@Override public void run() { handle(client, localEndpoint); }")
    text = replace_once(text,
        "    private void handle(Socket client) {\n",
        "    private void handle(Socket client, boolean localEndpoint) {\n")
    text = replace_once(text,
        '            if (rawTarget.startsWith("/v1/route?")) {',
        '            if (!localEndpoint && rawTarget.startsWith("/v1/route?")) {')
    text = replace_once(text,
        '            if (rawTarget.startsWith("/rtm")) {',
        '            if (!localEndpoint && rawTarget.startsWith("/rtm")) {')
    text = replace_once(text,
        "            Reply reply = route(method, rawTarget, contentType, body);\n",
        "            Reply reply = localEndpoint\n"
        "                    ? routeLocalGame(method, rawTarget, contentType, body)\n"
        "                    : route(method, rawTarget, contentType, body);\n")
    text = replace_once(text,
        "            if (reply.status == 200 && \"GET\".equals(method) && isVersionRoute(rawTarget)) {\n",
        "            if (!localEndpoint && reply.status == 200 && \"GET\".equals(method)\n"
        "                    && isVersionRoute(rawTarget)) {\n")
    # A second zone is added only to successful original-account replies. The
    # online zone and its identity/nonce remain untouched.
    text = replace_once(text,
        "            return new Reply(result.status, result.contentType, result.body);\n"
        "        }\n        if (bootstrap || account || staticFixture) {",
        "            if (localMirrorActive && sessionBearer != null) {\n"
        "                try { restoreOnlineMirror(sessionBearer); }\n"
        "                catch (IOException unavailable) {\n"
        "                    return new Reply(503, \"text/plain; charset=utf-8\",\n"
        "                            bytes(\"Online state unavailable\"));\n"
        "                }\n"
        "            }\n"
        "            return new Reply(result.status, result.contentType,\n"
        "                    withLocalZone(result.body));\n"
        "        }\n        if (bootstrap || account || staticFixture) {")
    text = replace_once(text,
        "                    result = OriginalUiAuthBridge.successLegacyJson(result, email, nonce, role);\n",
        "                    result = withLocalZone(OriginalUiAuthBridge.successLegacyJson(\n"
        "                            result, email, nonce, role));\n")
    text = replace_once(text,
        "                    result = withLocalZone(OriginalUiAuthBridge.successLegacyJson(\n"
        "                            result, email, nonce, role));\n",
        "                    if (localMirrorActive) restoreOnlineMirror(bearer);\n"
        "                    result = withLocalZone(OriginalUiAuthBridge.successLegacyJson(\n"
        "                            result, email, nonce, role));\n")
    text = replace_once(text,
        "                            if (bearer.equals(sessionBearer)) LegacyStateMirror.write(getFilesDir(), state);\n",
        "                            if (bearer.equals(sessionBearer) && !localMirrorActive)\n"
        "                                LegacyStateMirror.write(getFilesDir(), state);\n")
    text = replace_once(text,
        "        String bearer = sessionBearer;\n        if (bearer == null) return new Reply(401,",
        "        String bearer = sessionBearer;\n"
        "        if (localMirrorActive && bearer != null) {\n"
        "            try { restoreOnlineMirror(bearer); }\n"
        "            catch (IOException unavailable) {\n"
        "                return new Reply(503, \"text/plain; charset=utf-8\",\n"
        "                        bytes(\"Online state unavailable\"));\n"
        "            }\n"
        "        }\n"
        "        if (bearer == null) return new Reply(401,")
    text = replace_once(text,
        "    private static boolean isVersionRoute(String path) {\n",
        """    private static byte[] withLocalZone(byte[] raw) {
        try {
            JSONObject envelope = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (!\"\".equals(envelope.optString(\"Ecode\", \"invalid\"))) return raw;
            JSONObject value = envelope.getJSONObject(\"Value\");
            JSONArray zones = value.getJSONArray(\"ZoneInfo\");
            if (zones.length() != 1) throw new IllegalStateException(\"Unexpected zone count\");
            JSONObject online = zones.getJSONObject(0);
            if (!\"1\".equals(online.getString(\"ZID\"))
                    || !\"http://127.0.0.1:19878\".equals(online.getString(\"ServerIP\")))
                throw new IllegalStateException(\"Unexpected online zone\");
            JSONObject local = new JSONObject();
            local.put(\"Platform\", \"2\");
            local.put(\"ZID\", \"2\");
            local.put(\"ZoneName\", \"本地模式\");
            local.put(\"ZoneStatus\", \"10\");
            local.put(\"ServerIP\", \"http://127.0.0.1:19879\");
            // The original client chooses the highest Sort as the default.
            // Keep the online server (Sort=1) selected for existing accounts.
            local.put(\"Sort\", 0);
            zones.put(local);
            return envelope.toString().getBytes(StandardCharsets.UTF_8);
        } catch (Exception invalid) {
            throw new IllegalStateException(\"Cannot prepare server list\", invalid);
        }
    }

    private void switchToLocalMirror() throws IOException {
        synchronized (zoneMirrorLock) {
            if (localMirrorActive) return;
            LocalModeBridge.Reply health = LocalModeBridge.requestGame(
                    \"GET\", \"/health\", null, null);
            if (health.status != 200) throw new IOException(\"Local service unavailable\");
            try {
                JSONObject identity = new JSONObject(new String(health.body, StandardCharsets.UTF_8));
                if (!\"ok\".equals(identity.optString(\"status\"))
                        || !\"single-user-local\".equals(identity.optString(\"mode\")))
                    throw new IOException(\"Unexpected local service\");
            } catch (IOException invalid) { throw invalid; }
            catch (Exception invalid) { throw new IOException(\"Invalid local identity\", invalid); }
            syncLocalMirror();
            localMirrorActive = true;
        }
    }

    private void syncLocalMirror() throws IOException {
        LocalModeBridge.Reply state = LocalModeBridge.requestGame(
                \"GET\", \"/__state\", null, null);
        if (state.status != 200 || !state.contentType.toLowerCase(Locale.ROOT)
                .startsWith(\"application/json\"))
            throw new IOException(\"Local state unavailable\");
        LegacyStateMirror.write(getFilesDir(), state.body);
    }

    private void restoreOnlineMirror(String bearer) throws IOException {
        synchronized (zoneMirrorLock) {
            if (!localMirrorActive) return;
            byte[] online = fetchMirror(bearer);
            synchronized (sessionLock) {
                if (!bearer.equals(sessionBearer)) throw new IOException(\"Online account changed\");
                LegacyStateMirror.write(getFilesDir(), online);
                localMirrorActive = false;
            }
        }
    }

    private Reply routeLocalGame(String method, String target, String contentType, byte[] body) {
        int query = target.indexOf('?');
        String path = query < 0 ? target : target.substring(0, query);
        if (query >= 0 || !originalUiAuth)
            return new Reply(400, \"text/plain; charset=utf-8\", bytes(\"Invalid local route\"));
        // Account and resource origins remain with the normal online adapter.
        if (path.startsWith(\"/account/\") || isVersionRoute(path)
                || path.endsWith(\".env\") || path.endsWith(\".mapping\"))
            return route(method, target, contentType, body);
        try {
            switchToLocalMirror();
            LocalModeBridge.Reply response = LocalModeBridge.requestGame(
                    method, path, contentType, body);
            if (\"POST\".equals(method) && response.status >= 200 && response.status < 300) {
                try { syncLocalMirror(); }
                catch (IOException unavailable) {
                    // The successful game response still belongs to the caller.
                }
            }
            return new Reply(response.status, response.contentType, response.body);
        } catch (IOException unavailable) {
            return new Reply(503, \"text/plain; charset=utf-8\",
                    bytes(\"Local service unavailable\"));
        }
    }

    private static boolean isVersionRoute(String path) {
""")
    return text.encode("utf-8")


if __name__ == "__main__":
    result = patch(ONLINE_APPLICATION.read_bytes())
    print({"sourceBytes": ONLINE_APPLICATION.stat().st_size,
           "patchedBytes": len(result), "guestEntryPoints": result.count(b"openGuest(")})
