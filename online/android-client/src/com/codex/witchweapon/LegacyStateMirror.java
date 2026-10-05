package com.codex.witchweapon;

import android.util.AtomicFile;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Iterator;

/** Read-only local mirror for preserved Lua UI; the online save remains authoritative. */
final class LegacyStateMirror {
    private static final int MAX_BYTES = 65536;
    private static final String[] FIELDS = {
        "version", "name", "gold", "rmb", "stamina", "activityStamina",
        "inventoryRevision", "collectionRevision", "mazeRound", "mazeHP",
        "active", "activeStage", "battleMazeRound", "startKey"
    };

    private LegacyStateMirror() {}

    static void clear(File filesDir) throws IOException {
        if (filesDir == null) throw new IOException("Missing mirror directory");
        AtomicFile target = new AtomicFile(new File(filesDir, "offline_save_v1.json"));
        target.delete();
        File base = target.getBaseFile();
        if (base.exists() || new File(base.getPath() + ".bak").exists()
                || new File(base.getPath() + ".new").exists())
            throw new IOException("Unable to clear prior account mirror");
    }

    static void write(File filesDir, byte[] serverJson) throws IOException {
        if (filesDir == null || serverJson == null || serverJson.length == 0 || serverJson.length > MAX_BYTES)
            throw new IOException("Invalid state mirror size");
        final String decoded;
        try {
            decoded = StandardCharsets.UTF_8.newDecoder()
                .onMalformedInput(CodingErrorAction.REPORT)
                .onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(serverJson)).toString();
        } catch (CharacterCodingException ex) { throw new IOException("Invalid state mirror UTF-8", ex); }

        final JSONObject source;
        final JSONObject mirror = new JSONObject();
        try {
            source = new JSONObject(decoded);
            for (String field : FIELDS)
                if (source.has(field) && !source.isNull(field)) mirror.put(field, source.get(field));
            for (Iterator<String> keys = source.keys(); keys.hasNext();) {
                String key = keys.next();
                if (key.startsWith("mazeEnergy_") && key.length() < 64 && !source.isNull(key))
                    mirror.put(key, source.get(key));
            }
            if (!mirror.has("version")) mirror.put("version", 1);
        } catch (Exception ex) { throw new IOException("Invalid state mirror JSON", ex); }

        byte[] bytes = mirror.toString().getBytes(StandardCharsets.UTF_8);
        AtomicFile target = new AtomicFile(new File(filesDir, "offline_save_v1.json"));
        try {
            if (Arrays.equals(target.readFully(), bytes)) return;
        } catch (IOException ignored) { /* First mirror, or interrupted previous write. */ }
        FileOutputStream out = null;
        try {
            out = target.startWrite();
            out.write(bytes);
            target.finishWrite(out);
        } catch (IOException ex) {
            if (out != null) target.failWrite(out);
            throw ex;
        }
    }
}
