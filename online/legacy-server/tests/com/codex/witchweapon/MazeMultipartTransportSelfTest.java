package com.codex.witchweapon;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Map;

/** Original BestHTTP switches long CSC settlement fields to multipart. */
public final class MazeMultipartTransportSelfTest {
    private static final String BOUNDARY = "BestHTTP_HTTPMultiPartForm_7F0A1B2C";
    private static final String TYPE = "multipart/form-data; boundary=\"" + BOUNDARY + "\"";

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static byte[] nativeBody(String... fields) {
        StringBuilder body = new StringBuilder();
        for (int i = 0; i < fields.length; i += 2) {
            body.append("--").append(BOUNDARY).append("\r\n")
                .append("Content-Disposition: form-data; name=\"")
                .append(fields[i]).append("\"\r\n")
                .append("Content-Type: text/plain; charset=utf-8\r\n")
                .append("Content-Length: ")
                .append(fields[i + 1].getBytes(StandardCharsets.UTF_8).length)
                .append("\r\n\r\n")
                .append(fields[i + 1]).append("\r\n");
        }
        body.append("--").append(BOUNDARY).append("--\r\n");
        return body.toString().getBytes(StandardCharsets.UTF_8);
    }

    private static void rejected(String path, String type, byte[] body) throws Exception {
        try {
            StandaloneServer.parseFormBody(path, type, body);
            throw new AssertionError("Accepted invalid multipart request");
        } catch (IOException expected) {
            // The request must fail before LocalSave sees any fields.
        }
    }

    public static void main(String[] args) throws Exception {
        StringBuilder payload = new StringBuilder();
        for (int i = 0; i < 80; i++) payload.append("战斗记录");
        payload.append("\r\n--").append(BOUNDARY).append("\r\n");
        String longData = payload.toString();
        check(longData.length() > 256, "Fixture did not trigger BestHTTP multipart mode");
        byte[] body = nativeBody(
            "enc", "1", "idempotency", "synthetic-request", "hwid", "test-device",
            "roleid", "1", "hp", "375", "data", longData, "state", "0",
            "servantcardids", "10010001", "servantids", "", "energys", "0",
            "levelid", "3130001026", "result", "0", "killed", "0", "npc", "0",
            "attackdamage", "0", "hurt", "0", "cure", "0",
            "fashioncardid", "0", "time", "123456", "sign", "synthetic-signature");
        Map<String,String> decoded = StandaloneServer.parseFormBody(
            "/csc/normal/commit", TYPE, body);
        check(decoded.size() == 20 && longData.equals(decoded.get("data")) &&
            "".equals(decoded.get("servantids")) &&
            "0".equals(decoded.get("state")) && "3130001026".equals(decoded.get("levelid")),
            "Native CSC multipart settlement was not decoded intact");

        Map<String,String> ordinary = StandaloneServer.parseFormBody(
            "/csc/normal/commit", "application/x-www-form-urlencoded; charset=utf-8",
            "state=1&data=short%2Btext".getBytes(StandardCharsets.UTF_8));
        check("short+text".equals(ordinary.get("data")),
            "Short URL-encoded CSC settlement regressed");
        rejected("/draw/gold/single", TYPE, body);
        rejected("/csc/normal/commit", "multipart/form-data; boundary=other", body);
        rejected("/csc/normal/commit", TYPE,
            Arrays.copyOf(body, body.length - BOUNDARY.length() - 6));
        rejected("/csc/normal/commit", TYPE,
            nativeBody("state", "0", "state", "1"));
        rejected("/csc/normal/commit", TYPE,
            nativeBody("data\"\r\nX-Evil: yes", "value"));
        rejected("/csc/normal/commit", TYPE,
            nativeBody("unknown", "value"));
        String oneField = new String(nativeBody("data", "A"), StandardCharsets.UTF_8);
        rejected("/csc/normal/commit", TYPE,
            oneField.replace("Content-Length: 1", "Content-Length: 2")
                .getBytes(StandardCharsets.UTF_8));
        rejected("/csc/normal/commit", TYPE,
            oneField.replace("text/plain; charset=utf-8", "application/octet-stream")
                .getBytes(StandardCharsets.UTF_8));
        rejected("/csc/normal/commit", TYPE,
            oneField.replace("name=\"data\"", "name=\"data\"; filename=\"x\"")
                .getBytes(StandardCharsets.UTF_8));
        String binary = "--" + BOUNDARY + "\r\n"
            + "Content-Disposition: form-data; name=\"data\"\r\n"
            + "Content-Type: text/plain; charset=utf-8\r\n"
            + "Content-Length: 1\r\n\r\n";
        byte[] head = binary.getBytes(StandardCharsets.US_ASCII);
        byte[] tail = ("\r\n--" + BOUNDARY + "--\r\n").getBytes(StandardCharsets.US_ASCII);
        byte[] invalidUtf8 = new byte[head.length + 1 + tail.length];
        System.arraycopy(head, 0, invalidUtf8, 0, head.length);
        invalidUtf8[head.length] = (byte)0xFF;
        System.arraycopy(tail, 0, invalidUtf8, head.length + 1, tail.length);
        rejected("/csc/normal/commit", TYPE, invalidUtf8);
        System.out.println("MAZE_MULTIPART_TRANSPORT_SELF_TEST_OK");
    }
}
