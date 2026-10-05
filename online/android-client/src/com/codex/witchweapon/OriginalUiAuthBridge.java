package com.codex.witchweapon;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * Dormant adapter for the original account UI. It must not be routed until the
 * two original EncryptTools calls have been patched and validated to send the
 * user's clear password to this loopback service. No bearer is put in the
 * legacy JSON, original account cache, local files, exception text or logs.
 */
final class OriginalUiAuthBridge {
    private static final int MAX_FORM_BYTES = 8192;
    private static final int MAX_AUTH_REPLY_BYTES = 65536;
    private static final String JSON_TYPE = "application/json; charset=utf-8";
    private static final String FORM_TYPE = "application/x-www-form-urlencoded";
    private static final String LOGIN = "/account/user/login";
    private static final String REGISTER = "/account/user/regist";
    private static final String FIXTURE_TOKEN = "offline-local";
    private static final SecureRandom NONCE_RANDOM = new SecureRandom();

    interface SessionState {
        /** Validate the mirror, write the marker, then retain bearer/email/nonce in Application memory. */
        void acceptVerified(OnlineAuthTokens tokens, String email, String nonce,
                            OriginalUiRoleSummary role, long generation) throws IOException;
        /** Match email and nonce, restore if necessary, then fetch the authenticated role. */
        OriginalUiRoleSummary activeRole(String email, String nonce) throws IOException;
    }

    static final class Reply {
        final int status;
        final String contentType;
        final byte[] body;
        Reply(int status, byte[] body) {
            this.status = status;
            this.contentType = JSON_TYPE;
            this.body = body;
        }
    }

    static final class Credentials {
        final String email;
        final String password;
        final boolean register;
        Credentials(String email, String password, boolean register) {
            this.email = email;
            this.password = password;
            this.register = register;
        }
    }

    private OriginalUiAuthBridge() { }

    static Reply authenticate(OnlineEndpoint endpoint, String path, String contentType,
                              byte[] form, byte[] legacyFixture, SessionState session,
                              long generation, boolean roleSummaryEnabled) {
        return authenticate(endpoint, path, contentType, form, legacyFixture,
                session, generation, roleSummaryEnabled, false);
    }

    static Reply authenticate(OnlineEndpoint endpoint, String path, String contentType,
                              byte[] form, byte[] legacyFixture, SessionState session,
                              long generation, boolean roleSummaryEnabled,
                              boolean authDiagnostics) {
        if (endpoint == null || session == null || legacyFixture == null) {
            if (authDiagnostics) OriginalUiAuthDiagnostic.rejected(path, contentType, form,
                    "dependencies", "missing_dependency", 0);
            return failure("ONLINE_AUTH_UNAVAILABLE");
        }
        final Credentials credentials;
        try {
            credentials = parseCredentials(path, contentType, form);
        } catch (IOException invalid) {
            if (authDiagnostics) OriginalUiAuthDiagnostic.rejected(path, contentType, form,
                    "parse", parseFailureCategory(invalid), 0);
            return failure(validationErrorCode(invalid));
        }
        HttpsURLConnection upstream = null;
        OnlineAuthTokens tokens = null;
        boolean activated = false;
        String stage = "open";
        try {
            upstream = endpoint.open("/api/v1/auth/" + (credentials.register ? "register" : "login"));
            stage = "send";
            upstream.setRequestMethod("POST");
            upstream.setDoOutput(true);
            upstream.setRequestProperty("Content-Type", JSON_TYPE);
            upstream.setRequestProperty("Accept", "application/json");
            JSONObject request = new JSONObject();
            request.put("email", credentials.email);
            request.put("password", credentials.password);
            request.put("remember", true);
            byte[] requestBytes = request.toString().getBytes(StandardCharsets.UTF_8);
            if (requestBytes.length > 4096) return failure("ONLINE_INVALID_REQUEST");
            upstream.setFixedLengthStreamingMode(requestBytes.length);
            try (OutputStream output = upstream.getOutputStream()) { output.write(requestBytes); }
            stage = "status";
            int code = upstream.getResponseCode();
            if (code != (credentials.register ? 201 : 200)) {
                if (authDiagnostics) OriginalUiAuthDiagnostic.rejected(path, contentType, form,
                        "status", "upstream_status", code);
                return failure(errorCode(credentials.register, code));
            }
            byte[] answer;
            stage = "read";
            try (InputStream input = upstream.getInputStream()) {
                answer = readBounded(input, MAX_AUTH_REPLY_BYTES);
            }
            stage = "bearer";
            tokens = OnlineAuthTokens.parse(answer);
            String nonce = newNonce();
            stage = "role";
            OriginalUiRoleSummary role = roleSummaryEnabled
                    ? OriginalUiRoleSummary.fetch(endpoint, tokens.access)
                    : OriginalUiRoleSummary.uncreated();
            // Prepare the old UI reply before activating the session. Only a
            // valid fixture may ever be reported as a successful login.
            stage = "fixture";
            byte[] legacy = successLegacyJson(legacyFixture, credentials.email, nonce, role);
            stage = "session";
            session.acceptVerified(tokens, credentials.email, nonce, role, generation);
            activated = true;
            return new Reply(200, legacy);
        } catch (Exception failed) {
            // Never include URL, form, password, bearer or upstream body here.
            if (authDiagnostics) OriginalUiAuthDiagnostic.rejected(path, contentType, form,
                    stage, "exception", 0);
            return failure("ONLINE_AUTH_UNAVAILABLE");
        } finally {
            if (upstream != null) upstream.disconnect();
            if (tokens != null && !activated) OnlineAuthTokens.revoke(endpoint, tokens.refresh);
        }
    }

