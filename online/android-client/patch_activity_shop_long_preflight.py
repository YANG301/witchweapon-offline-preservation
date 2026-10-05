"""Keep original activity shop rows when ToLua exposes a C# long value.

The online overview preflight introduced in the earlier carousel patch checks
``type(StopTime) == 'number'``. The game's ToLua bridge pushes C# long values
through ``tolua_pushint64``; they are not ordinary Lua numbers. The original
UI accepts these values and performs arithmetic on them. This v10-only patch
changes just that preflight check, leaving the original activity controls.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_ui.ab"
ASSET_NAME = "UIActivities.lua"
EXPECTED_V10_BUNDLE_SHA256 = "0d6ff08efcd517b49da935aa9e309c2fd2cd6c06b1da4c9c9eab249236c0063a"
EXPECTED_V10_OBJECT_SHA256 = "1aa17adcaf0d5ee6f5cca3da6932b4961dd74a0d85da29727bee0e363493edd3"
OLD_CHECK = "return timeOK and type(timeValue) == 'number'"
NEW_CHECK = "return timeOK and timeValue ~= nil"


def patch_script(source: str) -> str:
    if source.count(OLD_CHECK) != 1 or NEW_CHECK in source:
        raise ValueError("Unexpected activity shop preflight source")
    if source.count("local shopIDs = {44000001, 44000070, 44000012}") != 1:
        raise ValueError("7# activity set link missing")
    if source.count("shopsID = 44000070") != 2 or \
            source.count("shopsID = 44000012") != 2:
        raise ValueError("Original special-shop activity rows changed")
    return source.replace(OLD_CHECK, NEW_CHECK, 1)


def patch_bundle(raw: bytes) -> bytes:
    if hashlib.sha256(raw).hexdigest() != EXPECTED_V10_BUNDLE_SHA256:
        raise ValueError("Unreviewed v10 activity Lua bundle")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest()
              for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(targets) != 1 or before[targets[0].path_id] != EXPECTED_V10_OBJECT_SHA256:
        raise ValueError("Unreviewed v10 activity overview object")
    target = targets[0]
    tree = target.read_typetree()
    if not isinstance(tree.get("m_Script"), str):
        raise ValueError("Unexpected Lua script encoding")
    tree["m_Script"] = patch_script(tree["m_Script"])
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    updated = UnityPy.load(result)
    changed = [obj.path_id for obj in updated.objects if
               hashlib.sha256(obj.get_raw_data()).hexdigest() != before[obj.path_id]]
    if changed != [target.path_id]:
        raise ValueError("Shop preflight patch changed unrelated Unity objects")
    reloaded = next(obj.read_typetree()["m_Script"] for obj in updated.objects
                    if obj.path_id == target.path_id)
    if reloaded != tree["m_Script"]:
        raise ValueError("Shop preflight patch failed bundle round-trip")
    return result
