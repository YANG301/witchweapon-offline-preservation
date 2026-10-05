"""Build a separately signed client candidate for the account and task fixes.

The source is the pinned v3 APK. Only classes2.dex, the two reviewed Lua
bundles and their index change. Never replace the installed or release APK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as signer
import build_original_ui_lottery_touch_probe_apk as touch
import build_priced_draw_apk as draw
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import patch_all_task_refresh as tasks


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online.apk"
SOURCE_SHA256 = tasks.EXPECTED_APK_SHA256
DEX_SHA256 = "f92724c979f671c435b4916f7eb5ed8cddbdd946cdd733c1d200519276b30b89"
AUTH_SOURCE = HERE / "src/com/codex/witchweapon/OriginalUiAuthBridge.java"
AUTH_SHA256 = "a2c80510a1940ed89a1ee1a3b3a2f146a37c1be148e27bc385da94dcf811c898"
DEX_MEMBER = "classes2.dex"
INDEX_MEMBER = "assets/m.assets_list.txt"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-bugfix-v4")
RESULT = HERE / "build/witchweapon-online-bugfix-v4-test.apk"
REPORT = HERE / "build/在线修复候选包验收-v4.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare() -> tuple[dict[str, bytes], dict[str, object]]:
    if tasks.sha256_file(SOURCE) != SOURCE_SHA256:
        raise ValueError("Unreviewed source APK")
    if tasks.sha256_file(AUTH_SOURCE) != AUTH_SHA256:
        raise ValueError("Unreviewed account-error fix source")
    if TEMP.exists():
        raise ValueError("Stale bugfix build directory")
    with zipfile.ZipFile(SOURCE) as apk:
        if len(apk.namelist()) != len(set(apk.namelist())):
            raise ValueError("Duplicate source APK members")
        old_dex = apk.read(DEX_MEMBER)
        if digest(old_dex) != DEX_SHA256:
            raise ValueError("Unreviewed source DEX")
        old_classes = set(adapter.dex_classes(old_dex))
        old_index = apk.read(INDEX_MEMBER)
        bundles = {name: apk.read(name) for name in tasks.EXPECTED_BUNDLE_SHA256}
    patched_bundles, changed_assets = tasks.patch_bundles(bundles)
    if any(patched_bundles[name] == bundles[name] for name in bundles):
        raise ValueError("Expected both Lua bundles to change")

    # Recreate the already-installed touch-trace and draw idempotency bridge.
    # Compiling OfflineApplication.java directly would silently lose both.
    draw.TEMP = TEMP
    adapter.TEMP = TEMP
    copied_app = draw.java_source(True)
    sources = [copied_app, touch.TRACE]
    sources.extend(HERE / "src/com/codex/witchweapon" / name for name in adapter.ADAPTER
                   if name != "OfflineApplication.java")
    sources.extend(adapter.AUTHOR / name for name in adapter.AUTHOR_HELPERS)
    sources.append(draw.BRIDGE)
    revised_dex, new_classes = adapter.compile_dex(sources, old_classes)
    if set(new_classes) != old_classes or revised_dex == old_dex:
        raise ValueError("Account bridge DEX class inventory changed")

    index = patch_index(old_index, {
        "/lua/" + Path(name).name: raw for name, raw in patched_bundles.items()
    })
    changes = dict(patched_bundles)
    changes[DEX_MEMBER] = revised_dex
    changes[INDEX_MEMBER] = index
    return changes, {
        "clientChange": "12-128 character password error uses original CE10114 code",
        "changedLuaTextAssets": changed_assets,
        "sourceDexSha256": DEX_SHA256,
        "candidateDexSha256": digest(revised_dex),
        "runtimeValidated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign candidate APK")
    args = parser.parse_args()
    changes, detail = prepare()
    try:
        if args.build:
            signer.SOURCE = SOURCE
            signer.SOURCE_SHA256 = SOURCE_SHA256
            signer.TEMP = TEMP
            report = signer.build(changes, RESULT, REPORT)
            before = cert_digest(signer.run([
                signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                "verify", "--print-certs", SOURCE], signer.signer_env()))
            after = cert_digest(signer.run([
                signer.JAVA, "-jar", signer.TOOLS / "lib/apksigner.jar",
                "verify", "--print-certs", RESULT], signer.signer_env()))
            if before != after:
                raise ValueError("APK signer changed")
            with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(RESULT) as new:
                for name in ("AndroidManifest.xml", "classes.dex", "assets/online_endpoint.txt"):
                    if old.read(name) != new.read(name):
                        raise ValueError("Production-critical member changed: " + name)
            for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                          "preservesV4TaskItemPatch", "nativeRefreshClass"):
                report.pop(stale, None)
            report.update(detail)
            report["sourceApkSha256"] = SOURCE_SHA256
            report["signerCertificateSha256"] = after
            REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
            print("BUGFIX_V4_APK_READY", report["testApk"]["sha256"])
        else:
            print("BUGFIX_V4_STATIC_OK", json.dumps({
                "changedMembers": sorted(changes), **detail}, ensure_ascii=False))
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r"D:\Environment\Android\temp").resolve() or \
                    resolved.name != "witch-online-bugfix-v4":
                raise ValueError("Unsafe bugfix temp cleanup target")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
