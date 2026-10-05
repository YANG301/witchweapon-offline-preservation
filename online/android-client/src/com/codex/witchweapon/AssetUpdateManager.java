package com.codex.witchweapon;

import android.content.Context;
import android.os.Build;
import android.os.StatFs;
import android.util.AtomicFile;
import android.util.Base64;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.util.Arrays;
import java.util.HashSet;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import javax.net.ssl.HttpsURLConnection;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Signed, bounded AssetBundle updates applied before the Unity activity starts. */
final class AssetUpdateManager {
    static final int BOOTSTRAP_VERSION = 1;
    private static final long MAX_ASSET = 128L * 1024 * 1024;
    private static final long MAX_TOTAL = 512L * 1024 * 1024;
    private static final int MAX_ASSETS = 256;
    private static final String MANIFEST = "/updates/stable/manifest.json";
    private static final String SIGNATURE = "/updates/stable/manifest.sig";
    private static final String BLOB_PREFIX = "/updates/stable/blobs/";
    private static final String STATE_FILE = "signed-asset-update-state.json";
    private static final String CACHE_DIRECTORY = "signed-asset-update-blobs";
    private static final String[] UNITY_METADATA = {
            "m.version", "m.assets_list.txt", "m.loaded.cache", "m.content.cache"
    };
    private static final long MAX_UNITY_METADATA = 8L * 1024 * 1024;
    private static final String ACTIVE = "assetbundle";
    private static final String STAGE = ".witch-update-stage";
    private static final String BACKUP = ".witch-update-backup";
    private static final String TRASH = ".witch-update-trash";
    private static final String INCOMPATIBLE = ".witch-update-previous-apk";
    private static final String CORRUPT = ".witch-update-corrupt";
    private static final String LOG_TAG = "WitchAssetUpdate";
    private static final Object RESOURCE_LOCK = new Object();

    interface Progress {
        void report(String message);
        void transfer(long received, long total);
    }

    static final class Result {
        final boolean safeToLaunch;
        final boolean updated;
        final String detail;
        Result(boolean safeToLaunch, boolean updated, String detail) {
            this.safeToLaunch = safeToLaunch;
            this.updated = updated;
            this.detail = detail;
        }
    }

    /** A signed release translated into the original Unity update protocol. */
    static final class LegacyRelease {
        final String version;
        final byte[] index;
        final Map<String, File> blobsByMd5;
        LegacyRelease(String version, byte[] index, Map<String, File> blobsByMd5) {
            this.version = version;
            this.index = index;
            this.blobsByMd5 = blobsByMd5;
        }
        File blob(String md5) { return blobsByMd5.get(md5); }
    }

    static LegacyRelease legacyRelease(Context context) {
        synchronized (RESOURCE_LOCK) {
            try {
                AssetUpdateManager manager = new AssetUpdateManager(context, null);
                JSONObject state = manager.readState();
                JSONObject release = state.optBoolean("pending", false)
                        ? state.optJSONObject("candidate") : state;
                if (release == null || release.optLong("releaseSequence", 0) < 1)
                    return null;
                JSONArray signed = manager.verifiedReleaseAssets(release);
                if (!manager.cachedAssetsMatch(signed))
                    throw new IOException("Signed resource cache is incomplete");
                long sequence = release.getLong("releaseSequence");
                String embedded = manager.embeddedVersion();
                int separator = embedded.lastIndexOf('.');
                if (separator < 1 || sequence > 1000000)
                    throw new IOException("Unsupported legacy resource version");
                long revision = Long.parseLong(embedded.substring(separator + 1)) + sequence;
                if (revision > Integer.MAX_VALUE)
                    throw new IOException("Legacy resource version exceeds range");
                String version = embedded.substring(0, separator + 1) + revision;
                Map<String, String> replacement = new HashMap<>();
                Map<String, File> byMd5 = new HashMap<>();
                for (int i = 0; i < signed.length(); i++) {
                    JSONObject item = signed.getJSONObject(i);
                    File file = manager.cacheBlob(item);
                    MessageDigest md5 = MessageDigest.getInstance("MD5");
                    try (InputStream input = new FileInputStream(file)) {
                        byte[] chunk = new byte[65536];
                        int count;
                        while ((count = input.read(chunk)) != -1)
                            md5.update(chunk, 0, count);
                    }
                    String digest = hex(md5.digest());
                    String resource = "/" + item.getString("path").substring(ACTIVE.length() + 1);
                    replacement.put(resource, digest + "=" + resource + ":" + item.getLong("size"));
                    if (byMd5.put(digest, file) != null)
                        throw new IOException("Duplicate original resource MD5");
                }
                byte[] bundled;
                try (InputStream input = context.getAssets().open("m.assets_list.txt")) {
                    bundled = readBounded(input, (int) MAX_UNITY_METADATA);
                }
                String[] lines = new String(bundled, StandardCharsets.UTF_8).split("\\r?\\n");
                StringBuilder index = new StringBuilder(bundled.length + signed.length() * 96);
                for (String line : lines) {
                    if (line.isEmpty()) continue;
                    int equal = line.indexOf('=');
                    int colon = line.lastIndexOf(':');
                    if (equal != 32 || colon <= equal)
                        throw new IOException("Bundled resource index has an invalid line");
                    String resource = line.substring(equal + 1, colon);
                    String changed = replacement.remove(resource);
                    index.append(changed == null ? line : changed).append('\n');
                }
                for (String added : replacement.values()) index.append(added).append('\n');
                return new LegacyRelease(version,
                        index.toString().getBytes(StandardCharsets.UTF_8), byMd5);
            } catch (Exception invalid) {
                Log.w(LOG_TAG, "Original Unity update bridge unavailable: "
                        + invalid.getClass().getSimpleName() + ": " + invalid.getMessage());
                return null;
            }
        }
    }

