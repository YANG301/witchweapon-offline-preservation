"""Fix the settlement NGUI panel queue after the particle-only release 47."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import UnityPy

import build_settlement_levelup_hotupdate as previous


PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / "热更新测试" / "主线热更候选"
APK = previous.APK
KEY = previous.KEY
LOGICAL = previous.LOGICAL_PATH
OLD = "47-e5c86cc2256821a0b18501dfab3fc466256149750b5d7da25ea6d3e1b408eb47"
OLD_BLOB = "8bbcda50270c63b288093b94a769c749f603828267b2529aa98009d9648aca69"
PANEL_PATH_ID = 6761771918859879738
OVERRIDE = PROJECT / "android-client" / "resources-overrides" / "settlement-levelup-panel.ab"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_bundle(original: bytes) -> bytes:
    if sha(original) != OLD_BLOB:
        raise ValueError("Release 47 settlement blob changed")
    bundle = UnityPy.load(original)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    matches = [obj for obj in bundle.objects if obj.path_id == PANEL_PATH_ID]
    if len(before) != 833 or len(matches) != 1 or matches[0].type.name != "MonoBehaviour":
        raise ValueError("Reviewed WatchmenContainer panel was not found")
    panel = matches[0]
    tree = panel.read_typetree()
    # RenderQueue.Automatic=0 ignores startingRenderQueue. StartAt=1 makes
    # the card draw at 3015+, behind which the glow now sits at queue 3014.
    if (tree.get("renderQueue") != 0 or tree.get("startingRenderQueue") != 3015
            or tree.get("mDepth") != 100 or tree.get("mClipping") != 3):
        raise ValueError("WatchmenContainer no longer has the reviewed NGUI settings")
    tree["renderQueue"] = 1
    panel.save_typetree(tree)
    result = bundle.file.save(packer="original")
    reopened = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in reopened.objects}
    if (set(before) != set(after)
            or {pid for pid in before if before[pid] != after[pid]} != {PANEL_PATH_ID}):
        raise ValueError("Panel patch changed unrelated Unity objects")
    patched = next(obj for obj in reopened.objects if obj.path_id == PANEL_PATH_ID)
    if patched.read_typetree().get("renderQueue") != 1:
        raise ValueError("Panel render queue failed round-trip")
    materials = {obj.path_id: obj.read_typetree() for obj in reopened.objects
                 if obj.path_id in previous.TARGETS}
    if set(materials) != set(previous.TARGETS) or any(
            tree.get("m_CustomRenderQueue") != previous.NEW_QUEUE
            for tree in materials.values()):
        raise ValueError("Particle materials lost the previous queue repair")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=int, default=49)
    args = parser.parse_args()
    if args.sequence != 49:
        raise ValueError("This reviewed follow-up release uses sequence 49")
    source = ROOT / "releases" / OLD
    base_raw = (source / "manifest.json").read_bytes()
    if sha(base_raw) != OLD.split("-", 1)[1]:
        raise ValueError("Signed release 47 manifest changed")
    base = json.loads(base_raw)
    old_asset = next((a for a in base["assets"] if a["path"] == LOGICAL), None)
    if base["releaseSequence"] != 47 or old_asset is None or old_asset["sha256"] != OLD_BLOB:
        raise ValueError("Release 47 no longer contains the particle queue repair")
    old_bundle = (ROOT / "blobs" / OLD_BLOB).read_bytes()
    patched = patch_bundle(old_bundle)
    if OVERRIDE.exists() and OVERRIDE.read_bytes() != patched:
        raise FileExistsError("An unrelated final APK override already exists")

    sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read("assets/update_public_key.der"))
    public.verify(base64.b64decode((source / "manifest.sig").read_bytes()), base_raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if public.public_numbers() != private.public_key().public_numbers():
        raise ValueError("Update signing key differs from the installed APK")
    blob_sha = sha(patched)
    fixed = copy.deepcopy(base)
    for asset in fixed["assets"]:
        if asset["path"] == LOGICAL:
            asset.update({"url": "/updates/stable/blobs/" + blob_sha,
                          "size": len(patched), "sha256": blob_sha})
    fix = previous.signed_release(fixed, 49, private, public)
    rollback = previous.signed_release(base, 50, private, public)
    for name, _, _ in (fix, rollback):
        if (ROOT / "releases" / name).exists():
            raise FileExistsError("Signed release already exists: " + name)
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    if not OVERRIDE.exists():
        OVERRIDE.write_bytes(patched)
    if OVERRIDE.read_bytes() != patched:
        raise IOError("Final APK override write failed")
    blob = ROOT / "blobs" / blob_sha
    if blob.exists() and blob.read_bytes() != patched:
        raise ValueError("Content-addressed blob differs")
    if not blob.exists():
        blob.write_bytes(patched)
    for name, raw, sig in (fix, rollback):
        folder = ROOT / "releases" / name
        folder.mkdir(parents=False)
        (folder / "manifest.json").write_bytes(raw)
        (folder / "manifest.sig").write_bytes(sig)
        public.verify(base64.b64decode(sig), raw, padding.PKCS1v15(), hashes.SHA256())
    print("SETTLEMENT_PANEL_HOTUPDATE_READY", fix[0], rollback[0], blob_sha, flush=True)


if __name__ == "__main__":
    main()
