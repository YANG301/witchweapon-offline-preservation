package com.codex.witchweapon;

import com.codex.witchweapon.host.Base64;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;

/** Checks both original-protocol story routes expose the restored final chapters. */
public final class StardustStoryFixtureSelfTest {
    private static final long GROUP_ID = 6030004L;
    private static final long FIRST_STORY_ID = 61300041001L;

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static byte[] stardustGroup(byte[] payload) throws Exception {
        ProtoWire story = ProtoWire.parse(payload);
        int matches = 0;
        byte[] groupBytes = null;
        for (ProtoWire.Field field : story.fields) {
            if (field.number != 1 || field.type != 2) continue;
            ProtoWire entry = ProtoWire.parse(field.data);
            if (entry.number(1, 0) != GROUP_ID) continue;
            groupBytes = entry.data(2);
            matches++;
        }
        require(matches == 1 && groupBytes != null, "Stardust group must appear once");
        return groupBytes;
    }

    private static void verify(JSONObject responses, String path, int expectedVersion)
            throws Exception {
        byte[] payload = Base64.decode(
            responses.getJSONObject(path).getString("base64"), Base64.DEFAULT);
        ProtoWire story = ProtoWire.parse(payload);
        require(story.number(100, -1) == expectedVersion, path + " version changed");
        ProtoWire group = ProtoWire.parse(stardustGroup(payload));
        require(group.number(100, 0) == 1, path + " Stardust group is locked");

        int count = 0;
        for (ProtoWire.Field field : group.fields) {
            if (field.number != 1 || field.type != 2) continue;
            ProtoWire node = ProtoWire.parse(field.data);
            require(node.number(100, 0) == FIRST_STORY_ID + count,
                path + " Stardust chapter order changed at " + (count + 1));
            if (count >= 18) {
                require(node.number(101, 0) == 1 && node.number(102, 0) == 1,
                    path + " final Stardust chapter is unavailable");
            }
            count++;
        }
        require(count == 21, path + " must contain exactly 21 Stardust chapters");

        // Starter-account special handling may alter the tutorial group only.
        JSONObject starter = new JSONObject().put("starterProfile", 1);
        byte[] starterResponse = LocalStarterStory.get(starter, payload);
        require(Arrays.equals(stardustGroup(payload), stardustGroup(starterResponse)),
            path + " starter handling changed the Stardust group");
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Arguments: responses.json");
        JSONObject responses = new JSONObject(new String(Files.readAllBytes(
            new File(args[0]).toPath()), StandardCharsets.UTF_8));
        verify(responses, "/story/get", 5);
        verify(responses, "/game/story/get", 1);
        System.out.println("STARDUST_STORY_FIXTURE_OK");
    }
}
