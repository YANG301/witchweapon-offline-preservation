package com.codex.witchweapon;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONArray;
import org.json.JSONObject;

public final class OriginalUiRoleSummaryTest {
    private static void require(boolean okay, String reason) {
        if (!okay) throw new AssertionError(reason);
    }
    private static byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }
    private static void invalid(byte[] body) throws Exception {
        try {
            OriginalUiRoleSummary.parse(body);
            throw new AssertionError("Accepted invalid role summary");
        } catch (IOException expected) { }
    }
    public static void main(String[] ignored) throws Exception {
        OriginalUiRoleSummary created=OriginalUiRoleSummary.parse(bytes(
                "{\"version\":1,\"exists\":true,\"roleId\":\"87123456789\",\"name\":\"原版玩家\"}"));
        require(created.exists && "原版玩家".equals(created.name),"Created role parse failed");
        JSONArray roles=created.legacyExistRoles();
        JSONObject item=roles.getJSONObject(0);
        require(roles.length()==1 && "87123456789".equals(item.getString("RID"))
                && "1".equals(item.getString("ZID")) && "2".equals(item.getString("Platform")),
                "Legacy existing-role shape changed");
        OriginalUiRoleSummary fresh=OriginalUiRoleSummary.parse(bytes(
                "{\"version\":1,\"exists\":false,\"roleId\":\"\",\"name\":\"\"}"));
        require(!fresh.exists && fresh.legacyExistRoles().length()==0,"Uncreated role was exposed");
        invalid(bytes("{\"version\":1,\"exists\":false,\"roleId\":\"1\",\"name\":\"\"}"));
        invalid(bytes("{\"version\":1,\"exists\":true,\"roleId\":\"9223372036854775808\",\"name\":\"Bad\"}"));
        invalid(bytes("{\"version\":1,\"exists\":true,\"roleId\":\"1\",\"name\":\"Bad\",\"accountId\":\"leak\"}"));
        invalid(new byte[]{'{',(byte)0xff,'}'});
        System.out.println("ORIGINAL_UI_ROLE_SUMMARY_PASS");
    }
}
