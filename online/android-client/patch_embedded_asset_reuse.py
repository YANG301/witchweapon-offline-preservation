"""Extend the reviewed dual-zone updater without changing its pinned source."""

def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Updater anchor changed: ' + before[:90])
    return text.replace(before, after, 1)


def patch(source: bytes) -> bytes:
    text = source.decode('utf-8')
    text = replace_once(text, '    private final AtomicFile stateFile;\n',
        '    private final AtomicFile stateFile;\n    private long updateDeadlineNanos;\n')
    text = replace_once(text,
        '    private Result checkAndApply(Progress progress) throws Exception {\n',
        '    private Result checkAndApply(Progress progress) throws Exception {\n'
        '        updateDeadlineNanos = System.nanoTime() + 20000000000L;\n')
    text = replace_once(text,
        '                else if (fileMatches(cached, entry)) reusable[i] = cached;\n',
        '                else if (fileMatches(cached, entry) || reuseBundledAsset(entry)) reusable[i] = cached;\n')
    text = replace_once(text,
        '                    transferred += entry.getLong("size");\n',
        '                    transferred += entry.getLong("size");\n'
        '                    JSONArray completedAsset = new JSONArray();\n'
        '                    completedAsset.put(entry);\n'
        '                    cacheSignedAssets(stagedAssets, completedAsset);\n')
    helper = '''    private boolean reuseBundledAsset(JSONObject entry) throws Exception {
        String path = entry.getString("path");
        if (!safeAssetPath(path)) throw new IOException("Invalid embedded asset path");
        try (InputStream input = context.getAssets().open(path)) {
            return SignedAssetReuse.copy(input, cacheBlob(entry),
                    entry.getLong("size"), entry.getString("sha256"));
        } catch (java.io.FileNotFoundException missing) {
            return false;
        }
    }

    private int remainingUpdateMillis() throws IOException {
        long remaining = (updateDeadlineNanos - System.nanoTime()) / 1000000L;
        if (remaining <= 0) throw new IOException("Version check time budget exceeded");
        return (int) Math.min(remaining, 10000L);
    }

'''
    text = replace_once(text, '    private byte[] request(String path, int maximum) throws IOException {\n',
        helper + '    private byte[] request(String path, int maximum) throws IOException {\n')
    text = text.replace('        HttpsURLConnection connection = endpoint.open(path);\n',
        '        int timeout = remainingUpdateMillis();\n'
        '        HttpsURLConnection connection = endpoint.open(path);\n'
        '        connection.setConnectTimeout(timeout);\n'
        '        connection.setReadTimeout(timeout);\n')
    text = replace_once(text,
        '        HttpsURLConnection connection = endpoint.open(entry.getString("url"));\n',
        '        int timeout = remainingUpdateMillis();\n'
        '        HttpsURLConnection connection = endpoint.open(entry.getString("url"));\n'
        '        connection.setConnectTimeout(timeout);\n'
        '        connection.setReadTimeout(timeout);\n')
    text = replace_once(text,
        '                while ((count = input.read(buffer)) != -1) {\n                    received += count;\n',
        '                while (true) {\n'
        '                    connection.setReadTimeout(remainingUpdateMillis());\n'
        '                    count = input.read(buffer);\n'
        '                    if (count == -1) break;\n'
        '                    received += count;\n')
    return text.encode('utf-8')
