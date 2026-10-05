package com.codex.witchweapon;

import java.nio.charset.StandardCharsets;
import org.json.JSONObject;

/** Small JVM check against the real, isolated 19876 service. */
public final class LocalModeBridgeTest {
    private static int checks;

    private static void require(boolean condition, String label) {
        checks++;
        if (!condition) throw new AssertionError(label);
    }

    private static byte[] bytes(String text) {
        return text.getBytes(StandardCharsets.UTF_8);
    }

    public static void main(String[] args) throws Exception {
        String type = "application/x-www-form-urlencoded; charset=UTF-8";
        require(LocalModeBridge.isGuestAccount("POST", "/account/user/regist", type,
                bytes("useraccount=device&usertype=3&password=random")), "guest register");
        require(!LocalModeBridge.isGuestAccount("POST", "/account/user/regist", type,
                bytes("useraccount=user%40example.com&usertype=2&password=secret")),
                "email registration stays online");
        require(!LocalModeBridge.isGuestAccount("POST", "/account/user/regist", type,
                bytes("usertype=3&usertype=2")), "conflicting account type rejected");
        require(!LocalModeBridge.isGuestAccount("POST", "/account/user/regist", "application/json",
                bytes("usertype=3")), "wrong content type rejected");
        require(LocalModeBridge.isGuestToken("POST", "/account/user/tokenlogin", type,
                bytes("useraccount=012345abcd&token=offline-local")), "guest resume token");
        require(!LocalModeBridge.isGuestToken("POST", "/account/user/tokenlogin", type,
                bytes("useraccount=online-placeholder%40example.invalid&token=offline-local")),
                "old online placeholder is not local guest");
        require(!LocalModeBridge.isGuestToken("POST", "/account/user/tokenlogin", type,
                bytes("useraccount=user%40example.com&token=online-nonce")),
                "online resume token stays online");
        if (args.length == 1 && "--integration".equals(args[0])) {
            for (String path : new String[]{"/account/user/regist", "/account/user/tokenlogin"}) {
                LocalModeBridge.Reply reply = LocalModeBridge.openGuest(path);
                JSONObject account = new JSONObject(new String(reply.body, StandardCharsets.UTF_8))
                        .getJSONObject("Value");
                require(reply.status == 200 && account.getInt("UserType") == 3,
                        "local guest account status");
                require("http://127.0.0.1:19878".equals(account.getJSONArray("ZoneInfo")
                        .getJSONObject(0).getString("ServerIP")), "game stays on mode router");
                require("本地模式".equals(account.getJSONArray("ZoneInfo")
                        .getJSONObject(0).getString("ZoneName")), "local zone name");
            }
            LocalModeBridge.Reply zone = LocalModeBridge.requestGame("POST",
                    "/account/user/getZone", type, new byte[0]);
            require(new JSONObject(new String(zone.body, StandardCharsets.UTF_8))
                    .getJSONObject("Value").getJSONArray("ZoneInfo").getJSONObject(0)
                    .getString("ServerIP").equals(LocalModeBridge.UNITY_ORIGIN),
                    "later zone requests stay on mode router");
            LocalModeBridge.Reply health = LocalModeBridge.requestGame("GET", "/health", null, null);
            require(health.status == 200, "game route reaches the independent local service");
        } else if (args.length != 0) {
            throw new IllegalArgumentException("Use --integration or no arguments");
        }
        System.out.println("LOCAL_MODE_BRIDGE_TEST_OK " + checks);
    }
}
