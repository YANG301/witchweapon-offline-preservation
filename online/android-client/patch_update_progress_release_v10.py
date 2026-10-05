"""Remove temporary hot-update markers for the progress-UI acceptance release."""

from __future__ import annotations

import hashlib

import UnityPy


BUNDLE = "assets/assetbundle/lua/lua_projx_patch.ab"
BASE_SHA256 = "78b2d551777ee0f6c10632814d29119ac199c01924c0b8336391341d1509c3eb"
REPLACEMENTS = {
    "LoginFormalPatch.lua": ("str = 'Email · 热更8'", "str = 'Email'"),
    "TaskItemPatch.lua": (
        "    text = '[80E0FF]热更9[-] ' .. text\n",
        "",
    ),
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch(raw: bytes) -> bytes:
    if sha256(raw) != BASE_SHA256:
        raise ValueError("Unexpected sequence-9 Lua AssetBundle")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha256(obj.get_raw_data()) for obj in bundle.objects}
    selected = {}
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        name = tree.get("m_Name")
        if name not in REPLACEMENTS:
            continue
        if name in selected:
            raise ValueError("Duplicate Lua asset: " + name)
        old, new = REPLACEMENTS[name]
        script = tree.get("m_Script")
        if not isinstance(script, str) or script.count(old) != 1:
            raise ValueError("Missing temporary marker: " + name)
        rewritten = script.replace(old, new, 1)
        if name == "LoginFormalPatch.lua":
            # Give this semantically unchanged Lua a new signed blob identity;
            # otherwise devices may reuse the cached sequence-7 blob and there
            # would be no network transfer with which to test the progress UI.
            rewritten = "-- signed resource progress acceptance v10\n" + rewritten
        tree["m_Script"] = rewritten
        obj.save_typetree(tree)
        selected[name] = (obj.path_id, tree["m_Script"])
    if set(selected) != set(REPLACEMENTS):
        raise ValueError("Lua marker inventory differs")
    result = bundle.file.save(packer="original")
    checked = UnityPy.load(result)
    after = {obj.path_id: sha256(obj.get_raw_data()) for obj in checked.objects}
    if set(before) != set(after) or {
        path_id for path_id in before if before[path_id] != after[path_id]
    } != {entry[0] for entry in selected.values()}:
        raise ValueError("Unrelated Unity object changed")
    for obj in checked.objects:
        for path_id, expected in selected.values():
            if obj.path_id == path_id and obj.read_typetree().get("m_Script") != expected:
                raise ValueError("Lua marker removal failed to round-trip")
    if result == raw:
        raise ValueError("Result did not change")
    return result