    private static String parseFailureCategory(IOException invalid) {
        String detail = invalid.getMessage();
        if ("Invalid legacy form metadata".equals(detail)) return "form_type";
        if ("Malformed legacy form field".equals(detail)
                || "Trailing legacy form separator".equals(detail)) return "form_shape";
        if ("Unknown or duplicate legacy form field".equals(detail)) return "fields";
        if ("Legacy form field too long".equals(detail)) return "field_length";
        if ("Only email accounts are supported".equals(detail)) return "account_type";
        if ("Missing account credentials".equals(detail)
                || "Invalid email account".equals(detail)) return "account";
        if ("Invalid password length".equals(detail)
                || "Invalid password characters".equals(detail)) return "password";
        if ("Invalid account date".equals(detail)
                || "Invalid account sign".equals(detail)) return "metadata";
        if ("Invalid form UTF-8".equals(detail)) return "utf8";
        return "other";
    }

    static String validationErrorCode(IOException invalid) {
        // Use the original client's password-length prompt instead of the
        // unknown ONLINE_* code, which the old UI reduces to a generic error.
        if ("Invalid password length".equals(invalid.getMessage())) return "CE10114";
        return "ONLINE_INVALID_REQUEST";
    }

    /** A cached login is accepted only after the matching local secret restores a Go session. */
    static Reply tokenLogin(String path, String contentType, byte[] form,
                            byte[] legacyFixture, SessionState session) {
        final String[] saved;
        try {
            saved = parseTokenLogin(path, contentType, form);
        } catch (IOException invalid) {
            return failure("ONLINE_INVALID_REQUEST");
        }
        final OriginalUiRoleSummary role;
        try {
            role = session == null ? null : session.activeRole(saved[0], saved[1]);
        } catch (OriginalUiRoleSummary.Unauthorized expired) {
            return failure("TTO0010");
        } catch (IOException unavailable) {
            return failure("ONLINE_AUTH_UNAVAILABLE");
        }
        // A cache entry for another identity must never revoke the active account.
        if (role == null) return failure("TTO0010");
        if (legacyFixture == null) return failure("ONLINE_AUTH_UNAVAILABLE");
        try {
            return new Reply(200, successLegacyJson(legacyFixture, saved[0], saved[1], role));
        } catch (IOException invalidFixture) {
            return failure("ONLINE_AUTH_UNAVAILABLE");
        }
    }

    static String[] parseTokenLogin(String path, String contentType, byte[] form) throws IOException {
        if (!"/account/user/tokenlogin".equals(path) || !validFormType(contentType)
                || form == null || form.length == 0 || form.length > MAX_FORM_BYTES)
            throw new IOException("Invalid token-login request");
        Set<String> allowed = new HashSet<String>();
        for (String key : new String[]{"useraccount", "token", "date", "sign"}) allowed.add(key);
        Map<String, String> fields = parseFields(form, allowed);
        String account = fields.get("useraccount");
        String token = fields.get("token");
        // Old offline APKs can have the prior shared placeholder in their
        // cache. Parse it, then reject it as expired through FailedDelegate.
        if (account == null || token == null || token.isEmpty() || token.length() > 512
                || hasControl(token))
            throw new IOException("Invalid token-login fields");
        String email = normalizeEmail(account);
        validateAccountMetadata(fields);
        return new String[]{email, token};
    }

