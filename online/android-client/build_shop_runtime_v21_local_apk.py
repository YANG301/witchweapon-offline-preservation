"""Build the isolated shop client without the archived count-hiding timer."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import UnityPy

import build_shop_runtime_v16_local_apk as composer
import build_shop_runtime_v20_local_apk as previous
from build_online_apk import patch_index


BUILD = Path(__file__).resolve().parent / "build"
RESULT = BUILD / "witchweapon-online-local-staging-shop-runtime-v21.apk"
REPORT = BUILD / "本地测试服商店运行时验收-v21.json"
OLD = b"2.0.1.20043081"
NEW = b"2.0.1.20043082"
LUA_BUNDLE = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
OLD_TIMER = "for _,name in ipairs({'buyWidget','FreshView'}) do"
NEW_TIMER = "for _,name in ipairs({'FreshView'}) do"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def preserve_native_counter(raw: bytes) -> bytes:
    """Stop the inherited timer from hiding the original shop counter."""
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(targets) != 1:
        raise ValueError("Expected one active init.lua TextAsset")
    target = targets[0]
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if not isinstance(source, str) or source.count(OLD_TIMER) != 1 or \
            source.count("buyWidget") != 1 or NEW_TIMER in source:
        raise ValueError("Unreviewed archived shop timer")
    updated_source = source.replace(OLD_TIMER, NEW_TIMER)
    tree["m_Script"] = updated_source
    target.save_typetree(tree)
    updated = bundle.file.save(packer="original")
    restored = UnityPy.load(updated)
    changed = {obj.path_id for obj in restored.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    scripts = [obj.read_typetree().get("m_Script") for obj in restored.objects
               if obj.path_id == target.path_id]
    if changed != {target.path_id} or scripts != [updated_source] or \
            "buyWidget" in updated_source:
        raise ValueError("Unexpected shop timer patch result")
    return updated


def prepare():
    changed = previous.prepare()
    if changed["assets/m.version"] != OLD + b"\r\n":
        raise ValueError("Unexpected prepared cache version")
    fixture = changed["assets/offline_responses.json"]
    if fixture.count(OLD) != 3 or NEW in fixture:
        raise ValueError("Unexpected prepared version fixture")
    changed["assets/m.version"] = NEW + b"\r\n"
    changed["assets/offline_responses.json"] = fixture.replace(OLD, NEW)
    changed[LUA_BUNDLE] = preserve_native_counter(changed[LUA_BUNDLE])
    changed[INDEX] = patch_index(changed[INDEX],
                                 {"/lua/lua.ab": changed[LUA_BUNDLE]})
    return changed


def build(changed):
    if RESULT.exists() or REPORT.exists():
        raise ValueError("v21 output already exists")
    composer.RESULT = RESULT
    composer.REPORT = REPORT
    report = composer.build(changed)
    report["purpose"] = "Local original shop counter with no archived timer override"
    report["assetVersion"] = NEW.decode("ascii")
    report["runtimeValidated"] = False
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    changed = prepare()
    if not args.build:
        print("SHOP_RUNTIME_V21_STATIC_OK", len(changed),
              composer.digest(changed[INDEX]))
        return
    report = build(changed)
    print("SHOP_RUNTIME_V21_LOCAL_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
