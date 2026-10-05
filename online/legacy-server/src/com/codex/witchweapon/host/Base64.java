package com.codex.witchweapon.host;

/** Only the two flag combinations used by the unmodified author logic. */
public final class Base64 {
    public static final int DEFAULT = 0;
    public static final int NO_WRAP = 2;
    private Base64() {}
    public static byte[] decode(String value, int flags) {
        if (flags != DEFAULT) throw new IllegalArgumentException("Unsupported Base64 flags");
        // Android DEFAULT accepts line wrapping. Do not silently discard other characters.
        return java.util.Base64.getDecoder().decode(value.replaceAll("[\\t\\n\\r ]", ""));
    }
    public static String encodeToString(byte[] value, int flags) {
        if (flags != NO_WRAP) throw new IllegalArgumentException("Unsupported Base64 flags");
        return java.util.Base64.getEncoder().encodeToString(value);
    }
}