    private final Context context;
    private final OnlineEndpoint endpoint;
    private final File root;
    private final File cacheRoot;
    private final AtomicFile stateFile;

    private AssetUpdateManager(Context context, OnlineEndpoint endpoint) throws IOException {
        this.context = context.getApplicationContext();
        this.endpoint = endpoint;
        root = context.getExternalFilesDir(null);
        if (root == null || !root.isDirectory()) throw new IOException("App resource directory unavailable");
        assertManagedChildren();
        cacheRoot = new File(context.getNoBackupFilesDir(), CACHE_DIRECTORY);
        if (!cacheRoot.isDirectory() && !cacheRoot.mkdirs())
            throw new IOException("Cannot create private signed asset cache");
        stateFile = new AtomicFile(new File(context.getNoBackupFilesDir(), STATE_FILE));
    }

    static Result run(Context context, Progress progress) {
        Result recovery = recoverBeforeUnity(context);
        if (!recovery.safeToLaunch) return recovery;
        try {
            OnlineEndpoint endpoint = OnlineEndpoint.fromAssets(context, "update_endpoint.txt");
            AssetUpdateManager manager = new AssetUpdateManager(context, endpoint);
            return manager.checkAndApply(progress);
        } catch (Exception unavailable) {
            Log.w(LOG_TAG, "Update unavailable: " + unavailable.getClass().getSimpleName()
                    + ": " + unavailable.getMessage());
            // A failed update must never prevent the bundled game from opening.
            return new Result(true, false, "资源更新暂不可用，继续使用已有资源");
        }
    }

    /** Repair an interrupted local update before Unity opens its first bundle. */
    static Result recoverBeforeUnity(Context context) {
        try {
            // Crash recovery must run even if the update origin is offline or
            // its APK configuration is invalid.
            new AssetUpdateManager(context, null).recover();
        } catch (Exception damaged) {
            Log.w(LOG_TAG, "Recovery failed: " + damaged.getClass().getSimpleName()
                    + ": " + damaged.getMessage());
            return new Result(false, false, "本地资源状态异常，请点击重试");
        }
        return new Result(true, false, "本地资源已就绪");
    }

    /** The original Unity updater rebuilds its resource directory before Lua starts. */
    static boolean restoreBeforeLegacyVersion(Context context) {
        synchronized (RESOURCE_LOCK) {
            try {
                return new AssetUpdateManager(context, null).restoreBeforeLegacyVersion();
            } catch (Exception failed) {
                Log.w(LOG_TAG, "Legacy version bridge failed: "
                        + failed.getClass().getSimpleName() + ": " + failed.getMessage());
                return false;
            }
        }
    }

    static void confirmAfterUnityStarted(Context context) {
        synchronized (RESOURCE_LOCK) {
        try {
            AssetUpdateManager manager = new AssetUpdateManager(context, null);
            JSONObject state = manager.readState();
            if (!state.optBoolean("pending", false)) {
                if (manager.embeddedVersion().equals(state.optString("embeddedVersion", ""))) {
                    manager.deleteManaged(new File(manager.root, INCOMPATIBLE));
                    manager.deleteManaged(new File(manager.root, CORRUPT));
                }
                return;
            }
            JSONObject candidate = state.optJSONObject("candidate");
            JSONArray signedAssets = manager.verifiedReleaseAssets(candidate);
            if (!manager.cachedAssetsMatch(signedAssets) || !manager.matchesAssets(
                    new File(manager.root, ACTIVE), signedAssets)
                    || !manager.exactTreeMatches(
                    new File(manager.root, ACTIVE), signedAssets)) {
                Log.w(LOG_TAG, "Signed release remains unconfirmed: active assets absent");
                return;
            }
            JSONObject committed = new JSONObject(candidate.toString());
            committed.put("highWater", state.optLong("highWater", 0));
            committed.put("pending", false);
            manager.writeState(committed);
            manager.deleteManaged(new File(manager.root, BACKUP));
            manager.deleteManaged(new File(manager.root, INCOMPATIBLE));
            manager.deleteManaged(new File(manager.root, CORRUPT));
            manager.pruneCacheBestEffort(committed);
            Log.i(LOG_TAG, "Confirmed signed release: sequence="
                    + committed.optLong("releaseSequence", 0));
        } catch (Exception ignored) {
            // Keep the pending journal; the next launch will restore the old set.
        }
        }
    }

