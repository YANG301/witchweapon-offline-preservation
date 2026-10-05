"""Build an in-memory local-mode variant of the online Android application.

The source under ``魔女兵器在线版`` is read only.  The returned Java source is
compiled together with this directory's LocalModeBridge.java by the APK build
driver; this module does not write or build an APK.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ONLINE_APPLICATION = Path(
    r"D:\Project\魔女兵器在线版\android-client\src\com\codex\witchweapon\OfflineApplication.java"
)
LOCAL_BRIDGE = Path(__file__).with_name("LocalModeBridge.java")
ONLINE_APPLICATION_SHA256 = (
    "9459b86cbd636f00bb2738160f622c4a400597e656843e22f473d218d30efc5b"
)


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError("OfflineApplication source anchor count is %d, expected 1" % count)
    return source.replace(old, new, 1)


def patch(source: bytes) -> bytes:
    """Return the modified OfflineApplication.java bytes without changing input files."""
    if not isinstance(source, bytes):
        raise TypeError("Java source must be bytes")
    if source.startswith(b"\xef\xbb\xbf") or b"\r\n" in source:
        raise ValueError("Unexpected Java source encoding or line endings")
    if hashlib.sha256(source).hexdigest() != ONLINE_APPLICATION_SHA256:
        raise ValueError("Online OfflineApplication.java changed; review anchors again")
    text = source.decode("utf-8", errors="strict")

    text = _replace_once(
        text,
        "    private boolean originalUiAuth;\n",
        "    private boolean originalUiAuth;\n"
        "    // Set only after the PC service confirms its single-user identity.\n"
        "    private volatile boolean localMode;\n",
    )

    text = _replace_once(
        text,
        "    /** Complete the first authenticated mirror before exposing the Unity UI. */\n",
        """    /**
     * Drop only this process's online credentials before entering local mode.
     * The existing online logout path still revokes its remote refresh token;
     * selecting the guest button must not contact the online service.
     */
    private void clearOnlineStateForLocalMode() throws IOException {
        synchronized (refreshLock) {
            synchronized (sessionLock) {
                authGeneration++;
                sessionBearer = null;
                sessionEmail = null;
                sessionNonce = null;
                sessionRole = null;
                IOException problem = null;
                try { if (sessionStore != null) sessionStore.clear(); }
                catch (IOException failed) { problem = failed; }
                try { clearReadyMarker(); }
                catch (IOException failed) { if (problem == null) problem = failed; }
                try { LegacyStateMirror.clear(getFilesDir()); }
                catch (IOException failed) { if (problem == null) problem = failed; }
                if (problem != null) throw problem;
            }
        }
    }

    /** Complete the first authenticated mirror before exposing the Unity UI. */
""",
    )

    text = _replace_once(
        text,
        "        AssetUpdateManager.LegacyRelease originalUpdate = legacyRelease;\n",
        """        // The original VisitorBtn submits RegistUser with usertype=3.  Its
        // account and all subsequent game traffic stay on the PC local service.
        if (originalUiAuth && query < 0 && LocalModeBridge.isGuestAccount(
                method, path, contentType, body)) {
            try {
                LocalModeBridge.Reply guest = LocalModeBridge.openGuest(path);
                clearOnlineStateForLocalMode();
                localMode = true;
                return new Reply(guest.status, guest.contentType, guest.body);
            } catch (IOException unavailable) {
                return localAccountUnavailable();
            }
        }
        // The original guest cache repeats its fixed token after process death.
        if (originalUiAuth && query < 0 && LocalModeBridge.isGuestToken(
                method, path, contentType, body)) {
            try {
                LocalModeBridge.Reply guest = LocalModeBridge.openGuest(path);
                clearOnlineStateForLocalMode();
                localMode = true;
                return new Reply(guest.status, guest.contentType, guest.body);
            } catch (IOException unavailable) {
                return localAccountUnavailable();
            }
        }
        if (originalUiAuth && localMode) {
            if (query < 0 && "POST".equals(method)
                    && path.equals("/account/user/logout")) {
                localMode = false;
                return new Reply(200, "application/json; charset=utf-8",
                        bytes("{\\"Ecode\\":\\"\\",\\"Value\\":{}}"));
            }
            // A manual email login or registration returns to the unchanged
            // online adapter.  Guest forms were handled above.
            if (query < 0 && "POST".equals(method)
                    && (path.equals("/account/user/login")
                        || path.equals("/account/user/regist"))) {
                localMode = false;
            } else {
                if (query >= 0 && (account || !bootstrap))
                    return new Reply(400, "text/plain; charset=utf-8",
                            bytes("Query unsupported"));
                // Keep the APK's version and env fixtures: they match its
                // bundled assets and point Unity back to this 19878 bridge.
                if (bootstrap || accountProbe) return localReply(path, bootstrap, false);
                try {
                    LocalModeBridge.Reply local = LocalModeBridge.requestGame(
                            method, path, contentType, body);
                    return new Reply(local.status, local.contentType, local.body);
                } catch (IOException unavailable) {
                    return localServiceUnavailable();
                }
            }
        }
        AssetUpdateManager.LegacyRelease originalUpdate = legacyRelease;
""",
    )

    text = _replace_once(
        text,
        "    private static boolean isVersionRoute(String path) {\n",
        """    private static Reply localAccountUnavailable() {
        // Legacy NetMsgBase expects HTTP 200 plus a nonempty Ecode to run its
        // failure delegate.  Never report a successful guest identity here.
        return new Reply(200, "application/json; charset=utf-8",
                bytes("{\\"Ecode\\":\\"LOCAL_SERVICE_UNAVAILABLE\\",\\"Value\\":null}"));
    }

    private static Reply localServiceUnavailable() {
        // Game endpoints can carry protobuf.  A JSON error with HTTP 200
        // would be interpreted as a successful protobuf response.
        return new Reply(503, "text/plain; charset=utf-8",
                bytes("Local service unavailable"));
    }

    private static boolean isVersionRoute(String path) {
""",
    )

    result = text.encode("utf-8")
    if result == source:
        raise AssertionError("Local-mode patch made no change")
    return result


def check() -> dict[str, int | bool]:
    """Validate exact anchors and the companion bridge without writing files."""
    source = ONLINE_APPLICATION.read_bytes()
    bridge = LOCAL_BRIDGE.read_bytes()
    if b"class LocalModeBridge" not in bridge:
        raise ValueError("LocalModeBridge.java is missing or unexpected")
    modified = patch(source)
    if b"revokeAsync(oldRefresh)" not in modified:
        raise AssertionError("Online logout implementation changed")
    if modified.count(b"LocalModeBridge.openGuest(path)") != 2:
        raise AssertionError("Guest entry and cache recovery are incomplete")
    return {
        "sourceBytes": len(source),
        "patchedBytes": len(modified),
        "sourceUnchanged": ONLINE_APPLICATION.read_bytes() == source,
        "guestEntryPoints": 2,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
