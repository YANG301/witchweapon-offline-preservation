package com.codex.witchweapon;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;

/** Import a bundled asset only when it matches an already verified manifest. */
final class SignedAssetReuse {
    static boolean copy(InputStream input, File destination, long size, String sha)
            throws Exception {
        if (size < 0 || !sha.matches("[0-9a-f]{64}"))
            throw new IOException("Invalid signed embedded asset");
        File temporary = new File(destination.getParentFile(), destination.getName() + ".embedded.part");
        if (!temporary.getCanonicalPath().equals(temporary.getAbsolutePath()))
            throw new IOException("Linked embedded cache entry is unsupported");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        long received = 0;
        try {
            try (FileOutputStream output = new FileOutputStream(temporary)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    received += count;
                    if (received > size) return false;
                    digest.update(buffer, 0, count);
                    output.write(buffer, 0, count);
                }
                StringBuilder hex = new StringBuilder(64);
                for (byte value : digest.digest())
                    hex.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
                if (received != size || !sha.equals(hex.toString())) return false;
                output.flush();
                output.getFD().sync();
            }
            if (destination.exists() && !destination.delete())
                throw new IOException("Cannot replace embedded cache entry");
            if (!temporary.renameTo(destination))
                throw new IOException("Cannot commit embedded cache entry");
            return true;
        } finally {
            if (temporary.exists() && !temporary.delete())
                throw new IOException("Cannot clear incomplete embedded cache entry");
        }
    }
}
