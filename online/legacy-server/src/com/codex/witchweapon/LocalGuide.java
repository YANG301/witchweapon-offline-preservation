package com.codex.witchweapon;

import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import org.json.JSONObject;

/** Per-account state for the original LessonTriggerStateGetAll/Update pair. */
final class LocalGuide {
    private static final int MAX_POINTS = 128;
    private static final long FORMER_OPENING_STAGE = 3150001004L;
    private static final long BASESTATION_OPENING_STAGE = 3150001001L;

    private LocalGuide() { }

    static boolean restoreFormerOpening(JSONObject save) throws Exception {
        // The first online test client used the later 1004 opening. After the
        // client selects the preserved 1001 route, an account that already won
        // 1004 must continue at the pre-naming scene instead of replaying a
        // different first battle. Never skip either scene for a fresh account.
        if (save.optInt("starterProfile",0) != 1 ||
                !save.optBoolean("roleCreated",false) ||
                !save.optBoolean("namePending",true) ||
                save.optInt("tutorialWins_"+FORMER_OPENING_STAGE,0) <= 0 ||
                save.optInt("tutorialWins_"+BASESTATION_OPENING_STAGE,0) > 0)
            return false;
        JSONObject points = points(save);
        boolean changed = false;
        for (int id = 1; id <= 2; id++) {
            String key = Integer.toString(id);
            if (rank(-2) > rank(points.optInt(key,-1))) {
                points.put(key,-2);
                changed = true;
            }
        }
        return changed;
    }

    static boolean restoreNamedStarter(JSONObject save) throws Exception {
        if (save.optInt("starterProfile",0) != 1 ||
                !save.optBoolean("roleCreated",false) ||
                save.optBoolean("namePending",true)) return false;
        JSONObject points = points(save);
        boolean changed = false;
        // Earlier builds acknowledged /role/rename without returning its
        // completed achievement. Naming proves that the first four guide
        // records have already been played, so resume after that scene.
        for (int id = 1; id <= 4; id++) {
            String key = Integer.toString(id);
            if (points.optInt(key,-1) != -2) { points.put(key,-2); changed = true; }
        }
        return changed;
    }

    static byte[] get(JSONObject save) throws Exception {
        JSONObject points = save.optJSONObject("guidePoints");
        if (points == null) return new byte[0];
        ArrayList<Integer> ids = new ArrayList<Integer>();
        for (java.util.Iterator<String> it = points.keys(); it.hasNext(); ) {
            String key = it.next();
            if (!key.matches("[1-9][0-9]{0,4}"))
                throw new IOException("Invalid stored guide ID");
            ids.add(Integer.parseInt(key));
        }
        Collections.sort(ids);
        ProtoWire result = new ProtoWire();
        for (int id : ids)
            result.add(1,new ProtoWire().set(1,id)
                .set(2,points.getInt(Integer.toString(id))).bytes());
        return result.bytes();
    }

    static byte[] update(JSONObject save,Map<String,String> args) throws Exception {
        String rawIds = args.get("pointtype"),rawStates = args.get("pointval");
        if (rawIds == null || rawStates == null ||
                rawIds.length() > 1024 || rawStates.length() > 1024)
            throw new IOException("Invalid guide update");
        if (rawIds.isEmpty() || rawStates.isEmpty()) {
            if (!rawIds.isEmpty() || !rawStates.isEmpty())
                throw new IOException("Mismatched guide update");
            return new ProtoWire().text(1,"ok").bytes();
        }
        String[] ids = rawIds.split("\\|",-1),states = rawStates.split("\\|",-1);
        if (ids.length != states.length || ids.length > MAX_POINTS)
            throw new IOException("Mismatched guide update");
        Set<Integer> seen = new HashSet<Integer>();
        int[] parsedIds = new int[ids.length],parsedStates = new int[states.length];
        for (int i = 0; i < ids.length; i++) {
            if (!ids[i].matches("[1-9][0-9]{0,4}") ||
                    !states[i].matches("-?[0-9]{1,5}"))
                throw new IOException("Invalid guide point");
            int id = Integer.parseInt(ids[i]),value = Integer.parseInt(states[i]);
            if (id > 99999 || value < -2 || value > 10000 || !seen.add(id))
                throw new IOException("Invalid guide point");
            parsedIds[i] = id;
            parsedStates[i] = value;
        }
        JSONObject points = points(save);
        for (int i = 0; i < parsedIds.length; i++) {
            String key = Integer.toString(parsedIds[i]);
            int old = points.optInt(key,-1);
            if (rank(parsedStates[i]) > rank(old)) points.put(key,parsedStates[i]);
        }
        return new ProtoWire().text(1,"ok").bytes();
    }

    private static JSONObject points(JSONObject save) throws Exception {
        JSONObject points = save.optJSONObject("guidePoints");
        if (points == null) {
            points = new JSONObject();
            save.put("guidePoints",points);
        }
        return points;
    }

    private static int rank(int state) {
        // RecOverState=-2 is terminal; numeric ordering alone would overwrite
        // it with an earlier active/progress state on a replayed request.
        return state == -2 ? Integer.MAX_VALUE : state + 1;
    }
}