    static Credentials parseCredentials(String path, String contentType, byte[] form) throws IOException {
        boolean register;
        if (LOGIN.equals(path)) register = false;
        else if (REGISTER.equals(path)) register = true;
        else throw new IOException("Unsupported legacy account path");
        if (!validFormType(contentType) || form == null || form.length == 0 || form.length > MAX_FORM_BYTES)
            throw new IOException("Invalid legacy form metadata");
        Set<String> allowed = new HashSet<String>();
        for (String key : new String[]{"useraccount", "usertype", "password", "date", "sign"})
            allowed.add(key);
        if (register) for (String key : new String[]{"cdkey", "sms", "smscode", "bundleid", "cid"})
            allowed.add(key);
        Map<String, String> fields = parseFields(form, allowed);
        if (!"2".equals(fields.get("usertype"))) throw new IOException("Only email accounts are supported");
        String account = fields.get("useraccount");
        String password = fields.get("password");
        if (account == null || password == null) throw new IOException("Missing account credentials");
        String email = normalizeEmail(account);
        int characters = password.codePointCount(0, password.length());
        if (characters < 12 || characters > 128)
            throw new IOException("Invalid password length");
        if (hasControl(password)) throw new IOException("Invalid password characters");
        validateAccountMetadata(fields);
        return new Credentials(email, password, register);
    }

    private static Map<String, String> parseFields(byte[] form, Set<String> allowed) throws IOException {
        Map<String, String> fields = new HashMap<String, String>();
        int start = 0;
        while (start < form.length) {
            int end = start;
            while (end < form.length && form[end] != '&') end++;
            int equal = start;
            while (equal < end && form[equal] != '=') equal++;
            if (equal == start || equal == end) throw new IOException("Malformed legacy form field");
            String key = decodeComponent(form, start, equal);
            String value = decodeComponent(form, equal + 1, end);
            if (!allowed.contains(key) || fields.put(key, value) != null)
                throw new IOException("Unknown or duplicate legacy form field");
            if (value.length() > 512) throw new IOException("Legacy form field too long");
            start = end + 1;
            if (end == form.length - 1) throw new IOException("Trailing legacy form separator");
        }
        return fields;
    }

    private static String normalizeEmail(String account) throws IOException {
        String email = account.trim().toLowerCase(Locale.ROOT);
        if (email.length() < 3 || email.getBytes(StandardCharsets.UTF_8).length > 254
                || email.indexOf('@') <= 0 || email.indexOf('@') == email.length() - 1
                || hasControl(email)) throw new IOException("Invalid email account");
        return email;
    }

    private static void validateAccountMetadata(Map<String, String> fields) throws IOException {
        String date = fields.get("date");
        String sign = fields.get("sign");
        if (date != null && !date.matches("[0-9]{17}")) throw new IOException("Invalid account date");
        if (sign != null && !sign.matches("[0-9a-fA-F]{32}")) throw new IOException("Invalid account sign");
    }

    private static boolean validFormType(String header) {
        if (header == null) return false;
        String[] parts = header.split(";", -1);
        if (parts.length < 1 || parts.length > 2 || !FORM_TYPE.equalsIgnoreCase(parts[0].trim()))
            return false;
        return parts.length == 1 || "charset=utf-8".equalsIgnoreCase(parts[1].trim());
    }