    private Result checkAndApply(Progress progress) throws Exception {
        JSONObject state = readState();
        byte[] manifestBytes = null;
        byte[] signatureBytes = null;
        Exception signatureFailure = null;
        // The publisher atomically changes its release pointer. The two GETs
        // can straddle that switch; retry the pair once if they do not match.
        for (int attempt = 0; attempt < 2; attempt++) {
            byte[] proposed = request(MANIFEST, 128 * 1024);
            byte[] encodedSignature = request(SIGNATURE, 8 * 1024);
            try {
                verifySignature(proposed, encodedSignature);
                manifestBytes = proposed;
                signatureBytes = encodedSignature;
                break;
            } catch (Exception invalid) {
                signatureFailure = invalid;
            }
        }
        if (manifestBytes == null) throw signatureFailure;
        JSONObject manifest = new JSONObject(new String(manifestBytes, StandardCharsets.UTF_8));
        JSONArray assets = validateManifest(manifest);
        long sequence = manifest.getLong("releaseSequence");
        long highWater = state.optLong("highWater", 0);
        long activeSequence = state.optLong("releaseSequence", 0);
        if (sequence < highWater || (sequence == activeSequence
                && matchesAssets(new File(root, ACTIVE), state.optJSONArray("assets"))))
            return new Result(true, false, "游戏资源已是最新");
        if (sequence == highWater && sequence != activeSequence)
            return new Result(true, false, "该资源版本已回退，等待新版发布");

        File active = new File(root, ACTIVE);
        File stage = new File(root, STAGE);
        File backup = new File(root, BACKUP);
        deleteManaged(stage);
        if (!stage.mkdir()) throw new IOException("Cannot create update stage");
        File stagedAssets = new File(stage, ACTIVE);
        if (!stagedAssets.mkdir()) throw new IOException("Cannot create bundle stage");
        try {
            copyUnityMetadata(active, stagedAssets);
            // Stage exactly the files authorized by this signed release.
            // Anything omitted falls back to the APK's bundled resources.
            // This also makes a higher-sequence rollback remove old overlays.
            long required = 16L * 1024 * 1024;
            for (int i = 0; i < assets.length(); i++) required += assets.getJSONObject(i).getLong("size");
            if (Build.VERSION.SDK_INT >= 18 && new StatFs(root.getAbsolutePath()).getAvailableBytes() < required)
                throw new IOException("Insufficient storage for signed update");
            // Count only uncached blobs, so the bar reflects bytes that must
            // actually cross the network rather than the whole signed release.
            File[] reusable = new File[assets.length()];
            long transferTotal = 0;
            for (int i = 0; i < assets.length(); i++) {
                JSONObject entry = assets.getJSONObject(i);
                File oldFile = assetFile(active, entry.getString("path"));
                File cached = cacheBlob(entry);
                if (fileMatches(oldFile, entry)) reusable[i] = oldFile;
                else if (fileMatches(cached, entry)) reusable[i] = cached;
                else transferTotal += entry.getLong("size");
            }
            long transferred = 0;
            for (int i = 0; i < assets.length(); i++) {
                JSONObject entry = assets.getJSONObject(i);
                File destination = assetFile(stagedAssets, entry.getString("path"));
                if (reusable[i] != null) {
                    File parent = destination.getParentFile();
                    if (!parent.isDirectory() && !parent.mkdirs())
                        throw new IOException("Cannot create staged asset directory");
                    copyFile(reusable[i], destination);
                } else {
                    progress.report("正在下载资源 " + (i + 1) + "/" + assets.length());
                    download(entry, destination, progress, transferred, transferTotal);
                    transferred += entry.getLong("size");
                }
            }
            progress.report("正在校验游戏资源…");
            if (!matchesAssets(stagedAssets, assets)) throw new IOException("Staged assets differ from manifest");
            cacheSignedAssets(stagedAssets, assets);
            JSONObject candidate = new JSONObject();
            candidate.put("releaseSequence", sequence);
            candidate.put("assets", assets);
            candidate.put("embeddedVersion", embeddedVersion());
            candidate.put("signedManifest", Base64.encodeToString(manifestBytes, Base64.NO_WRAP));
            candidate.put("signedSignature", Base64.encodeToString(signatureBytes, Base64.NO_WRAP));
            JSONObject journal = new JSONObject();
            journal.put("pending", true);
            journal.put("highWater", sequence);
            journal.put("previous", state);
            journal.put("candidate", candidate);
            journal.put("hadPrevious", active.exists());
            if (active.exists()) journal.put("previousTreeSha256", directoryFingerprint(active));
            writeState(journal);
            if (backup.exists()) throw new IOException("Unresolved previous backup");
            if (active.exists() && !active.renameTo(backup))
                throw new IOException("Cannot preserve previous bundles");
            if (!stagedAssets.renameTo(active)) {
                if (backup.exists() && !backup.renameTo(active))
                    throw new IOException("Cannot restore previous bundles");
                writeState(state);
                throw new IOException("Cannot activate staged bundles");
            }
            deleteManaged(stage);
            Log.i(LOG_TAG, "Activated signed release: sequence=" + sequence
                    + ", assets=" + assets.length());
            return new Result(true, true, "资源更新已完成，正在启动游戏");
        } catch (Exception failure) {
            deleteManaged(stage);
            throw failure;
        }
    }

    private boolean restoreBeforeLegacyVersion() throws Exception {
        JSONObject state = readState();
        JSONObject release = state.optBoolean("pending", false)
                ? state.optJSONObject("candidate") : state;
        if (release == null || release.optLong("releaseSequence", 0) == 0) return true;
        try {
            JSONArray assets = verifiedReleaseAssets(release);
            if (!cachedAssetsMatch(assets))
                throw new IOException("Private signed asset cache is incomplete");
            File active = new File(root, ACTIVE);
            boolean replaced = !matchesAssets(active, assets) || !exactTreeMatches(active, assets);
            if (replaced)
                activateFromCache(assets);
            if (!matchesAssets(active, assets) || !exactTreeMatches(active, assets))
                throw new IOException("Legacy version bridge did not restore signed assets");
            Log.i(LOG_TAG, "Legacy version bridge ready: sequence="
                    + release.getLong("releaseSequence") + ", assets=" + assets.length()
                    + ", restored=" + replaced);
            return true;
        } catch (Exception invalid) {
            Log.w(LOG_TAG, "Signed overlay cannot be restored before legacy version: "
                    + invalid.getClass().getSimpleName() + ": " + invalid.getMessage());
            return restorePreviousOrBundled(state);
        }
    }

