package com.codex.witchweapon;

import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

/** A single account's refresh credential, encrypted with an app-local Android Keystore key. */
final class OnlineSessionStore {
    private static final byte[] MAGIC = {'W', 'W', 'R', '1'};
    private static final int IV_LENGTH = 12;
    private static final int MAX_FILE = 8192;
    private static final String ALIAS = "witchweapon-online-refresh-v1";
    private final AtomicFile file;
    private final byte[] associatedData;

    static final class Entry {
        final String email;
        final String nonce;
        final String refresh;
        final long expiresAt;
        Entry(String email, String nonce, String refresh, long expiresAt) {
            this.email = email;
            this.nonce = nonce;
            this.refresh = refresh;
            this.expiresAt = expiresAt;
        }
        boolean expired() { return expiresAt <= System.currentTimeMillis(); }
    }

    static final class Corrupt extends IOException {
        Corrupt() { super("Saved login cannot be decrypted"); }
    }

    OnlineSessionStore(Context context) {
        file = new AtomicFile(new File(context.getNoBackupFilesDir(), "online_refresh_v1.bin"));
        associatedData = (context.getPackageName() + ":online-refresh-v1")
                .getBytes(StandardCharsets.UTF_8);
    }

    synchronized Entry read() throws IOException {
        if (!file.getBaseFile().exists()
                && !new File(file.getBaseFile().getPath() + ".bak").exists()) return null;
        if (Build.VERSION.SDK_INT < 23) throw new Corrupt();
        final byte[] encrypted;
        try (InputStream input = file.openRead()) {
            ByteArrayOutputStream output = new ByteArrayOutputStream();
            byte[] buffer = new byte[1024];
            int count;
            while ((count = input.read(buffer)) >= 0) {
                output.write(buffer, 0, count);
                if (output.size() > MAX_FILE) throw new Corrupt();
            }
            encrypted = output.toByteArray();
        } catch (FileNotFoundException gone) {
            return null;
        }
        if (encrypted.length < MAGIC.length + IV_LENGTH + 16) throw new Corrupt();
        for (int i = 0; i < MAGIC.length; i++) if (encrypted[i] != MAGIC[i]) throw new Corrupt();
        byte[] iv = new byte[IV_LENGTH];
        System.arraycopy(encrypted, MAGIC.length, iv, 0, IV_LENGTH);
        try {
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            cipher.updateAAD(associatedData);
            byte[] plaintext = cipher.doFinal(encrypted, MAGIC.length + IV_LENGTH,
                    encrypted.length - MAGIC.length - IV_LENGTH);
            JSONObject json = new JSONObject(new String(plaintext, StandardCharsets.UTF_8));
            if (json.getInt("version") != 1) throw new Corrupt();
            String email = json.getString("email");
            String nonce = json.getString("nonce");
            String refresh = json.getString("refreshToken");
            long expiry = json.getLong("refreshExpiresAtMillis");
            if (email.isEmpty() || email.length() > 254 || email.indexOf('@') <= 0
                    || !nonce.matches("[0-9a-f]{48}")
                    || !refresh.matches("[A-Za-z0-9_-]{43}") || expiry <= 0)
                throw new Corrupt();
            return new Entry(email, nonce, refresh, expiry);
        } catch (Corrupt invalid) {
            throw invalid;
        } catch (Exception invalid) {
            throw new Corrupt();
        }
    }

    synchronized void write(Entry entry) throws IOException {
        if (Build.VERSION.SDK_INT < 23) throw new IOException("Android 6.0 is required for saved login");
        if (entry == null || entry.email == null || entry.email.isEmpty()
                || entry.nonce == null || !entry.nonce.matches("[0-9a-f]{48}")
                || entry.refresh == null || !entry.refresh.matches("[A-Za-z0-9_-]{43}")
                || entry.expiresAt <= System.currentTimeMillis())
            throw new IOException("Invalid saved login");
        try {
            JSONObject json = new JSONObject();
            json.put("version", 1);
            json.put("email", entry.email);
            json.put("nonce", entry.nonce);
            json.put("refreshToken", entry.refresh);
            json.put("refreshExpiresAtMillis", entry.expiresAt);
            byte[] plain = json.toString().getBytes(StandardCharsets.UTF_8);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            byte[] iv = cipher.getIV();
            if (iv == null || iv.length != IV_LENGTH)
                throw new IOException("Unsupported Keystore IV length");
            cipher.updateAAD(associatedData);
            byte[] sealed = cipher.doFinal(plain);
            byte[] data = new byte[MAGIC.length + IV_LENGTH + sealed.length];
            System.arraycopy(MAGIC, 0, data, 0, MAGIC.length);
            System.arraycopy(iv, 0, data, MAGIC.length, IV_LENGTH);
            System.arraycopy(sealed, 0, data, MAGIC.length + IV_LENGTH, sealed.length);
            if (data.length > MAX_FILE) throw new IOException("Saved login too large");
            FileOutputStream output = null;
            try {
                output = file.startWrite();
                output.write(data);
                file.finishWrite(output);
            } catch (IOException failed) {
                if (output != null) file.failWrite(output);
                throw failed;
            }
        } catch (IOException failed) {
            throw failed;
        } catch (Exception failed) {
            throw new IOException("Cannot save encrypted login", failed);
        }
    }

    synchronized void clear() throws IOException {
        file.delete();
        File base = file.getBaseFile();
        boolean fileGone = !base.exists() && !new File(base.getPath() + ".bak").exists()
                && !new File(base.getPath() + ".new").exists();
        boolean keyGone = false;
        if (Build.VERSION.SDK_INT >= 23) {
            try {
                KeyStore store = KeyStore.getInstance("AndroidKeyStore");
                store.load(null);
                if (store.containsAlias(ALIAS)) store.deleteEntry(ALIAS);
                keyGone = true;
            } catch (Exception failed) {
                if (!fileGone) throw new IOException("Cannot invalidate saved login");
            }
        }
        // Either deleting the ciphertext or deleting its non-exportable key
        // makes an old refresh credential impossible to restore.
        if (!fileGone && !keyGone) throw new IOException("Cannot invalidate saved login");
    }

    private SecretKey key() throws GeneralSecurityException, IOException {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        java.security.Key existing = store.getKey(ALIAS, null);
        if (existing != null) {
            if (!(existing instanceof SecretKey)) throw new GeneralSecurityException("Invalid key type");
            return (SecretKey) existing;
        }
        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        generator.init(new KeyGenParameterSpec.Builder(ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setKeySize(256).build());
        return generator.generateKey();
    }
}