    private static String decodeComponent(byte[] form, int start, int end) throws IOException {
        ByteArrayOutputStream decoded = new ByteArrayOutputStream(end - start);
        for (int at = start; at < end; at++) {
            int value = form[at] & 255;
            if (value == '%') {
                if (at + 2 >= end) throw new IOException("Invalid percent encoding");
                int high = hex(form[++at] & 255);
                int low = hex(form[++at] & 255);
                if (high < 0 || low < 0) throw new IOException("Invalid percent encoding");
                decoded.write((high << 4) | low);
            } else {
                decoded.write(value == '+' ? ' ' : value);
            }
        }
        try {
            return StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(decoded.toByteArray())).toString();
        } catch (CharacterCodingException badUtf8) {
            throw new IOException("Invalid form UTF-8");
        }
    }

    private static int hex(int character) {
        if (character >= '0' && character <= '9') return character - '0';
        if (character >= 'a' && character <= 'f') return character - 'a' + 10;
        if (character >= 'A' && character <= 'F') return character - 'A' + 10;
        return -1;
    }

    private static boolean hasControl(String value) {
        for (int at = 0; at < value.length(); at++) {
            int c = value.charAt(at);
            if (Character.isISOControl(c)) return true;
        }
        return false;
    }

    static String parseBearer(byte[] answer) throws IOException {
        if (answer == null || answer.length == 0 || answer.length > MAX_AUTH_REPLY_BYTES)
            throw new IOException("Invalid online auth response size");
        try {
            String token = new JSONObject(new String(answer, StandardCharsets.UTF_8)).getString("token");
            if (!token.matches("[A-Za-z0-9_-]{43}")) throw new IOException("Invalid online session token");
            return token;
        } catch (IOException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IOException("Invalid online auth response");
        }
    }

    static String errorCode(boolean register, int httpStatus) {
        if (!register && httpStatus == 401) return "AE0010"; // account or password error
        if (register && httpStatus == 409) return "DB0040"; // user already exists
        return "ONLINE_AUTH_UNAVAILABLE";
    }

    static String newNonce() {
        byte[] random = new byte[24];
        NONCE_RANDOM.nextBytes(random);
        char[] hex = "0123456789abcdef".toCharArray();
        char[] result = new char[random.length * 2];
        for (int i = 0; i < random.length; i++) {
            result[i * 2] = hex[(random[i] >>> 4) & 15];
            result[i * 2 + 1] = hex[random[i] & 15];
        }
        return new String(result);
    }

    static byte[] successLegacyJson(byte[] fixture, String email, String nonce,
                                    OriginalUiRoleSummary role) throws IOException {
        if (nonce == null || !nonce.matches("[0-9a-f]{48}"))
            throw new IOException("Invalid local session nonce");
        if (role == null) throw new IOException("Missing authenticated role summary");
        try {
            JSONObject envelope = new JSONObject(new String(fixture, StandardCharsets.UTF_8));
            if (!"".equals(envelope.getString("Ecode"))) throw new IOException("Invalid legacy account fixture");
            JSONObject value = envelope.getJSONObject("Value");
            if (value.getInt("UID") != 1 || !FIXTURE_TOKEN.equals(value.getString("Token")))
                throw new IOException("Invalid legacy account fixture identity");
            if (!FIXTURE_TOKEN.equals(value.getString("LoginToken")))
                throw new IOException("Unexpected legacy login-token fixture");
            JSONArray zones = value.getJSONArray("ZoneInfo");
            if (zones.length() != 1) throw new IOException("Unexpected legacy zone fixture");
            JSONObject zone = zones.getJSONObject(0);
            if (!"1".equals(zone.getString("ZID"))
                    || !"http://127.0.0.1:19878".equals(zone.getString("ServerIP")))
                throw new IOException("Unexpected legacy zone endpoint");
            value.put("UserType", 2);
            value.put("Email", email);
            // This random nonce is only meaningful with the current Java
            // Application session and is never the Go bearer.
            value.put("Token", nonce);
            value.put("LoginToken", nonce);
            value.put("ExistRoles", role.legacyExistRoles());
            return envelope.toString().getBytes(StandardCharsets.UTF_8);
        } catch (IOException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IOException("Invalid legacy account fixture");
        }
    }

    private static Reply failure(String code) {
        try {
            JSONObject body = new JSONObject();
            body.put("Ecode", code);
            body.put("Value", JSONObject.NULL);
            // The original NetMsgBase dispatches nonempty Ecode through
            // OnInternalError/OnFail to the account FailedDelegate.
            return new Reply(200, body.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception impossible) {
            return new Reply(200, "{\"Ecode\":\"ONLINE_AUTH_UNAVAILABLE\"}".getBytes(StandardCharsets.US_ASCII));
        }
    }

    private static byte[] readBounded(InputStream input, int limit) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) >= 0) {
            output.write(buffer, 0, count);
            if (output.size() > limit) throw new IOException("Online auth response too large");
        }
        return output.toByteArray();
    }
}
