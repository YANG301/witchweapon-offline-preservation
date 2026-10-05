"""Build a separately signed ordinary-draw cost/retry candidate from open-access APK.

Only Constant.ab, its bundle index, and classes2.dex change. The production
OfflineApplication.java remains untouched; the DEX is made from a temporary
copy that first reproduces the pinned inherited touch-trace DEX exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_online_apk as adapter
import build_original_ui_quest_refresh_v6_apk as base
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import build_original_ui_lottery_touch_probe_apk as touch
import patch_draw_costs as costs


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-original-ui-open-access-v1.apk"
SOURCE_SHA256 = "7a365e3c654d43157b0acbd0d8ed5b4fdb22fc8fbdfe21d033bd072332f3b536"
SOURCE_DEX_SHA256 = "3bfd5cedc15878bbb23f705db499dde7c8f68249407daf62598ffe92feddfa9d"
JAVA_SOURCE = HERE / "src/com/codex/witchweapon/OfflineApplication.java"
JAVA_SOURCE_SHA256 = "0da03b2780bf9a915a078b5f0f9908c19f8bd6ae0eaf20b1f903b3f9643a4fb8"
BRIDGE = HERE / "draw-bridge/DrawRequestIdempotency.java"
ORIGINAL_CONSTANT = Path(
    r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel\constant.ab")
RESULT = HERE / "build/witchweapon-online-original-ui-priced-draw-v1.apk"
REPORT = HERE / "build/原版普通抽卡成本候选包验收.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-online-priced-draw")
DEX = "classes2.dex"
BUNDLE = "assets/assetbundle/config/clientexel/constant.ab"
INDEX = "assets/m.assets_list.txt"


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("Pinned bridge source anchor changed: " + before[:80])
    return source.replace(before, after, 1)


def java_source(draw_bridge: bool) -> Path:
    if base.sha256(JAVA_SOURCE) != JAVA_SOURCE_SHA256:
        raise ValueError("Pinned production Java source changed")
    source = JAVA_SOURCE.read_text(encoding="utf-8")
    source = replace_once(source, touch.ANCHOR, touch.INJECTION)
    if draw_bridge:
        source = replace_once(source,
            "                        byte[] forwardedBody = appendBattleEnergy(path, contentType, body);",
            "                        byte[] forwardedBody = DrawRequestIdempotency.append(path, contentType, "
            "appendBattleEnergy(path, contentType, body));")
        source = replace_once(source,
            "                    if (status >= 200 && status < 300 && \"POST\".equals(method)) refreshMirrorAsync();",
            "                    if (status >= 200 && status < 300 && \"POST\".equals(method)) {\n"
            "                        DrawRequestIdempotency.confirm(path, body);\n"
            "                        refreshMirrorAsync();\n"
            "                    }")
    target = (TEMP / ("draw-source" if draw_bridge else "baseline-source") /
              "com/codex/witchweapon/OfflineApplication.java")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source, encoding="utf-8")
    return target


def compile_bridge(old_dex: bytes) -> bytes:
    old_classes = set(adapter.dex_classes(old_dex))
    if "Lcom/codex/witchweapon/LotteryTouchTrace;" not in old_classes:
        raise ValueError("Inherited touch-trace class is missing")
    adapter.TEMP = TEMP

    def sources(draw_bridge: bool):
        copied = java_source(draw_bridge)
        result = [copied, touch.TRACE]
        result.extend(HERE / "src/com/codex/witchweapon" / name for name in adapter.ADAPTER
                      if name != "OfflineApplication.java")
        result.extend(adapter.AUTHOR / name for name in adapter.AUTHOR_HELPERS)
        if draw_bridge:
            result.append(BRIDGE)
        return result

    baseline, baseline_classes = adapter.compile_dex(sources(False), old_classes)
    if baseline != old_dex or set(baseline_classes) != old_classes:
        raise ValueError("Production Java and touch-trace sources do not reproduce inherited DEX")
    patched, patched_classes = adapter.compile_dex(sources(True), old_classes)
    if set(patched_classes) != old_classes | {
            "Lcom/codex/witchweapon/DrawRequestIdempotency;",
            "Lcom/codex/witchweapon/DrawRequestIdempotency$Entry;"}:
        raise ValueError("Draw bridge changed unrelated DEX class inventory")
    if patched == old_dex:
        raise ValueError("Draw bridge did not change DEX")
    return patched


def prepare() -> dict[str, bytes]:
    if not SOURCE.is_file() or base.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Pinned open-access APK is missing or changed")
    if not BRIDGE.is_file() or not ORIGINAL_CONSTANT.is_file():
        raise ValueError("Draw patch input missing")
    with zipfile.ZipFile(SOURCE) as source:
        names = source.namelist()
        if len(names) != len(set(names)) or any(item not in names for item in (DEX,BUNDLE,INDEX)):
            raise ValueError("Unexpected source APK members")
        old_dex = source.read(DEX)
        if hashlib.sha256(old_dex).hexdigest() != SOURCE_DEX_SHA256:
            raise ValueError("Pinned source DEX changed")
        revised_bundle = costs.patch_bundle(source.read(BUNDLE), ORIGINAL_CONSTANT.read_bytes())
        if revised_bundle == source.read(BUNDLE):
            raise ValueError("Original draw costs already present in source")
        revised_index = patch_index(source.read(INDEX),
                                    {"/config/clientexel/constant.ab": revised_bundle})
    revised_dex = compile_bridge(old_dex)
    return {DEX: revised_dex, BUNDLE: revised_bundle, INDEX: revised_index}


def build(changes: dict[str, bytes]) -> dict:
    if RESULT.exists() or REPORT.exists():
        raise ValueError("Versioned candidate already exists")
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA256, TEMP
    report = base.build(changes, RESULT, REPORT)
    signer = [base.JAVA, "-jar", base.TOOLS / "lib/apksigner.jar"]
    before = cert_digest(base.run([*signer, "verify", "--print-certs", SOURCE], base.signer_env()))
    after = cert_digest(base.run([*signer, "verify", "--print-certs", RESULT], base.signer_env()))
    if before != after:
        raise ValueError("APK signing identity changed")
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(RESULT) as new:
        for name in ("AndroidManifest.xml", "classes.dex", "assets/assetbundle/lua/lua.ab"):
            if old.read(name) != new.read(name):
                raise ValueError("Critical original game payload changed: " + name)
    report.update(changedUnityAssets=["Constant: original ordinary draw costs/cooldown"],
                  drawRoutes=["/draw/gold/single", "/draw/gold/ten",
                              "/draw/rmb/single", "/draw/rmb/ten"],
                  guideDrawUnchanged=True, sameSignerCertificateSha256=after,
                  drawRetryGraceSeconds={"confirmed": 8, "uncertain": 45},
                  runtimeValidated=False)
    for stale in ("changedUnityTextAsset", "originalUnityTextAssetSha256",
                  "preservesV4TaskItemPatch", "nativeRefreshClass"):
        report.pop(stale, None)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Sign candidate, but never install")
    args = parser.parse_args()
    if TEMP.exists():
        raise ValueError("Unexpected previous draw-build temporary directory")
    try:
        changes = prepare()
        if args.build:
            report = build(changes)
            print("PRICED_DRAW_APK_READY", report["testApk"]["sha256"])
        else:
            print("PRICED_DRAW_PATCH_CHECK_OK", len(changes),
                  hashlib.sha256(changes[DEX]).hexdigest())
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r"D:\Environment\Android\temp").resolve() or \
                    resolved.name != "witch-online-priced-draw":
                raise ValueError("Unsafe draw-build temporary cleanup")
            shutil.rmtree(resolved)


if __name__ == "__main__":
    main()
