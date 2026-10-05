"""Make the published sequence-10 blob distinct from the bundled test blob.

Only an inert Lua comment changes. Devices upgrading through the Android
progress bridge must fetch the signed blob, proving actual byte progress.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
BASE_SHA256 = "43c02447e2202d9cf7945b094f8e59e35f5f2104ed6577dae472bcd272968c9f"
NAME = "LoginFormalPatch.lua"
OLD = "-- signed resource progress acceptance v10\n"
NEW = "-- signed resource progress delivery v10\n"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    if sha(raw) != BASE_SHA256:
        raise ValueError("Unexpected bundled progress-bridge Lua baseline")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    targets = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == NAME]
    if len(targets) != 1:
        raise ValueError("Login Lua inventory changed")
    target = targets[0]
    tree = target.read_typetree()
    script = tree.get("m_Script")
    if not isinstance(script, str) or script.count(OLD) != 1:
        raise ValueError("Acceptance Lua comment differs")
    tree["m_Script"] = script.replace(OLD, NEW, 1)
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    checked = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in checked.objects}
    if set(before) != set(after) or {
        path_id for path_id in before if before[path_id] != after[path_id]
    } != {target.path_id}:
        raise ValueError("Unrelated Unity object changed")
    scripts = [obj.read_typetree().get("m_Script") for obj in checked.objects
               if obj.path_id == target.path_id]
    if scripts != [tree["m_Script"]] or result == raw:
        raise ValueError("Delivery Lua did not round-trip")
    return result
