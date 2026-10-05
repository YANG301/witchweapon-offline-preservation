package com.codex.witchweapon;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.zip.ZipFile;
import org.json.JSONObject;

/** Pure-JVM checks of the dormant account form parser and the actual APK fixture. */
public final class OriginalUiAuthBridgeTest {
    private static int checks;

    private static void require(boolean yes, String label) {
        checks++;
        if (!yes) throw new AssertionError(label);
    }

    private static byte[] bytes(String value) { return value.getBytes(StandardCharsets.UTF_8); }

    private static byte[] read(InputStream input) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) >= 0) output.write(buffer, 0, count);
        return output.toByteArray();
    }

    private static void reject(String label, String path, String type, String form) {
        try {
            OriginalUiAuthBridge.parseCredentials(path, type, bytes(form));
            throw new AssertionError("Accepted invalid form: " + label);
        } catch (IOException expected) { checks++; }
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Pass the currently signed test APK path");
        String formType = "application/x-www-form-urlencoded; charset=UTF-8";
        String valid = "useraccount=Alice%2Btag%40Example.com&usertype=2"
                + "&password=correctHorse33&date=20260923000000000"
                + "&sign=0123456789abcdef0123456789abcdef";
        OriginalUiAuthBridge.Credentials login = OriginalUiAuthBridge.parseCredentials(
                "/account/user/login", formType, bytes(valid));
        require(!login.register, "login action");
        require("alice+tag@example.com".equals(login.email), "normalized email");
        require("correctHorse33".equals(login.password), "password decoded exactly");
        OriginalUiAuthBridge.Credentials register = OriginalUiAuthBridge.parseCredentials(
                "/account/user/regist", formType,
                bytes(valid + "&cdkey=&smscode=&bundleid=com.example.test&cid=2"));
        require(register.register, "register action");
        reject("unknown registration field", "/account/user/regist", formType,
                valid + "&cdkey=&smscode=&bundleid=com.example.test&cid=2&unexpected=x");

        reject("duplicate password", "/account/user/login", formType,
                valid + "&password=anotherPassword33");
        reject("guest type", "/account/user/login", formType,
                valid.replace("usertype=2", "usertype=3"));
        reject("bad percent", "/account/user/login", formType,
                valid.replace("correctHorse33", "bad%Q0password33"));
        reject("invalid UTF-8", "/account/user/login", formType,
                valid.replace("correctHorse33", "%C3%28password33"));
        reject("unknown field", "/account/user/login", formType, valid + "&token=forged");
        reject("register field in login", "/account/user/login", formType, valid + "&cdkey=x");
        reject("query path", "/account/user/login?x=y", formType, valid);
        reject("wrong content type", "/account/user/login", "application/json", valid);
        reject("short password", "/account/user/login", formType,
                valid.replace("correctHorse33", "short"));
        reject("missing password", "/account/user/login", formType,
                "useraccount=a%40b.test&usertype=2");
        reject("trailing separator", "/account/user/login", formType, valid + "&");

        String fakeBearer = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
        require(fakeBearer.equals(OriginalUiAuthBridge.parseBearer(
                bytes("{\"token\":\"" + fakeBearer + "\"}"))), "valid auth token");
        try {
            OriginalUiAuthBridge.parseBearer(bytes("{\"token\":\"offline-local\"}"));
            throw new AssertionError("Accepted legacy placeholder as Go bearer");
        } catch (IOException expected) { checks++; }
        require("AE0010".equals(OriginalUiAuthBridge.errorCode(false, 401)), "old login error code");
        require("DB0040".equals(OriginalUiAuthBridge.errorCode(true, 409)), "old duplicate email code");
        require("CE10114".equals(OriginalUiAuthBridge.validationErrorCode(
                new IOException("Invalid password length"))), "original password-length prompt");
        require("ONLINE_INVALID_REQUEST".equals(OriginalUiAuthBridge.validationErrorCode(
                new IOException("Invalid password characters"))), "other validation remains generic");
        java.lang.reflect.Constructor<OnlineEndpoint> endpointConstructor =
                OnlineEndpoint.class.getDeclaredConstructor(String.class);
        endpointConstructor.setAccessible(true);
        OnlineEndpoint unreachable = endpointConstructor.newInstance("https://127.0.0.1:1");
        OriginalUiAuthBridge.SessionState unusedSession = new OriginalUiAuthBridge.SessionState() {
            @Override public void acceptVerified(OnlineAuthTokens tokens, String email,
                    String localNonce, OriginalUiRoleSummary role, long generation) {
                throw new AssertionError("Invalid password must not create a session");
            }
            @Override public OriginalUiRoleSummary activeRole(String email, String localNonce) {
                throw new AssertionError("Invalid password must not read a session");
            }
        };
        OriginalUiAuthBridge.Reply shortPassword = OriginalUiAuthBridge.authenticate(
                unreachable, "/account/user/regist", formType,
                bytes(valid.replace("correctHorse33", "shortpass11")
                        + "&cdkey=&smscode=&bundleid=com.example.test&cid=2"),
                bytes("{}"), unusedSession, 0, false);
        require(shortPassword.status == 200 && "CE10114".equals(new JSONObject(
                new String(shortPassword.body, StandardCharsets.UTF_8)).getString("Ecode")),
                "11-character registration returns the original password-length error");
        OriginalUiAuthBridge.Reply unavailable = OriginalUiAuthBridge.authenticate(
                null, "/account/user/login", formType, bytes(valid), bytes("{}"), null, 0, false);
        require(unavailable.status == 200 && !"".equals(new JSONObject(
                new String(unavailable.body, StandardCharsets.UTF_8)).getString("Ecode")),
                "HTTP 200 legacy error envelope");

        final String nonce = OriginalUiAuthBridge.newNonce();
        require(nonce.matches("[0-9a-f]{48}") && !nonce.equals(OriginalUiAuthBridge.newNonce()),
                "fresh process-local nonce");
        String[] cached = OriginalUiAuthBridge.parseTokenLogin(
                "/account/user/tokenlogin", formType,
                bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce));
        require(login.email.equals(cached[0]) && nonce.equals(cached[1]), "strict cached-login form");
        String[] oldCache = OriginalUiAuthBridge.parseTokenLogin("/account/user/tokenlogin",
                formType, bytes("useraccount=alice%40example.com&token=offline-local"));
        require("offline-local".equals(oldCache[1]), "old cache parsed for expired-token reply");

        final OriginalUiRoleSummary existingRole = OriginalUiRoleSummary.parse(bytes(
                "{\"version\":1,\"exists\":true,\"roleId\":\"87123456789\",\"name\":\"Alice\"}"));
        final OriginalUiRoleSummary freshRole = OriginalUiRoleSummary.parse(bytes(
                "{\"version\":1,\"exists\":false,\"roleId\":\"\",\"name\":\"\"}"));

        try (ZipFile apk = new ZipFile(args[0])) {
            byte[] raw;
            try (InputStream input = apk.getInputStream(apk.getEntry("assets/offline_responses.json"))) {
                raw = read(input);
            }
            JSONObject fixtures = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            for (String path : new String[]{"/account/user/login", "/account/user/regist"}) {
                byte[] legacy = OriginalUiAuthBridge.successLegacyJson(
                        bytes(fixtures.getJSONObject(path).getString("body")), login.email, nonce,
                        existingRole);
                JSONObject envelope = new JSONObject(new String(legacy, StandardCharsets.UTF_8));
                JSONObject value = envelope.getJSONObject("Value");
                require("".equals(envelope.getString("Ecode")), "success Ecode");
                require(value.getInt("UID") == 1 && value.getInt("UserType") == 2, "legacy numeric fields");
                require(login.email.equals(value.getString("Email")), "legacy email");
                require(nonce.equals(value.getString("LoginToken")), "fresh local login token");
                require(nonce.equals(value.getString("Token")), "fresh local game token");
                require("87123456789".equals(value.getJSONArray("ExistRoles")
                        .getJSONObject(0).getString("RID")), "existing role belongs to account");
                require("新丰洲".equals(value.getJSONArray("ZoneInfo")
                        .getJSONObject(0).getString("ZoneName")), "preserved current zone fixture");
                String reply = new String(legacy, StandardCharsets.UTF_8);
                require(!reply.contains(fakeBearer) && !reply.contains(login.password), "no secret in legacy JSON");
            }
            final String loginBody = fixtures.getJSONObject("/account/user/tokenlogin").getString("body");
            final String[] activeEmail = {login.email};
            final String[] activeNonce = {nonce};
            final OriginalUiRoleSummary[] activeRole = {existingRole};
            final IOException[] refreshFailure = {null};
            OriginalUiAuthBridge.SessionState active = new OriginalUiAuthBridge.SessionState() {
                @Override public void acceptVerified(OnlineAuthTokens tokens, String email, String localNonce,
                                                     OriginalUiRoleSummary role, long generation) {
                    throw new AssertionError("token login must not create a Go session");
                }
                @Override public OriginalUiRoleSummary activeRole(String email, String localNonce)
                        throws IOException {
                    if (refreshFailure[0] != null) throw refreshFailure[0];
                    return activeRole[0] != null && activeEmail[0].equals(email)
                            && activeNonce[0].equals(localNonce) ? activeRole[0] : null;
                }
            };
            OriginalUiAuthBridge.Reply validCached = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce),
                    bytes(loginBody), active);
            require(validCached.status == 200, "active cached-login HTTP status");
            require(nonce.equals(new JSONObject(new String(validCached.body, StandardCharsets.UTF_8))
                    .getJSONObject("Value").getString("Token")), "active nonce returns old success JSON");
            require("87123456789".equals(new JSONObject(new String(validCached.body, StandardCharsets.UTF_8))
                    .getJSONObject("Value").getJSONArray("ExistRoles")
                    .getJSONObject(0).getString("RID")), "cached login retains account role");
            activeRole[0] = freshRole;
            OriginalUiAuthBridge.Reply refreshed = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce),
                    bytes(loginBody), active);
            require(new JSONObject(new String(refreshed.body, StandardCharsets.UTF_8))
                    .getJSONObject("Value").getJSONArray("ExistRoles").length() == 0,
                    "cached login uses newly fetched role state");
            activeRole[0] = existingRole;
            OriginalUiAuthBridge.Reply otherAccount = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=other%40example.com&token=" + nonce),
                    bytes(loginBody), active);
            require("TTO0010".equals(new JSONObject(new String(otherAccount.body,
                    StandardCharsets.UTF_8)).getString("Ecode")), "cross-account cached login rejected");
            require(activeRole[0] == existingRole && login.email.equals(activeEmail[0]),
                    "cross-account cache does not revoke another active session");
            refreshFailure[0] = new IOException("simulated transient role failure");
            OriginalUiAuthBridge.Reply temporarilyUnavailable = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce),
                    bytes(loginBody), active);
            require("ONLINE_AUTH_UNAVAILABLE".equals(new JSONObject(new String(
                    temporarilyUnavailable.body, StandardCharsets.UTF_8)).getString("Ecode")),
                    "role refresh failure cannot yield a stale successful login");
            refreshFailure[0] = new OriginalUiRoleSummary.Unauthorized();
            OriginalUiAuthBridge.Reply expired = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce),
                    bytes(loginBody), active);
            require("TTO0010".equals(new JSONObject(new String(expired.body,
                    StandardCharsets.UTF_8)).getString("Ecode")),
                    "remote 401 yields original expired-token code");
            refreshFailure[0] = null;
            activeEmail[0] = "bob@example.com";
            activeNonce[0] = OriginalUiAuthBridge.newNonce();
            activeRole[0] = freshRole;
            OriginalUiAuthBridge.Reply switched = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=bob%40example.com&token=" + activeNonce[0]),
                    bytes(loginBody), active);
            JSONObject switchedValue = new JSONObject(new String(switched.body, StandardCharsets.UTF_8))
                    .getJSONObject("Value");
            require("bob@example.com".equals(switchedValue.getString("Email"))
                    && switchedValue.getJSONArray("ExistRoles").length() == 0,
                    "account switch did not clear prior role");
            OriginalUiAuthBridge.Reply restarted = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=Alice%2Btag%40Example.com&token=" + nonce),
                    bytes(loginBody), null);
            require("TTO0010".equals(new JSONObject(new String(restarted.body,
                    StandardCharsets.UTF_8)).getString("Ecode")), "restarted process nonce expired");
            OriginalUiAuthBridge.Reply priorOfflineCache = OriginalUiAuthBridge.tokenLogin(
                    "/account/user/tokenlogin", formType,
                    bytes("useraccount=alice%40example.com&token=offline-local"),
                    bytes(loginBody), active);
            require("TTO0010".equals(new JSONObject(new String(priorOfflineCache.body,
                    StandardCharsets.UTF_8)).getString("Ecode")), "old shared placeholder rejected");
            require(activeRole[0] == freshRole && "bob@example.com".equals(activeEmail[0]),
                    "old placeholder cannot revoke switched account");
        }
        System.out.println("ORIGINAL_UI_AUTH_BRIDGE_TEST_OK " + checks + " assertions");
    }
}
