"""Patch the online signed updater for the separate local-mode APK.

Only the returned bytes change. The online Java source remains a read-only
input, and this module does not fetch updates, modify files, or build an APK.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


ONLINE_UPDATER = Path(
    r"D:\Project\魔女兵器在线版\android-client\src\com\codex\witchweapon\AssetUpdateManager.java"
)
ONLINE_UPDATER_SHA256 = (
    "b375b2965a71dec9aa421dd72e94330a8ec7f58f7e7abb51a50756f055b104cc"
)

_RECOVERY_ORIGINAL = "            new AssetUpdateManager(context, null).recover();\n"
_RECOVERY_LOCAL = """            AssetUpdateManager manager = new AssetUpdateManager(context, null);
            manager.recover();
            // Check the active same-version cache before Unity reads login bundles.
            if (!manager.restoreBeforeLegacyVersion())
                throw new IOException("Local login asset recovery failed");
"""

_MANIFEST_ORIGINAL = '            String path = item.getString("path");\n'
_MANIFEST_LOCAL = """            String path = item.getString("path");
            // These two bundles contain the APK's local-mode login button.
            // Reject the whole signed release; every other bundle remains eligible.
            if ("assetbundle/assets/resources/ui/prefab/login/loginmain.ab"
                    .equalsIgnoreCase(path)
                    || "assetbundle/scene/loginfromal.ab".equalsIgnoreCase(path))
                throw new IOException("Signed release contains a local login bundle");
"""


def _replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError("AssetUpdateManager source anchor count is %d, expected 1" % count)
    return source.replace(old, new, 1)


def patch(source: bytes) -> bytes:
    """Return the two-hunk local Java variant, failing closed on source drift."""
    if not isinstance(source, bytes):
        raise TypeError("Java source must be bytes")
    if source.startswith(b"\xef\xbb\xbf") or b"\r\n" in source:
        raise ValueError("Unexpected Java source encoding or line endings")
    if hashlib.sha256(source).hexdigest() != ONLINE_UPDATER_SHA256:
        raise ValueError("Online AssetUpdateManager.java changed; review anchors again")
    text = source.decode("utf-8", errors="strict")
    text = _replace_once(text, _RECOVERY_ORIGINAL, _RECOVERY_LOCAL)
    text = _replace_once(text, _MANIFEST_ORIGINAL, _MANIFEST_LOCAL)
    return text.encode("utf-8")


def check() -> dict[str, int | bool]:
    """Read-only self-check: both changes are exact and all other bytes survive."""
    source = ONLINE_UPDATER.read_bytes()
    modified = patch(source)
    reverse = modified.decode("utf-8")
    reverse = _replace_once(reverse, _RECOVERY_LOCAL, _RECOVERY_ORIGINAL)
    reverse = _replace_once(reverse, _MANIFEST_LOCAL, _MANIFEST_ORIGINAL)
    if reverse.encode("utf-8") != source:
        raise AssertionError("Local updater variant changed unrelated code")
    for original_route in (
        b"return manager.checkAndApply(progress);",
        b"JSONArray signedAssets = validateManifest(manifest);",
        b"verifySignature(manifestBytes, signatureBytes);",
    ):
        if original_route not in modified:
            raise AssertionError("Original signed-update path changed")
    return {
        "sourceBytes": len(source),
        "patchedBytes": len(modified),
        "sourceUnchanged": ONLINE_UPDATER.read_bytes() == source,
        "protectedBundles": 2,
        "changedHunks": 2,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(check(), ensure_ascii=False, sort_keys=True))