    private void activateFromCache(JSONArray assets) throws Exception {
        File active = new File(root, ACTIVE);
        File stage = new File(root, STAGE);
        File trash = new File(root, TRASH);
        deleteManaged(stage);
        if (!stage.mkdir()) throw new IOException("Cannot create legacy bridge stage");
        File stagedAssets = new File(stage, ACTIVE);
        if (!stagedAssets.mkdir()) throw new IOException("Cannot create legacy bridge bundle stage");
        try {
            copyUnityMetadata(active.isDirectory() ? active : new File(root, BACKUP), stagedAssets);
            for (int i = 0; i < assets.length(); i++) {
                JSONObject item = assets.getJSONObject(i);
                File destination = assetFile(stagedAssets, item.getString("path"));
                File parent = destination.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs())
                    throw new IOException("Cannot create legacy bridge asset directory");
                copyFile(cacheBlob(item), destination);
            }
            if (!matchesAssets(stagedAssets, assets) || !exactTreeMatches(stagedAssets, assets))
                throw new IOException("Legacy bridge stage differs from signed cache");
            deleteManaged(trash);
            if (active.exists() && !active.renameTo(trash))
                throw new IOException("Cannot quarantine Unity resource directory");
            if (!stagedAssets.renameTo(active)) {
                if (trash.exists() && !trash.renameTo(active))
                    throw new IOException("Cannot restore Unity resource directory");
                throw new IOException("Cannot activate signed assets before Lua startup");
            }
            deleteManaged(trash);
        } finally {
            deleteManaged(stage);
        }
    }

    private boolean restorePreviousOrBundled(JSONObject state) throws Exception {
        long highWater = state.optLong("highWater", 0);
        JSONObject previous = state.optBoolean("pending", false)
                ? state.optJSONObject("previous") : null;
        if (previous != null && previous.optLong("releaseSequence", 0) > 0) {
            try {
                JSONArray previousAssets = verifiedReleaseAssets(previous);
                if (!cachedAssetsMatch(previousAssets))
                    throw new IOException("Previous signed assets are no longer cached");
                activateFromCache(previousAssets);
                JSONObject restored = new JSONObject(previous.toString());
                restored.put("highWater", highWater);
                restored.put("pending", false);
                writeState(restored);
                deleteManaged(new File(root, BACKUP));
                pruneCacheBestEffort(restored);
                Log.w(LOG_TAG, "Legacy version bridge rolled back to sequence="
                        + restored.getLong("releaseSequence"));
                return true;
            } catch (Exception previousInvalid) {
                Log.w(LOG_TAG, "Previous signed release unavailable: "
                        + previousInvalid.getClass().getSimpleName());
            }
        }
        // Keep Unity's own version/index/cache files while dropping every
        // unverified external AssetBundle and returning to APK resources.
        activateFromCache(new JSONArray());
        deleteManaged(new File(root, BACKUP));
        deleteManaged(new File(root, STAGE));
        deleteManaged(new File(root, TRASH));
        JSONObject reset = emptyState();
        reset.put("embeddedVersion", embeddedVersion());
        reset.put("highWater", highWater);
        writeState(reset);
        pruneCacheBestEffort(reset);
        Log.w(LOG_TAG, "Legacy version bridge returned to APK resources");
        return true;
    }

    private void pruneCache(JSONObject state) throws IOException {
        HashSet<String> keep = new HashSet<>();
        JSONArray assets = state.optJSONArray("assets");
        if (assets != null) {
            for (int i = 0; i < assets.length(); i++) {
                JSONObject item = assets.optJSONObject(i);
                if (item != null) {
                    String sha = item.optString("sha256", "");
                    if (sha.matches("[0-9a-f]{64}")) keep.add(sha);
                }
            }
        }
        File[] children = cacheRoot.listFiles();
        if (children == null) throw new IOException("Cannot inspect private signed asset cache");
        for (File child : children) {
            String name = child.getName();
            if (!name.matches("[0-9a-f]{64}(\\.part)?") || keep.contains(name)) continue;
            if (!child.isFile() || !child.getCanonicalPath().equals(
                    new File(cacheRoot.getCanonicalFile(), name).getPath()) || !child.delete())
                throw new IOException("Cannot retire unused signed cache entry");
        }
    }

    private void pruneCacheBestEffort(JSONObject state) {
        try { pruneCache(state); }
        catch (IOException failed) {
            Log.w(LOG_TAG, "Unused signed cache cleanup deferred: "
                    + failed.getClass().getSimpleName());
        }
    }

    private void recover() throws IOException, JSONException {
        JSONObject state = readState();
        File active = new File(root, ACTIVE);
        File backup = new File(root, BACKUP);
        File trash = new File(root, TRASH);
        deleteManaged(new File(root, STAGE));
        if (trash.exists()) {
            // A process may have died between the two directory renames used
            // by the legacy-version bridge. Restore the previous tree first.
            if (!active.exists()) {
                if (!trash.renameTo(active))
                    throw new IOException("Cannot recover interrupted legacy bridge");
            } else deleteManaged(trash);
        }
        if (!state.optBoolean("pending", false)) {
            deleteManaged(backup);
            String bundled = embeddedVersion();
            String recorded = state.optString("embeddedVersion", "");
            if (recorded.isEmpty()) {
                if (active.exists() && !exactTreeMatches(active, new JSONArray()))
                    isolateActive(active, new File(root, INCOMPATIBLE));
                state.put("embeddedVersion", bundled);
                writeState(state);
            } else if (!bundled.equals(recorded)) {
                // A newly installed APK may bundle a different Lua/config
                // baseline. Never load the previous APK's external overlay.
                isolateActive(active, new File(root, INCOMPATIBLE));
                JSONObject reset = emptyState();
                reset.put("embeddedVersion", bundled);
                reset.put("highWater", state.optLong("highWater", 0));
                writeState(reset);
                state = reset;
            } else if (state.optLong("releaseSequence", 0) > 0
                    && (!matchesAssets(active, state.optJSONArray("assets"))
                        || !exactTreeMatches(active, state.optJSONArray("assets")))) {
                boolean restored = false;
                try {
                    JSONArray signedAssets = verifiedReleaseAssets(state);
                    if (cachedAssetsMatch(signedAssets)) {
                        activateFromCache(signedAssets);
                        restored = matchesAssets(active, signedAssets)
                                && exactTreeMatches(active, signedAssets);
                    }
                } catch (Exception invalid) {
                    Log.w(LOG_TAG, "Signed cache recovery unavailable: "
                            + invalid.getClass().getSimpleName());
                }
                if (!restored) {
                    try { activateFromCache(new JSONArray()); }
                    catch (Exception cannotKeepMetadata) {
                        isolateActive(active, new File(root, CORRUPT));
                    }
                    JSONObject reset = emptyState();
                    reset.put("embeddedVersion", bundled);
                    reset.put("highWater", state.optLong("highWater", 0));
                    writeState(reset);
                    state = reset;
                } else Log.i(LOG_TAG, "Recovered signed assets from private cache");
            } else if (state.optLong("releaseSequence", 0) == 0 && active.exists()
                    && !exactTreeMatches(active, new JSONArray())) {
                // No signed release owns these files. Do not let arbitrary
                // pre-existing external Lua override the bundled game, but
                // preserve the original updater's four metadata files.
                try { activateFromCache(new JSONArray()); }
                catch (Exception cannotKeepMetadata) {
                    isolateActive(active, new File(root, CORRUPT));
                }
            }
            pruneCacheBestEffort(state);
            return;
        }
        JSONObject previous = state.optJSONObject("previous");
        if (previous == null) throw new IOException("Invalid update journal");
        if (backup.exists()) {
            deleteManaged(trash);
            if (active.exists() && !active.renameTo(trash))
                throw new IOException("Cannot quarantine unconfirmed bundles");
            if (!backup.renameTo(active)) {
                if (trash.exists()) trash.renameTo(active);
                throw new IOException("Cannot restore previous bundles");
            }
            deleteManaged(trash);
        } else if (!state.optBoolean("hadPrevious", false)) {
            deleteManaged(active);
        } else if (!active.isDirectory() || !directoryFingerprint(active).equals(
                state.optString("previousTreeSha256", ""))) {
            // A missing backup with the candidate still active is ambiguous.
            // Never declare the old release restored without checking bytes.
            throw new IOException("Unrecoverable asset transaction journal");
        }
        JSONObject restored = new JSONObject(previous.toString());
        restored.put("highWater", Math.max(state.optLong("highWater", 0),
                previous.optLong("highWater", 0)));
        restored.put("pending", false);
        writeState(restored);
        recover();
    }

    private void isolateActive(File active, File quarantine) throws IOException {
        if (!active.exists()) return;
        // Quarantine is a bounded, managed previous-attempt directory. An old
        // quarantined release must not make every later recovery fail.
        deleteManaged(quarantine);
        if (!active.renameTo(quarantine))
            throw new IOException("Cannot isolate unverified bundles");
    }

    private boolean exactTreeMatches(File active, JSONArray assets) {
        if (assets == null || !active.isDirectory()) return false;
        try {
            HashSet<String> expected = new HashSet<>();
            for (int i = 0; i < assets.length(); i++) {
                String path = assets.getJSONObject(i).getString("path");
                if (!safeAssetPath(path) || !expected.add(path)) return false;
            }
            HashSet<String> actual = new HashSet<>();
            collectAssetPaths(active, active, actual);
            return expected.equals(actual);
        } catch (Exception invalid) { return false; }
    }

    private static void collectAssetPaths(File base, File directory, HashSet<String> paths)
            throws IOException {
        File[] children = directory.listFiles();
        if (children == null) throw new IOException("Cannot inspect active bundles");
        for (File child : children) {
            if (!child.getCanonicalPath().equals(
                    new File(directory.getCanonicalFile(), child.getName()).getPath()))
                throw new IOException("Linked active asset is unsupported");
            if (child.isDirectory()) collectAssetPaths(base, child, paths);
            else if (child.isFile()) {
                String relative = child.getAbsolutePath().substring(base.getAbsolutePath().length() + 1)
                        .replace(File.separatorChar, '/');
                if (isUnityMetadata(relative)) continue;
                if (!relative.endsWith(".ab"))
                    throw new IOException("Unexpected non-bundle in Unity resource directory");
                if (!paths.add("assetbundle/" + relative) || paths.size() > MAX_ASSETS)
                    throw new IOException("Unexpected active asset count");
            } else throw new IOException("Unsupported active asset entry");
        }
    }

    private static boolean isUnityMetadata(String relative) {
        for (String name : UNITY_METADATA) if (name.equals(relative)) return true;
        return false;
    }

    private static void copyUnityMetadata(File source, File destination) throws IOException {
        if (!source.isDirectory()) return;
        for (String name : UNITY_METADATA) {
            File input = new File(source, name);
            if (!input.exists()) continue;
            if (!input.isFile() || input.length() > MAX_UNITY_METADATA
                    || !input.getCanonicalPath().equals(
                    new File(source.getCanonicalFile(), name).getPath()))
                throw new IOException("Invalid Unity resource metadata");
            copyFile(input, new File(destination, name));
        }
    }

    private JSONArray validateManifest(JSONObject manifest) throws Exception {
        if (manifest.getInt("schema") != 1
                || !context.getPackageName().equals(manifest.getString("packageId"))
                || !embeddedVersion().equals(manifest.getString("targetAppVersion"))
                || manifest.getInt("minBootstrapVersion") > BOOTSTRAP_VERSION
                || manifest.getInt("minBootstrapVersion") < 1
                || manifest.getLong("releaseSequence") < 1)
            throw new IOException("Signed manifest is incompatible with this APK");
        JSONArray assets = manifest.getJSONArray("assets");
        if (assets.length() > MAX_ASSETS) throw new IOException("Too many update assets");
        HashSet<String> paths = new HashSet<>();
        long total = 0;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject item = assets.getJSONObject(i);
            String path = item.getString("path");
            String sha = item.getString("sha256");
            String url = item.getString("url");
            long size = item.getLong("size");
            if (!safeAssetPath(path) || !paths.add(path.toLowerCase(Locale.ROOT))
                    || !sha.matches("[0-9a-f]{64}")
                    || !url.equals(BLOB_PREFIX + sha) || size < 1 || size > MAX_ASSET)
                throw new IOException("Invalid signed asset entry");
            total += size;
            if (total > MAX_TOTAL) throw new IOException("Signed update exceeds download limit");
        }
        return assets;
    }

    private String embeddedVersion() throws IOException {
        try (InputStream input = context.getAssets().open("m.version")) {
            String version = new String(readBounded(input, 64), StandardCharsets.US_ASCII).trim();
            if (!version.matches("[0-9.]{1,32}")) throw new IOException("Invalid embedded version");
            return version;
        }
    }

    private void verifySignature(byte[] manifest, byte[] encoded) throws Exception {
        byte[] keyData;
        try (InputStream input = context.getAssets().open("update_public_key.der")) {
            keyData = readBounded(input, 1024);
        }
        PublicKey key = KeyFactory.getInstance("RSA").generatePublic(new X509EncodedKeySpec(keyData));
        if (!(key instanceof RSAPublicKey)
                || ((RSAPublicKey) key).getModulus().bitLength() < 2048)
            throw new IOException("Update signing key is too short");
        byte[] signature = Base64.decode(new String(encoded, StandardCharsets.US_ASCII).trim(), Base64.DEFAULT);
        Signature verifier = Signature.getInstance("SHA256withRSA");
        verifier.initVerify(key);
        verifier.update(manifest);
        if (!verifier.verify(signature)) throw new IOException("Update manifest signature mismatch");
    }

    private byte[] request(String path, int maximum) throws IOException {
        HttpsURLConnection connection = endpoint.open(path);
        try {
            connection.setRequestMethod("GET");
            if (connection.getResponseCode() != 200) throw new IOException("Update endpoint unavailable");
            try (InputStream input = connection.getInputStream()) { return readBounded(input, maximum); }
        } finally { connection.disconnect(); }
    }

    private void download(JSONObject entry, File destination, Progress progress,
                          long completed, long total) throws Exception {
        File parent = destination.getParentFile();
        if (!parent.isDirectory() && !parent.mkdirs()) throw new IOException("Cannot create asset directory");
        HttpsURLConnection connection = endpoint.open(entry.getString("url"));
        try {
            connection.setRequestMethod("GET");
            if (connection.getResponseCode() != 200) throw new IOException("Asset download failed");
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            long expectedSize = entry.getLong("size");
            long received = 0;
            try (InputStream input = connection.getInputStream();
                 FileOutputStream output = new FileOutputStream(destination)) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    received += count;
                    if (received > expectedSize) throw new IOException("Asset is larger than signed size");
                    digest.update(buffer, 0, count);
                    output.write(buffer, 0, count);
                    progress.transfer(completed + received, total);
                }
                output.flush();
                output.getFD().sync();
            }
            if (received != expectedSize || !hex(digest.digest()).equals(entry.getString("sha256")))
                throw new IOException("Asset hash or size mismatch");
        } finally { connection.disconnect(); }
    }

    private File cacheBlob(JSONObject entry) throws IOException, JSONException {
        String sha = entry.getString("sha256");
        if (!sha.matches("[0-9a-f]{64}")) throw new IOException("Invalid cached asset digest");
        File blob = new File(cacheRoot, sha);
        if (blob.exists() && !blob.getCanonicalPath().equals(
                new File(cacheRoot.getCanonicalFile(), sha).getPath()))
            throw new IOException("Linked signed asset cache is unsupported");
        return blob;
    }

    private void cacheSignedAssets(File stagedAssets, JSONArray assets) throws Exception {
        long needed = 16L * 1024 * 1024;
        for (int i = 0; i < assets.length(); i++) {
            JSONObject item = assets.getJSONObject(i);
            if (!fileMatches(cacheBlob(item), item)) needed += item.getLong("size");
        }
        if (Build.VERSION.SDK_INT >= 18
                && new StatFs(cacheRoot.getAbsolutePath()).getAvailableBytes() < needed)
            throw new IOException("Insufficient private storage for signed assets");
        for (int i = 0; i < assets.length(); i++) {
            JSONObject item = assets.getJSONObject(i);
            File blob = cacheBlob(item);
            if (fileMatches(blob, item)) continue;
            File temporary = new File(cacheRoot, item.getString("sha256") + ".part");
            if (temporary.exists() && !temporary.delete())
                throw new IOException("Cannot reset incomplete signed cache entry");
            try {
                copyFile(assetFile(stagedAssets, item.getString("path")), temporary);
                if (!fileMatches(temporary, item))
                    throw new IOException("Private signed asset cache differs from manifest");
                if (blob.exists() && !blob.delete())
                    throw new IOException("Cannot replace invalid signed cache entry");
                if (!temporary.renameTo(blob))
                    throw new IOException("Cannot commit private signed cache entry");
            } finally {
                if (temporary.exists()) temporary.delete();
            }
        }
    }

    private boolean cachedAssetsMatch(JSONArray assets) {
        if (assets == null) return false;
        try {
            for (int i = 0; i < assets.length(); i++) {
                JSONObject item = assets.getJSONObject(i);
                if (!fileMatches(cacheBlob(item), item)) return false;
            }
            return true;
        } catch (Exception invalid) { return false; }
    }

    private JSONArray verifiedReleaseAssets(JSONObject release) throws Exception {
        if (release == null || release.optLong("releaseSequence", 0) < 1
                || !embeddedVersion().equals(release.optString("embeddedVersion", "")))
            throw new IOException("Signed cache release does not target this APK");
        String manifestText = release.optString("signedManifest", "");
        String signatureText = release.optString("signedSignature", "");
        if (manifestText.isEmpty() || signatureText.isEmpty()
                || manifestText.length() > 180000 || signatureText.length() > 12000)
            throw new IOException("Signed cache has no bounded manifest proof");
        byte[] manifestBytes = Base64.decode(manifestText, Base64.DEFAULT);
        byte[] signatureBytes = Base64.decode(signatureText, Base64.DEFAULT);
        if (manifestBytes.length > 128 * 1024 || signatureBytes.length > 8 * 1024)
            throw new IOException("Signed cache manifest proof exceeds limits");
        verifySignature(manifestBytes, signatureBytes);
        JSONObject manifest = new JSONObject(new String(manifestBytes, StandardCharsets.UTF_8));
        JSONArray signedAssets = validateManifest(manifest);
        JSONArray recordedAssets = release.optJSONArray("assets");
        if (manifest.getLong("releaseSequence") != release.getLong("releaseSequence")
                || !sameAssets(signedAssets, recordedAssets))
            throw new IOException("Signed cache state differs from manifest");
        return signedAssets;
    }

    private static boolean sameAssets(JSONArray signed, JSONArray recorded) throws JSONException {
        if (signed == null || recorded == null || signed.length() != recorded.length()) return false;
        for (int i = 0; i < signed.length(); i++) {
            JSONObject a = signed.getJSONObject(i);
            JSONObject b = recorded.getJSONObject(i);
            if (!a.getString("path").equals(b.getString("path"))
                    || !a.getString("url").equals(b.getString("url"))
                    || !a.getString("sha256").equals(b.getString("sha256"))
                    || a.getLong("size") != b.getLong("size")) return false;
        }
        return true;
    }

    private boolean matchesAssets(File base, JSONArray assets) {
        if (assets == null) return false;
        try {
            for (int i = 0; i < assets.length(); i++) {
                JSONObject item = assets.getJSONObject(i);
                if (!safeAssetPath(item.getString("path"))
                        || !fileMatches(assetFile(base, item.getString("path")), item)) return false;
            }
            return true;
        } catch (Exception invalid) { return false; }
    }

    private boolean fileMatches(File file, JSONObject item) throws Exception {
        if (!file.isFile() || file.length() != item.getLong("size")) return false;
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return hex(digest.digest()).equals(item.getString("sha256"));
    }

    private static File assetFile(File base, String path) throws IOException {
        if (!safeAssetPath(path)) throw new IOException("Invalid asset path");
        // Manifest paths include assetbundle/, while base already points there.
        File target = new File(base, path.substring("assetbundle/".length()));
        String canonicalBase = base.getCanonicalPath();
        if (!target.getCanonicalPath().startsWith(canonicalBase + File.separator))
            throw new IOException("Asset path escapes app directory");
        return target;
    }

    private static boolean safeAssetPath(String path) {
        if (path == null || path.length() > 240 || !path.startsWith("assetbundle/")
                || !path.endsWith(".ab")) return false;
        for (int i = 0; i < path.length(); i++) {
            char c = path.charAt(i);
            if (c < 32 || c > 126 || "\\:<>?*|\"".indexOf(c) >= 0) return false;
        }
        String[] parts = path.split("/", -1);
        for (String part : parts) {
            if (part.isEmpty() || ".".equals(part) || "..".equals(part)) return false;
        }
        return true;
    }

    private JSONObject readState() throws IOException {
        if (!stateFile.getBaseFile().exists()) return emptyState();
        try {
            return new JSONObject(new String(stateFile.readFully(), StandardCharsets.UTF_8));
        } catch (Exception invalid) {
            throw new IOException("Invalid update state", invalid);
        }
    }

    private static JSONObject emptyState() {
        JSONObject state = new JSONObject();
        try {
            state.put("releaseSequence", 0);
            state.put("highWater", 0);
            state.put("pending", false);
            state.put("assets", new JSONArray());
        } catch (JSONException impossible) { throw new IllegalStateException(impossible); }
        return state;
    }

    private void writeState(JSONObject state) throws IOException {
        FileOutputStream output = stateFile.startWrite();
        try {
            output.write(state.toString().getBytes(StandardCharsets.UTF_8));
            stateFile.finishWrite(output);
        } catch (IOException failure) {
            stateFile.failWrite(output);
            throw failure;
        }
    }

    private static final class CopyBudget {
        int files;
        long bytes;
    }

    private static String directoryFingerprint(File base) throws IOException {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            CopyBudget budget = new CopyBudget();
            fingerprintTree(base, base, digest, budget);
            return hex(digest.digest());
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IOException("SHA-256 unavailable", impossible);
        }
    }

    private static void fingerprintTree(File base, File directory, MessageDigest digest,
                                        CopyBudget budget) throws IOException {
        File[] children = directory.listFiles();
        if (children == null) throw new IOException("Cannot inspect existing bundles");
        Arrays.sort(children, (left, right) -> left.getName().compareTo(right.getName()));
        for (File child : children) {
            if (!child.getCanonicalPath().equals(
                    new File(directory.getCanonicalFile(), child.getName()).getPath()))
                throw new IOException("Linked existing asset is unsupported");
            String relative = child.getAbsolutePath().substring(base.getAbsolutePath().length() + 1)
                    .replace(File.separatorChar, '/');
            digest.update(relative.getBytes(StandardCharsets.UTF_8));
            digest.update((byte) 0);
            if (child.isDirectory()) {
                digest.update((byte) 'D');
                fingerprintTree(base, child, digest, budget);
            } else if (child.isFile()) {
                digest.update((byte) 'F');
                budget.files++;
                budget.bytes += child.length();
                if (budget.files > 20000 || budget.bytes > MAX_TOTAL)
                    throw new IOException("Existing asset tree exceeds update limit");
                try (InputStream input = new FileInputStream(child)) {
                    byte[] bytes = new byte[65536];
                    int count;
                    while ((count = input.read(bytes)) != -1) digest.update(bytes, 0, count);
                }
            } else throw new IOException("Unsupported existing asset entry");
        }
    }

    private static void copyFile(File source, File destination) throws IOException {
        try (InputStream input = new FileInputStream(source);
             FileOutputStream output = new FileOutputStream(destination)) {
            byte[] bytes = new byte[65536];
            int count;
            while ((count = input.read(bytes)) != -1) output.write(bytes, 0, count);
            output.flush();
            output.getFD().sync();
        }
    }

    private void deleteManaged(File directory) throws IOException {
        if (!directory.exists()) return;
        String rootPath = root.getCanonicalPath();
        String target = directory.getCanonicalPath();
        if (!target.startsWith(rootPath + File.separator)
                || !directory.getParentFile().getCanonicalPath().equals(rootPath))
            throw new IOException("Unsafe update cleanup target");
        deleteTree(directory);
    }

    private void assertManagedChildren() throws IOException {
        String canonicalRoot = root.getCanonicalPath();
        for (String name : new String[] {ACTIVE, STAGE, BACKUP, TRASH, INCOMPATIBLE, CORRUPT}) {
            File child = new File(root, name);
            if (child.exists() && !child.getCanonicalPath().equals(
                    new File(canonicalRoot, name).getPath()))
                throw new IOException("Linked resource directory is unsupported");
        }
    }

    private static void deleteTree(File file) throws IOException {
        if (file.isDirectory()) {
            File[] children = file.listFiles();
            if (children == null) throw new IOException("Cannot inspect update directory");
            for (File child : children) {
                if (!child.getCanonicalPath().equals(
                        new File(file.getCanonicalFile(), child.getName()).getPath()))
                    throw new IOException("Linked update entry is unsupported");
                deleteTree(child);
            }
        }
        if (!file.delete()) throw new IOException("Cannot remove old update entry");
    }

    private static byte[] readBounded(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (output.size() > maximum - count) throw new IOException("Update response exceeds limit");
            output.write(buffer, 0, count);
        }
        return output.toByteArray();
    }

    private static String hex(byte[] bytes) {
        char[] digits = "0123456789abcdef".toCharArray();
        char[] result = new char[bytes.length * 2];
        for (int i = 0; i < bytes.length; i++) {
            result[i * 2] = digits[(bytes[i] >>> 4) & 15];
            result[i * 2 + 1] = digits[bytes[i] & 15];
        }
        return new String(result).toLowerCase(Locale.ROOT);
    }
}
