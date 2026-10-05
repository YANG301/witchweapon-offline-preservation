package com.codex.witchweapon;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.nio.file.Files;
import java.security.MessageDigest;

public final class SignedAssetReuseTest {
    private static String sha(byte[] bytes) throws Exception {
        StringBuilder result = new StringBuilder();
        for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes))
            result.append(String.format("%02x", value & 255));
        return result.toString();
    }
    private static void require(boolean condition) {
        if (!condition) throw new AssertionError("Signed asset reuse regression");
    }
    public static void main(String[] args) throws Exception {
        File destination = new File(args[0], "signed-asset-test.bin");
        byte[] expected = {1, 2, 3, 4, 5};
        String hash = sha(expected);
        require(SignedAssetReuse.copy(new ByteArrayInputStream(expected), destination, 5, hash));
        require(java.util.Arrays.equals(expected, Files.readAllBytes(destination.toPath())));
        for (byte[] invalid : new byte[][] {{1, 2, 3, 4, 6}, {1, 2}, {1, 2, 3, 4, 5, 6}}) {
            require(!SignedAssetReuse.copy(new ByteArrayInputStream(invalid), destination, 5, hash));
            require(java.util.Arrays.equals(expected, Files.readAllBytes(destination.toPath())));
            require(!new File(destination.getPath() + ".embedded.part").exists());
        }
        require(SignedAssetReuse.copy(new ByteArrayInputStream(expected), destination, 5, hash));
        System.out.println("SIGNED_ASSET_REUSE_OK: exact, changed hash, short, oversized, repeat");
    }
}
