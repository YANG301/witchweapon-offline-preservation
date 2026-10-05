package com.codex.witchweapon;

import java.io.IOException;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Locale;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONObject;

/** Strict parser for the authenticated Java-save role summary (v4 candidate). */
final class OriginalUiRoleSummary {
    static final int MAX_REPLY_BYTES = 2048;
    final boolean exists;
    final String roleId;
    final String name;

    static final class Unauthorized extends IOException {
        Unauthorized() { super("Role session expired"); }
    }

    private OriginalUiRoleSummary(boolean exists, String roleId, String name) {
        this.exists = exists;
        this.roleId = roleId;
        this.name = name;
    }

    static OriginalUiRoleSummary uncreated() {
        return new OriginalUiRoleSummary(false, "", "");
    }

    static OriginalUiRoleSummary fetch(OnlineEndpoint endpoint, String bearer) throws IOException {
        if (endpoint == null || bearer == null || !bearer.matches("[A-Za-z0-9_-]{43}"))
            throw new IOException("Invalid role session");
        HttpsURLConnection upstream = endpoint.open("/api/v1/legacy-role");
        try {
            upstream.setRequestMethod("GET");
            upstream.setRequestProperty("Authorization", "Bearer " + bearer);
            upstream.setRequestProperty("Accept", "application/json");
            int status = upstream.getResponseCode();
            if (status == 401) throw new Unauthorized();
            if (status != 200 || upstream.getContentLength() > MAX_REPLY_BYTES)
                throw new IOException("Role summary unavailable");
            String type = upstream.getContentType();
            if (type == null || !type.toLowerCase(Locale.ROOT).startsWith("application/json"))
                throw new IOException("Invalid role summary type");
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            try (InputStream input = upstream.getInputStream()) {
                byte[] buffer = new byte[1024];
                int count;
                while ((count = input.read(buffer)) >= 0) {
                    output.write(buffer, 0, count);
                    if (output.size() > MAX_REPLY_BYTES)
                        throw new IOException("Role summary too large");
                }
            }
            return parse(output.toByteArray());
        } finally {
            upstream.disconnect();
        }
    }

    static OriginalUiRoleSummary parse(byte[] body) throws IOException {
        if (body == null || body.length == 0 || body.length > MAX_REPLY_BYTES)
            throw new IOException("Invalid role summary length");
        try {
            String decoded = StandardCharsets.UTF_8.newDecoder()
                    .onMalformedInput(CodingErrorAction.REPORT)
                    .onUnmappableCharacter(CodingErrorAction.REPORT)
                    .decode(ByteBuffer.wrap(body)).toString();
            JSONObject json = new JSONObject(decoded);
            if (json.length() != 4 || !json.has("version") || !json.has("exists")
                    || !json.has("roleId") || !json.has("name")
                    || !(json.get("version") instanceof Number)
                    || !"1".equals(json.get("version").toString())
                    || !(json.get("exists") instanceof Boolean)
                    || !(json.get("roleId") instanceof String)
                    || !(json.get("name") instanceof String))
                throw new IOException("Invalid role summary shape");
            boolean exists = json.getBoolean("exists");
            String roleId = json.getString("roleId");
            String name = json.getString("name");
            if (exists) {
                if (!roleId.matches("[1-9][0-9]{0,18}") || name.isEmpty()
                        || name.getBytes(StandardCharsets.UTF_8).length > 128)
                    throw new IOException("Invalid existing role");
                try { Long.parseLong(roleId); }
                catch (NumberFormatException invalid) { throw new IOException("Invalid role ID"); }
                for (int i = 0; i < name.length(); i++) {
                    int point = name.codePointAt(i);
                    if (Character.isISOControl(point) || Character.getType(point) == Character.FORMAT)
                        throw new IOException("Invalid role name");
                    if (point > 65535) i++;
                }
            } else if (!roleId.isEmpty() || !name.isEmpty()) {
                throw new IOException("Absent role has data");
            }
            return new OriginalUiRoleSummary(exists, roleId, name);
        } catch (CharacterCodingException invalid) {
            throw new IOException("Invalid role summary encoding");
        } catch (IOException invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new IOException("Invalid role summary JSON");
        }
    }

    JSONArray legacyExistRoles() throws IOException {
        JSONArray result = new JSONArray();
        if (!exists) return result;
        try {
            JSONObject entry = new JSONObject();
            entry.put("ZID", "1");
            entry.put("RID", roleId);
            entry.put("Platform", "2");
            result.put(entry);
            return result;
        } catch (Exception invalid) {
            throw new IOException("Unable to prepare existing role");
        }
    }
}
