"""Patch only the battle-settlement level-up particle render queues.

The signed resource release is deliberately staged locally. Publishing is a
separate operation after the active release has been checked on the server.
The same patched bundle is kept under resources-overrides for the next APK.
"""

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


PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / "热更新测试" / "主线热更候选"
APK = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地双区服-v110-测试.apk")
KEY = PROJECT / ".local" / "热更新密钥" / "签名私钥.pem"
APK_MEMBER = "assets/assetbundle/assets/resources/ui/prefab/settlement.ab"
LOGICAL_PATH = "assetbundle/assets/resources/ui/prefab/settlement.ab"
APK_BUNDLE_SHA = "d92a20aee6f8635eb4c47f9072699e0cf68712a6dec7374201a5cd9b9b8ca147"
TARGETS = {
    9098637359406585277: "lv_03",
    -6553390747368790970: "lv_04",
    2432090746599879568: "lv_05",
}
OLD_QUEUE = 3047
# WatchmenContainer's NGUI panel starts at 3015. The glow belongs behind it.
NEW_QUEUE = 3014
OVERRIDE = PROJECT / "android-client" / "resources-overrides" / "settlement-levelup.ab"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_bundle(original: bytes) -> bytes:
    if sha(original) != APK_BUNDLE_SHA:
        raise ValueError("Settlement bundle differs from the inspected v110 APK")
    bundle = UnityPy.load(original)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    if len(before) != 833:
        raise ValueError("Unexpected settlement object inventory")
    found = set()
    for obj in bundle.objects:
        if obj.path_id not in TARGETS:
            continue
        if obj.type.name != "Material":
            raise ValueError("Target object is no longer a Material")
        tree = obj.read_typetree()
        if (tree.get("m_Name") != TARGETS[obj.path_id]
                or tree.get("m_CustomRenderQueue") != OLD_QUEUE):
            raise ValueError("Level-up material changed in the source bundle")
        tree["m_CustomRenderQueue"] = NEW_QUEUE
        obj.save_typetree(tree)
        found.add(obj.path_id)
    if found != set(TARGETS):
        raise ValueError("Not all three level-up materials were found")
    result = bundle.file.save(packer="original")
    reopened = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in reopened.objects}
    if set(after) != set(before) or {pid for pid in before if before[pid] != after[pid]} != found:
        raise ValueError("Settlement patch changed unrelated Unity objects")
    for obj in reopened.objects:
        if obj.path_id in TARGETS:
            tree = obj.read_typetree()
            if tree.get("m_Name") != TARGETS[obj.path_id] or tree.get("m_CustomRenderQueue") != NEW_QUEUE:
                raise ValueError("Patched Material failed round-trip")
    return result


def signed_release(manifest: dict, sequence: int, private, public) -> tuple[str, bytes, bytes]:
    manifest = copy.deepcopy(manifest)
    manifest["releaseSequence"] = sequence
    raw = (json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    name = f"{sequence}-{sha(raw)}"
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signature = private.sign(raw, padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, raw, padding.PKCS1v15(), hashes.SHA256())
    return name, raw, base64.b64encode(signature) + b"\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="reviewed active signed release directory name")
    parser.add_argument("--sequence", type=int, help="fix release sequence; rollback uses the next sequence")
    args = parser.parse_args()
    if (args.base is None) != (args.sequence is None):
        parser.error("--base and --sequence must be given together")

    with zipfile.ZipFile(APK) as apk:
        original = apk.read(APK_MEMBER)
        public_der = apk.read("assets/update_public_key.der")
        version = apk.read("assets/m.version").decode("ascii").strip()
    patched = patch_bundle(original)
    if OVERRIDE.exists() and OVERRIDE.read_bytes() != patched:
        raise FileExistsError("An unrelated APK override already exists")
    OVERRIDE.parent.mkdir(parents=True, exist_ok=True)
    if not OVERRIDE.exists():
        OVERRIDE.write_bytes(patched)
    if OVERRIDE.read_bytes() != patched:
        raise IOError("APK override write failed")
    print("SETTLEMENT_BUNDLE_READY", sha(patched), len(patched), str(OVERRIDE), flush=True)
    if args.base is None:
        return

    if args.sequence <= int(args.base.split("-", 1)[0]):
        raise ValueError("Fix release must advance the active release sequence")
    source = ROOT / "releases" / args.base
    base_raw = (source / "manifest.json").read_bytes()
    if sha(base_raw) != args.base.split("-", 1)[1]:
        raise ValueError("Base manifest digest differs from its directory name")
    base = json.loads(base_raw)
    if (base.get("targetAppVersion") != version
            or base.get("releaseSequence") != int(args.base.split("-", 1)[0])
            or any(item["path"] == LOGICAL_PATH for item in base["assets"])):
        raise ValueError("Unexpected signed release base or already patched settlement bundle")

    sys.path.insert(0, r"D:\Environment\VPS-SSH\packages313")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    public = serialization.load_der_public_key(public_der)
    public.verify(base64.b64decode((source / "manifest.sig").read_bytes()), base_raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(KEY.read_bytes(), password=None)
    if public.public_numbers() != private.public_key().public_numbers():
        raise ValueError("Signing key differs from the installed APK")

    blob_sha = sha(patched)
    fixed = copy.deepcopy(base)
    fixed["assets"].append({"path": LOGICAL_PATH, "url": "/updates/stable/blobs/" + blob_sha,
                            "size": len(patched), "sha256": blob_sha})
    fix = signed_release(fixed, args.sequence, private, public)
    rollback = signed_release(base, args.sequence + 1, private, public)
    for name, _, _ in (fix, rollback):
        if (ROOT / "releases" / name).exists():
            raise FileExistsError("Signed release already exists: " + name)
    blob = ROOT / "blobs" / blob_sha
    if blob.exists() and blob.read_bytes() != patched:
        raise ValueError("Content-addressed blob is corrupt")
    if not blob.exists():
        blob.write_bytes(patched)
    for name, raw, signature in (fix, rollback):
        folder = ROOT / "releases" / name
        folder.mkdir(parents=False)
        (folder / "manifest.json").write_bytes(raw)
        (folder / "manifest.sig").write_bytes(signature)
        public.verify(base64.b64decode(signature), raw, padding.PKCS1v15(), hashes.SHA256())
    print("SETTLEMENT_HOTUPDATE_READY", fix[0], rollback[0], blob_sha, flush=True)


if __name__ == "__main__":
    main()
