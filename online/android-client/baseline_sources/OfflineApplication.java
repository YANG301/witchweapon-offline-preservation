package com.codex.witchweapon;

import android.app.Activity;
import android.app.Application;
import android.content.Intent;
import android.os.Bundle;
import android.os.Build;
import android.util.Base64;
import android.util.AtomicFile;
import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Iterator;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONObject;

/**
 * Transitional adapter for the author's offline APK. Unity still talks to
 * a private loopback port; only this Android process talks to the HTTPS origin.
 * Passwords and access Bearers stay in memory. Only an encrypted refresh
 * credential, account identity and original-UI nonce survive process death.
 */
public final class OfflineApplication extends Application implements Application.ActivityLifecycleCallbacks {
    private static final int NATIVE_LOGIN_PORT = 19877;
    private static final int ORIGINAL_UI_PORT = 19878;
    private static final int MAX_REQUEST = 1024 * 1024;
    private static final int MAX_RESPONSE = 16 * 1024 * 1024;
    private static final String READY_FILE = "online_bootstrap_ready";
    private static final byte[] READY_VALUE = "online-v1\n".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] ORIGINAL_UI_VALUE = "original-ui-v1\n".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] ROLE_SUMMARY_VALUE = "role-summary-v1\n".getBytes(StandardCharsets.US_ASCII);
    private static final byte[] AUTH_DIAGNOSTIC_VALUE = "auth-diagnostic-v1\n".getBytes(StandardCharsets.US_ASCII);
    private volatile String sessionBearer;
    private String sessionEmail;
    private String sessionNonce;
    private OriginalUiRoleSummary sessionRole;
    private final Object sessionLock = new Object();
    private final Object refreshLock = new Object();
    private OnlineSessionStore sessionStore;
    private long authGeneration;
    private boolean originalUiAuth;
    private boolean roleSummaryEnabled;
    private boolean authDiagnostics;
    private int listenPort = NATIVE_LOGIN_PORT;
    private OnlineEndpoint remote;
    private JSONObject localFixtures;
    private boolean loginLaunched;
    private volatile Activity gameActivity;
    private final Object mirrorLock = new Object();
    private boolean mirrorBusy;
    private boolean mirrorDirty;

    @Override public void onCreate() {
        super.onCreate();
        try { clearReadyMarker(); }
        catch (IOException staleMarker) { throw new IllegalStateException("Cannot clear stale online startup state"); }
        try { remote = OnlineEndpoint.fromAssets(this); }
        catch (IOException missingOrInvalid) { remote = null; }
        try (InputStream input = getAssets().open("original_ui_auth.txt")) {
            if (!Arrays.equals(readBounded(input, 32), ORIGINAL_UI_VALUE))
                throw new IllegalStateException("Invalid original UI auth mode");
            originalUiAuth = true;
            listenPort = ORIGINAL_UI_PORT;
        } catch (FileNotFoundException normalNativeLoginBuild) {
            originalUiAuth = false;
        } catch (IOException invalidMode) {
            throw new IllegalStateException("Cannot read original UI auth mode", invalidMode);
        }
        if (originalUiAuth) {
            try (InputStream input = getAssets().open("original_ui_role_summary.txt")) {
                if (!Arrays.equals(readBounded(input, 32), ROLE_SUMMARY_VALUE))
                    throw new IllegalStateException("Invalid role summary mode");
                roleSummaryEnabled = true;
            } catch (FileNotFoundException normalBuild) {
                roleSummaryEnabled = false;
            } catch (IOException invalidMode) {
                throw new IllegalStateException("Cannot read role summary mode", invalidMode);
            }
        }
        if (originalUiAuth) {
            try (InputStream input = getAssets().open("original_ui_auth_diagnostics.txt")) {
                if (!Arrays.equals(readBounded(input, 32), AUTH_DIAGNOSTIC_VALUE))
                    throw new IllegalStateException("Invalid account diagnostic mode");
                authDiagnostics = true;
            } catch (FileNotFoundException normalBuild) {
                authDiagnostics = false;
            } catch (IOException invalidMode) {
                throw new IllegalStateException("Cannot read account diagnostic mode", invalidMode);
            }
        }
        if (originalUiAuth) {
            // Android Keystore AES-GCM is available from API 23. Older
            // devices retain the existing process-only account behavior.
            if (Build.VERSION.SDK_INT >= 23) sessionStore = new OnlineSessionStore(this);
            try { LegacyStateMirror.clear(getFilesDir()); }
            catch (IOException staleMirror) {
                throw new IllegalStateException("Cannot clear stale account mirror", staleMirror);
            }
        }
        try (InputStream input = getAssets().open("offline_responses.json")) {
            localFixtures = new JSONObject(new String(readBounded(input, 2 * 1024 * 1024), StandardCharsets.UTF_8));
        } catch (Exception missingOrInvalid) {
            localFixtures = null;
        }
        registerActivityLifecycleCallbacks(this);
        Thread listener = new Thread(new Runnable() {
            @Override public void run() { listen(); }
        }, "witch-online-loopback");
        listener.setDaemon(true);
        listener.start();
    }

    OnlineEndpoint endpoint() { return remote; }

    boolean hasSession() { return sessionBearer != null; }

    void acceptSession(String bearer) {
        if (bearer == null || bearer.isEmpty() || bearer.length() > 512) throw new IllegalArgumentException("Invalid session");
        synchronized (sessionLock) {
            sessionEmail = null;
            sessionNonce = null;
            sessionRole = null;
            sessionBearer = bearer;
        }
    }

    private final OriginalUiAuthBridge.SessionState originalAccountSession =
            new OriginalUiAuthBridge.SessionState() {
        @Override public void acceptVerified(OnlineAuthTokens tokens, String email, String nonce,
                                             OriginalUiRoleSummary role, long generation) throws IOException {
            // Fetching can fail without disturbing the current account.
            byte[] mirror = fetchMirror(tokens.access);
            String previousRefresh = null;
            synchronized (refreshLock) {
                synchronized (sessionLock) {
                    if (generation != authGeneration) throw new IOException("Stale account attempt");
                    OnlineSessionStore.Entry previous = readSavedSession();
                    if (previous != null) previousRefresh = previous.refresh;
                    sessionBearer = null;
                    sessionEmail = null;
                    sessionNonce = null;
                    sessionRole = null;
                    try {
                        clearReadyMarker();
                        LegacyStateMirror.write(getFilesDir(), mirror);
                        if (sessionStore != null) {
                            sessionStore.write(new OnlineSessionStore.Entry(
                                    email, nonce, tokens.refresh, tokens.refreshExpiresAt));
                        }
                    } catch (IOException failed) {
                        try { LegacyStateMirror.clear(getFilesDir()); }
                        catch (IOException ignored) { }
                        throw failed;
                    }
                    sessionEmail = email;
                    sessionNonce = nonce;
                    sessionRole = role;
                    sessionBearer = tokens.access;
                }
            }
            if (previousRefresh != null && !previousRefresh.equals(tokens.refresh))
                revokeAsync(previousRefresh);
        }
        @Override public OriginalUiRoleSummary activeRole(String email, String nonce) throws IOException {
            String bearer = ensureOriginalSession(email, nonce);
            if (bearer == null) return null;
            final OriginalUiRoleSummary cached;
            synchronized (sessionLock) {
                if (!bearer.equals(sessionBearer) || !email.equals(sessionEmail)
                        || !nonce.equals(sessionNonce))
                    return null;
                cached = sessionRole;
            }
            if (!roleSummaryEnabled) return cached;
            OriginalUiRoleSummary current;
            try { current = OriginalUiRoleSummary.fetch(remote, bearer); }
            catch (OriginalUiRoleSummary.Unauthorized expired) {
                bearer = renewAccessAfterUnauthorized(bearer);
                if (bearer == null) return null;
                try { current = OriginalUiRoleSummary.fetch(remote, bearer); }
                catch (OriginalUiRoleSummary.Unauthorized stillInvalid) {
                    expireSessionIfCurrent(bearer);
                    throw stillInvalid;
                }
            }
            synchronized (sessionLock) {
                if (!bearer.equals(sessionBearer) || !email.equals(sessionEmail)
                        || !nonce.equals(sessionNonce)) return null;
                sessionRole = current;
                return current;
            }
        }
    };

    private OnlineSessionStore.Entry readSavedSession() throws IOException {
        if (sessionStore == null) return null;
        try { return sessionStore.read(); }
        catch (OnlineSessionStore.Corrupt corrupt) {
            sessionStore.clear();
            return null;
        }
    }

    /** The old game's email and nonce must match the encrypted record exactly. */
    private String ensureOriginalSession(String email, String nonce) throws IOException {
        synchronized (sessionLock) {
            if (sessionBearer != null)
                return email.equals(sessionEmail) && nonce.equals(sessionNonce) ? sessionBearer : null;
        }
        synchronized (refreshLock) {
            if (sessionStore == null) return null;
            final OnlineSessionStore.Entry saved;
            final long generation;
            synchronized (sessionLock) {
                if (sessionBearer != null)
                    return email.equals(sessionEmail) && nonce.equals(sessionNonce) ? sessionBearer : null;
                generation = authGeneration;
                saved = readSavedSession();
                if (saved == null || !email.equals(saved.email) || !nonce.equals(saved.nonce)) return null;
                if (saved.expired()) {
                    sessionStore.clear();
                    throw new OriginalUiRoleSummary.Unauthorized();
                }
            }
            final OnlineAuthTokens rotated;
            try { rotated = OnlineAuthTokens.refresh(remote, saved.refresh); }
            catch (OnlineAuthTokens.Unauthorized rejected) {
                forgetSavedIfSame(saved, generation);
                throw new OriginalUiRoleSummary.Unauthorized();
            }
            synchronized (sessionLock) {
                if (generation != authGeneration || sessionBearer != null) return null;
                OnlineSessionStore.Entry current = readSavedSession();
                if (current == null || !saved.refresh.equals(current.refresh)) return null;
                // Server rotation invalidates the old credential. Commit the new
                // one before any further network work or exposing the access token.
                sessionStore.write(new OnlineSessionStore.Entry(
                        email, nonce, rotated.refresh, rotated.refreshExpiresAt));
            }
            OriginalUiRoleSummary role = roleSummaryEnabled
                    ? OriginalUiRoleSummary.fetch(remote, rotated.access)
                    : OriginalUiRoleSummary.uncreated();
            synchronized (sessionLock) {
                if (generation != authGeneration || sessionBearer != null) return null;
                OnlineSessionStore.Entry current = readSavedSession();
                if (current == null || !rotated.refresh.equals(current.refresh)) return null;
                prepareSession(rotated.access);
                sessionEmail = email;
                sessionNonce = nonce;
                sessionRole = role;
                sessionBearer = rotated.access;
                return rotated.access;
            }
        }
    }

    private void forgetSavedIfSame(OnlineSessionStore.Entry expected, long generation)
            throws IOException {
        synchronized (sessionLock) {
            if (generation != authGeneration) return;
            OnlineSessionStore.Entry current = readSavedSession();
            if (current == null || !expected.refresh.equals(current.refresh)) return;
            sessionStore.clear();
            authGeneration++;
            sessionBearer = null;
            sessionEmail = null;
            sessionNonce = null;
            sessionRole = null;
            clearReadyMarker();
            LegacyStateMirror.clear(getFilesDir());
        }
    }

    /** Serialize rotation so concurrent 401s cannot reuse one refresh token. */
    private String renewAccessAfterUnauthorized(String oldBearer) throws IOException {
        if (!originalUiAuth) return null;
        synchronized (refreshLock) {
            if (sessionStore == null) {
                expireSessionIfCurrent(oldBearer);
                throw new OriginalUiRoleSummary.Unauthorized();
            }
            final OnlineSessionStore.Entry saved;
            final long generation;
            final String email;
            final String nonce;
            synchronized (sessionLock) {
                if (sessionBearer == null) return null;
                if (!oldBearer.equals(sessionBearer)) return sessionBearer;
                generation = authGeneration;
                email = sessionEmail;
                nonce = sessionNonce;
                saved = readSavedSession();
                if (saved == null || !email.equals(saved.email) || !nonce.equals(saved.nonce)) {
                    clearOriginalAccountState();
                    throw new OriginalUiRoleSummary.Unauthorized();
                }
                if (saved.expired()) {
                    forgetSavedIfSame(saved, generation);
                    throw new OriginalUiRoleSummary.Unauthorized();
                }
            }
            final OnlineAuthTokens rotated;
            try { rotated = OnlineAuthTokens.refresh(remote, saved.refresh); }
            catch (OnlineAuthTokens.Unauthorized rejected) {
                forgetSavedIfSame(saved, generation);
                throw new OriginalUiRoleSummary.Unauthorized();
            }
            synchronized (sessionLock) {
                if (generation != authGeneration || !oldBearer.equals(sessionBearer)) return null;
                OnlineSessionStore.Entry current = readSavedSession();
                if (current == null || !saved.refresh.equals(current.refresh)) return null;
                sessionStore.write(new OnlineSessionStore.Entry(
                        email, nonce, rotated.refresh, rotated.refreshExpiresAt));
                sessionBearer = rotated.access;
                return rotated.access;
            }
        }
    }

    private void revokeAsync(final String refresh) {
        if (refresh == null) return;
        Thread task = new Thread(new Runnable() {
            @Override public void run() { OnlineAuthTokens.revoke(remote, refresh); }
        }, "witch-online-revoke");
        task.setDaemon(true);
        task.start();
    }

    private long clearOriginalAccountState() throws IOException {
        return clearOriginalAccountState(null);
    }

    private long beginOriginalAccountAttempt() {
        synchronized (refreshLock) {
            synchronized (sessionLock) { return ++authGeneration; }
        }
    }

    private long clearOriginalAccountState(String expectedBearer) throws IOException {
        final String oldRefresh;
        final long generation;
        synchronized (refreshLock) {
            synchronized (sessionLock) {
                if (expectedBearer != null && !expectedBearer.equals(sessionBearer)) return -1;
                authGeneration++;
                sessionBearer = null;
                sessionEmail = null;
                sessionNonce = null;
                sessionRole = null;
                OnlineSessionStore.Entry saved = readSavedSession();
                oldRefresh = saved == null ? null : saved.refresh;
                if (sessionStore != null) sessionStore.clear();
                IOException problem = null;
                try { clearReadyMarker(); }
                catch (IOException failed) { problem = failed; }
                try { LegacyStateMirror.clear(getFilesDir()); }
                catch (IOException failed) { if (problem == null) problem = failed; }
                if (problem != null) throw problem;
                generation = authGeneration;
            }
        }
        revokeAsync(oldRefresh);
        return generation;
    }

    /** Complete the first authenticated mirror before exposing the Unity UI. */
    void prepareSession(String bearer) throws IOException {
        if (bearer == null || bearer.isEmpty() || bearer.length() > 512)
            throw new IOException("Invalid session");
        // A failed HTTPS request or mirror write must never leave a prior
        // ready marker that would seed the original game's account cache.
        clearReadyMarker();
        byte[] state = fetchMirror(bearer);
        LegacyStateMirror.write(getFilesDir(), state);
        writeReadyMarker();
    }

    private AtomicFile readyMarker() {
        return new AtomicFile(new File(getFilesDir(), READY_FILE));
    }

    private void clearReadyMarker() throws IOException {
        AtomicFile marker = readyMarker();
        marker.delete();
        File base = marker.getBaseFile();
        if (base.exists() || new File(base.getPath() + ".bak").exists()
                || new File(base.getPath() + ".new").exists())
            throw new IOException("Unable to clear online startup marker");
    }

    private void writeReadyMarker() throws IOException {
        AtomicFile marker = readyMarker();
        FileOutputStream output = null;
        try {
            output = marker.startWrite();
            output.write(READY_VALUE);
            marker.finishWrite(output);
        } catch (IOException failed) {
            if (output != null) marker.failWrite(output);
            marker.delete();
            throw failed;
        }
        try (InputStream check = new FileInputStream(marker.getBaseFile())) {
            if (!Arrays.equals(readBounded(check, 32), READY_VALUE)) {
                marker.delete();
                throw new IOException("Invalid online startup marker");
            }
        } catch (IOException failed) {
            marker.delete();
            throw failed;
        }
    }

    /** Native-entry process-only session reset. Original UI uses clearOriginalAccountState. */
    void clearSession() {
        synchronized (sessionLock) {
            authGeneration++;
            sessionBearer = null;
            sessionEmail = null;
            sessionNonce = null;
            sessionRole = null;
            try { clearReadyMarker(); }
            catch (IOException failed) {
                // Network requests still fail closed because the Bearer is gone.
                // A later Application start refuses stale marker state entirely.
            }
            if (originalUiAuth) {
                try { LegacyStateMirror.clear(getFilesDir()); }
                catch (IOException failed) {
                    // The Bearer and local nonce are already gone; a later
                    // manual login also verifies mirror removal before auth.
                }
            }
        }
    }

    private byte[] fetchMirror(String bearer) throws IOException {
        if (remote == null) throw new IOException("HTTPS endpoint unavailable");
        HttpsURLConnection upstream = remote.open("/api/v1/legacy-state");
        try {
            upstream.setRequestMethod("GET");
            upstream.setRequestProperty("Authorization", "Bearer " + bearer);
            int code = upstream.getResponseCode();
            if (code != 200) throw new IOException("State mirror response was not successful");
            try (InputStream input = upstream.getInputStream()) { return readBounded(input, 65536); }
        } finally { upstream.disconnect(); }
    }

    private void refreshMirrorAsync() {
        final String bearer = sessionBearer;
        if (bearer == null) return;
        synchronized (mirrorLock) {
            mirrorDirty = true;
            if (mirrorBusy) return;
            mirrorBusy = true;
        }
        Thread task = new Thread(new Runnable() {
            @Override public void run() {
                while (true) {
                    synchronized (mirrorLock) { mirrorDirty = false; }
                    try {
                        byte[] state = fetchMirror(bearer);
                        synchronized (sessionLock) {
                            if (bearer.equals(sessionBearer)) LegacyStateMirror.write(getFilesDir(), state);
                        }
                    } catch (IOException failed) {
                        // The last authenticated mirror remains readable, but no
                        // failed fetch is ever presented as a successful update.
                    }
                    synchronized (mirrorLock) {
                        if (!mirrorDirty || !bearer.equals(sessionBearer)) {
                            mirrorBusy = false;
                            return;
                        }
                    }
                }
            }
        }, "witch-online-mirror");
        task.setDaemon(true);
        task.start();
    }

    private void listen() {
        try (ServerSocket server = new ServerSocket()) {
            server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), listenPort), 16);
            while (true) {
                final Socket client = server.accept();
                Thread worker = new Thread(new Runnable() {
                    @Override public void run() { handle(client); }
                }, "witch-online-request");
                worker.setDaemon(true);
                worker.start();
            }
        } catch (IOException failed) {
            // Fail closed. The original game will see a connection error.
        }
    }

    private void handle(Socket client) {
        try (Socket socket = client) {
            socket.setSoTimeout(25000);
            InputStream input = new BufferedInputStream(socket.getInputStream());
            String requestLine = readLine(input);
            if (requestLine == null) return;
            String[] parts = requestLine.split(" ", 3);
            if (parts.length != 3 || !parts[2].startsWith("HTTP/1.")) {
                write(socket, new Reply(400, "text/plain; charset=utf-8", bytes("Invalid request")));
                return;
            }
            String method = parts[0];
            String rawTarget = parts[1];
            if (!"GET".equals(method) && !"POST".equals(method)) {
                write(socket, new Reply(405, "text/plain; charset=utf-8", bytes("Method not supported")));
                return;
            }
            if (!rawTarget.startsWith("/") || rawTarget.indexOf('#') >= 0 || rawTarget.indexOf('\\') >= 0) {
                write(socket, new Reply(400, "text/plain; charset=utf-8", bytes("Invalid target")));
                return;
            }
            int length = 0;
            String contentType = "application/x-www-form-urlencoded; charset=utf-8";
            boolean hasLength = false;
            Map<String, String> upgradeHeaders = new HashMap<>();
            int headerCount = 0;
            while (true) {
                if (++headerCount > 64) throw new IOException("Too many headers");
                String header = readLine(input);
                if (header == null) throw new IOException("Missing header end");
                if (header.isEmpty()) break;
                int colon = header.indexOf(':');
                if (colon <= 0) throw new IOException("Invalid header");
                String name = header.substring(0, colon).trim().toLowerCase(Locale.ROOT);
                String value = header.substring(colon + 1).trim();
                if ("content-length".equals(name)) {
                    if (hasLength) throw new IOException("Duplicate length");
                    length = Integer.parseInt(value);
                    hasLength = true;
                } else if ("content-type".equals(name)) {
                    if (value.length() > 128 || value.indexOf('\r') >= 0 || value.indexOf('\n') >= 0)
                        throw new IOException("Invalid content type");
                    contentType = value;
                } else if ("transfer-encoding".equals(name)) {
                    throw new IOException("Chunked request unsupported");
                } else if ("upgrade".equals(name) || "connection".equals(name)
                        || "sec-websocket-key".equals(name)
                        || "sec-websocket-version".equals(name)) {
                    if (upgradeHeaders.put(name, value) != null)
                        throw new IOException("Duplicate upgrade header");
                }
            }
            if (length < 0 || length > MAX_REQUEST) throw new IOException("Request too large");
            if (rawTarget.startsWith("/v1/route?")) {
                if (!originalUiAuth || !"GET".equals(method)
                        || !ChatWebSocketRelay.isRouteTarget(rawTarget) || length != 0)
                    write(socket, new Reply(400, "text/plain; charset=utf-8", bytes("Invalid chat route")));
                else
                    write(socket, new Reply(200, "application/json; charset=utf-8",
                            ChatWebSocketRelay.routeBody()));
                return;
            }
            if (rawTarget.startsWith("/rtm")) {
                if (!originalUiAuth || !ChatWebSocketRelay.validRequest(
                        method, rawTarget, upgradeHeaders, length)) {
                    write(socket, new Reply(400, "text/plain; charset=utf-8", bytes("Invalid chat upgrade")));
                    return;
                }
                String bearer = sessionBearer;
                if (bearer == null) {
                    write(socket, new Reply(401, "text/plain; charset=utf-8", bytes("Online login required")));
                    return;
                }
                if (remote == null) {
                    write(socket, new Reply(503, "text/plain; charset=utf-8", bytes("HTTPS endpoint unavailable")));
                    return;
                }
                for (int attempt = 0; attempt < 2; attempt++) {
                    int status;
                    try {
                        status = ChatWebSocketRelay.relay(socket, input, remote, bearer,
                                rawTarget, upgradeHeaders);
                    } catch (IOException unavailable) {
                        write(socket, new Reply(502, "text/plain; charset=utf-8",
                                bytes("Chat gateway unavailable")));
                        return;
                    }
                    if (status == 101) return;
                    if (status == 401 && originalUiAuth && attempt == 0) {
                        try { bearer = renewAccessAfterUnauthorized(bearer); }
                        catch (IOException unavailable) {
                            write(socket, new Reply(503, "text/plain; charset=utf-8",
                                    bytes("Login refresh unavailable")));
                            return;
                        }
                        if (bearer != null) continue;
                    }
                    write(socket, new Reply(status, "text/plain; charset=utf-8",
                            bytes(status == 401 ? "Online login required" : "Chat unavailable")));
                    return;
                }
                return;
            }
            byte[] body = new byte[length];
            int consumed = 0;
            while (consumed < length) {
                int count = input.read(body, consumed, length - consumed);
                if (count < 0) throw new IOException("Truncated request");
                consumed += count;
            }
            write(socket, route(method, rawTarget, contentType, body));
        } catch (Exception failed) {
            // Deliberately no exception or request logging: forms may carry secrets.
        }
    }

    private Reply route(String method, String target, String contentType, byte[] body) {
        int query = target.indexOf('?');
        String path = query < 0 ? target : target.substring(0, query);
        boolean bootstrap = path.endsWith(".env") || path.endsWith(".mapping")
                || path.equals("/getversion") || path.equals("//getversion")
                || path.equals("/m.version");
        boolean account = path.startsWith("/account/");
        boolean accountProbe = originalUiAuth && "POST".equals(method) && query < 0
                && path.equals("/account/test/ok");
        // These two author responses are fixed presentation/bootstrap data:
        // an empty protobuf and a notice JSON document. Neither reads a save.
        boolean staticFixture = "POST".equals(method) && query < 0
                && (path.equals("/misc/getLeancloudInfo")
                    || path.equals("/Notice/fetchContent"));
        if (query >= 0) {
            String parameters = target.substring(query + 1).toLowerCase(Locale.ROOT);
            if (account || parameters.contains("token") || parameters.contains("password"))
                return new Reply(400, "text/plain; charset=utf-8", bytes("Query unsupported"));
        }
        if (path.equals("/account/test/ok") && !"POST".equals(method))
            return new Reply(405, "text/plain; charset=utf-8", bytes("Method not supported"));
        if (originalUiAuth && query < 0 && "POST".equals(method)
                && path.equals("/account/user/logout")) {
            try {
                clearOriginalAccountState();
                return new Reply(200, "application/json; charset=utf-8",
                        bytes("{\"Ecode\":\"\",\"Value\":{}}"));
            } catch (IOException failed) {
                return new Reply(503, "text/plain; charset=utf-8", bytes("Account reset unavailable"));
            }
        }
        if (originalUiAuth && query < 0 && "POST".equals(method)
                && (path.equals("/account/user/login") || path.equals("/account/user/regist")
                    || path.equals("/account/user/tokenlogin"))) {
            long generation = -1;
            if (!path.equals("/account/user/tokenlogin")) {
                generation = beginOriginalAccountAttempt();
            }
            byte[] fixture = accountFixture(path);
            OriginalUiAuthBridge.Reply result = path.equals("/account/user/tokenlogin")
                    ? OriginalUiAuthBridge.tokenLogin(path, contentType, body, fixture, originalAccountSession)
                    : OriginalUiAuthBridge.authenticate(remote, path, contentType, body,
                            fixture, originalAccountSession, generation, roleSummaryEnabled,
                            authDiagnostics);
            return new Reply(result.status, result.contentType, result.body);
        }
        if (bootstrap || account || staticFixture) {
            // The original UI checks one fixed author account-probe response
            // before email login. It contains no account data or credentials.
            if (((account && !accountProbe) || (staticFixture && !originalUiAuth))
                    && sessionBearer == null)
                return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
            return localReply(path, bootstrap, account && !accountProbe);
        }
        // The legacy remote API is deliberately query-free. Original gameplay
        // parameters are POST form fields; a URL must never carry a token.
        if (query >= 0) return new Reply(400, "text/plain; charset=utf-8", bytes("Query unsupported"));
        String bearer = sessionBearer;
        if (bearer == null) return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
        if (remote == null) return new Reply(503, "text/plain; charset=utf-8", bytes("HTTPS endpoint unavailable"));
        try {
            for (int attempt = 0; attempt < 2; attempt++) {
                HttpsURLConnection upstream = remote.open("/api/v1/legacy" + path);
                try {
                    upstream.setRequestMethod(method);
                    upstream.setRequestProperty("Authorization", "Bearer " + bearer);
                    if ("POST".equals(method)) {
                        byte[] forwardedBody = appendBattleEnergy(path, contentType, body);
                        upstream.setDoOutput(true);
                        upstream.setRequestProperty("Content-Type", contentType);
                        upstream.setFixedLengthStreamingMode(forwardedBody.length);
                        try (OutputStream output = upstream.getOutputStream()) { output.write(forwardedBody); }
                    }
                    int status = upstream.getResponseCode();
                    if (status == 401 && originalUiAuth && attempt == 0) {
                        try { bearer = renewAccessAfterUnauthorized(bearer); }
                        catch (OriginalUiRoleSummary.Unauthorized invalidRefresh) {
                            return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                        } catch (IOException temporarilyUnavailable) {
                            return new Reply(503, "text/plain; charset=utf-8", bytes("Login refresh unavailable"));
                        }
                        if (bearer == null)
                            return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                        continue;
                    }
                    InputStream stream = status < 400 ? upstream.getInputStream() : upstream.getErrorStream();
                    byte[] result;
                    if (stream == null) result = new byte[0];
                    else try (InputStream input = stream) { result = readBounded(input, MAX_RESPONSE); }
                    String type = upstream.getContentType();
                    if (type == null || type.length() > 128 || type.indexOf('\r') >= 0 || type.indexOf('\n') >= 0)
                        type = "application/octet-stream";
                    if (status == 401) expireSessionIfCurrent(bearer);
                    if (status != 401 && !bearer.equals(sessionBearer))
                        return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                    if (status >= 200 && status < 300 && "POST".equals(method)) refreshMirrorAsync();
                    return new Reply(status, type, result);
                } finally {
                    upstream.disconnect();
                }
            }
            return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
        } catch (Exception failed) {
            return new Reply(502, "text/plain; charset=utf-8", bytes("HTTPS upstream unavailable"));
        }
    }

    private void expireSessionIfCurrent(String bearer) throws IOException {
        if (originalUiAuth) {
            clearOriginalAccountState(bearer);
            return;
        }
        synchronized (sessionLock) {
            if (!bearer.equals(sessionBearer)) return;
            clearSession();
        }
        final Activity activity = gameActivity;
        if (activity == null) return;
        activity.runOnUiThread(new Runnable() {
            @Override public void run() {
                if (sessionBearer == null && !loginLaunched) {
                    loginLaunched = true;
                    activity.startActivity(new Intent(activity, OnlineLoginActivity.class));
                }
            }
        });
    }

    private Reply localReply(String path, boolean bootstrap, boolean account) {
        if (localFixtures == null) return new Reply(503, "text/plain; charset=utf-8", bytes("Local bootstrap missing"));
        JSONObject item = localFixtures.optJSONObject(path);
        if (item == null && bootstrap && path.endsWith(".env")) item = localFixtures.optJSONObject("*.env");
        if (item == null && bootstrap && path.endsWith(".mapping")) item = localFixtures.optJSONObject("*.mapping");
        if (item == null) return new Reply(501, "text/plain; charset=utf-8", bytes("Legacy endpoint unavailable"));
        int status = item.optInt("status", 200);
        String type = item.optString("type", "application/octet-stream");
        try {
            byte[] result = item.has("base64")
                    ? Base64.decode(item.getString("base64"), Base64.DEFAULT)
                    : bytes(item.optString("body", ""));
            if (account && type.startsWith("application/json")) {
                if (originalUiAuth) {
                    String email;
                    String nonce;
                    String bearer;
                    OriginalUiRoleSummary role;
                    synchronized (sessionLock) {
                        email = sessionEmail;
                        nonce = sessionNonce;
                        bearer = sessionBearer;
                        role = sessionRole;
                    }
                    if (email == null || nonce == null || bearer == null || role == null)
                        return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                    // getZone/token/get remain local author fixtures, but may
                    // not reintroduce the old shared offline-local credential.
                    if (roleSummaryEnabled && path.equals("/account/user/getZone")) {
                        try { role = OriginalUiRoleSummary.fetch(remote, bearer); }
                        catch (OriginalUiRoleSummary.Unauthorized expired) {
                            try {
                                bearer = renewAccessAfterUnauthorized(bearer);
                                if (bearer == null)
                                    return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                                role = OriginalUiRoleSummary.fetch(remote, bearer);
                            } catch (OriginalUiRoleSummary.Unauthorized invalid) {
                                expireSessionIfCurrent(bearer);
                                return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                            } catch (IOException unavailable) {
                                return new Reply(503, "text/plain; charset=utf-8", bytes("Role summary unavailable"));
                            }
                        } catch (IOException unavailable) {
                            return new Reply(503, "text/plain; charset=utf-8", bytes("Role summary unavailable"));
                        }
                        synchronized (sessionLock) {
                            if (!bearer.equals(sessionBearer) || !email.equals(sessionEmail)
                                    || !nonce.equals(sessionNonce))
                                return new Reply(401, "text/plain; charset=utf-8", bytes("Online login required"));
                            sessionRole = role;
                        }
                    }
                    result = OriginalUiAuthBridge.successLegacyJson(result, email, nonce, role);
                } else {
                    // The transitional native-login build must not cache its
                    // old fixed LoginToken as a real online credential.
                    JSONObject envelope = new JSONObject(new String(result, StandardCharsets.UTF_8));
                    JSONObject value = envelope.optJSONObject("Value");
                    if (value != null) value.put("LoginToken", "");
                    result = bytes(envelope.toString());
                }
            }
            return new Reply(status, type, result);
        } catch (Exception badFixture) {
            return new Reply(503, "text/plain; charset=utf-8", bytes("Invalid local bootstrap"));
        }
    }

    private byte[] accountFixture(String path) {
        if (localFixtures == null) return null;
        JSONObject item = localFixtures.optJSONObject(path);
        if (item == null || !item.optString("type", "").startsWith("application/json")) return null;
        String body = item.optString("body", "");
        return body.isEmpty() ? null : bytes(body);
    }

    private byte[] appendBattleEnergy(String path, String contentType, byte[] body) {
        if (!path.equals("/level/pushMainLineProgress")
                && !path.equals("/game/level/pushMainLineProgress")) return body;
        if (contentType == null || !contentType.toLowerCase(Locale.ROOT)
                .startsWith("application/x-www-form-urlencoded")) return body;
        File file = new File(getFilesDir(), "offline_battle_energy.json");
        if (!file.isFile() || file.length() < 2 || file.length() > 8192) return body;
        try (InputStream input = new FileInputStream(file)) {
            JSONObject state = new JSONObject(new String(readBounded(input, 8192), StandardCharsets.UTF_8));
            String key = state.optString("startKey", "");
            if (!key.matches("[0-9-]{1,128}")) return body;
            StringBuilder appended = new StringBuilder();
            appended.append("energyStartKey=").append(URLEncoder.encode(key, "UTF-8"));
            int slots = 0;
            for (Iterator<String> keys = state.keys(); keys.hasNext();) {
                String field = keys.next();
                if (!field.matches("mazeEnergy_[0-9]{1,32}")) continue;
                if (++slots > 16) return body;
                double energy = state.optDouble(field, Double.NaN);
                if (Double.isNaN(energy) || Double.isInfinite(energy)) return body;
                energy = Math.max(0, Math.min(1000, energy));
                appended.append('&').append(field).append('=').append(energy);
            }
            byte[] extra = bytes(appended.toString());
            if (body.length + extra.length + 1 > MAX_REQUEST) return body;
            ByteArrayOutputStream joined = new ByteArrayOutputStream(body.length + extra.length + 1);
            joined.write(body);
            if (body.length > 0) joined.write('&');
            joined.write(extra);
            return joined.toByteArray();
        } catch (Exception invalidOrRacingFile) {
            return body;
        }
    }

    private static String readLine(InputStream input) throws IOException {
        ByteArrayOutputStream line = new ByteArrayOutputStream();
        while (true) {
            int value = input.read();
            if (value < 0) return line.size() == 0 ? null : line.toString("UTF-8");
            if (value == '\n') return line.toString("UTF-8");
            if (value != '\r') line.write(value);
            if (line.size() > 8192) throw new IOException("Header line too long");
        }
    }

    private static byte[] readBounded(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) >= 0) {
            result.write(buffer, 0, count);
            if (result.size() > maximum) throw new IOException("Response too large");
        }
        return result.toByteArray();
    }

    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }

    private static void write(Socket socket, Reply reply) throws IOException {
        OutputStream output = socket.getOutputStream();
        String headers = "HTTP/1.1 " + reply.status + " " + (reply.status >= 400 ? "Error" : "OK")
                + "\r\nContent-Type: " + reply.contentType
                + "\r\nContent-Length: " + reply.body.length
                + "\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n";
        output.write(headers.getBytes(StandardCharsets.US_ASCII));
        output.write(reply.body);
        output.flush();
    }

    private static final class Reply {
        final int status;
        final String contentType;
        final byte[] body;
        Reply(int status, String contentType, byte[] body) {
            this.status = status;
            this.contentType = contentType;
            this.body = body;
        }
    }

    @Override public void onActivityResumed(Activity activity) {
        if (!"com.shuiqinling.ww.android.LingGameActivity".equals(activity.getClass().getName())) return;
        gameActivity = activity;
        if (originalUiAuth) return;
        if (sessionBearer != null || loginLaunched) return;
        loginLaunched = true;
        activity.startActivity(new Intent(activity, OnlineLoginActivity.class));
    }
    @Override public void onActivityCreated(Activity activity, Bundle state) { }
    @Override public void onActivityStarted(Activity activity) { }
    @Override public void onActivityPaused(Activity activity) {
        if (gameActivity == activity) gameActivity = null;
    }
    @Override public void onActivityStopped(Activity activity) { }
    @Override public void onActivitySaveInstanceState(Activity activity, Bundle state) { }
    @Override public void onActivityDestroyed(Activity activity) {
        if (activity instanceof OnlineLoginActivity) loginLaunched = false;
    }
}
