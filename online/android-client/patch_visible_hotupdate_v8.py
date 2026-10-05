"""A visible, login-only hot-update marker for release sequence 8.

The single TextAsset change makes the existing email login-type label show
"Email · 热更8". It does not alter the login request, UI hierarchy or save.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
ASSET_NAME = "LoginFormalPatch.lua"
BASE_BUNDLE_SHA256 = "549b852a2e1f66dc1e8fb55ea07d4951028863a2c40706ae81bc1937946a01c3"
BASE_OBJECT_SHA256 = "3f2c83d19d90fba1b152f78eff235a6672f141ca0fd70faaea820ee96ebe770a"
BASE_SCRIPT_SHA256 = "5345c789ba37e6735b775c5147096c7136cab0e4ad2c90453ee1533bc10f3c08"
OLD_LABEL = "str = 'Email'"
NEW_LABEL = "str = 'Email · 热更8'"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def patch(raw: bytes) -> bytes:
    if sha(raw) != BASE_BUNDLE_SHA256:
        raise ValueError("Current Lua AssetBundle differs from signed sequence 7")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    matching = [
        obj for obj in bundle.objects
        if obj.type.name == "TextAsset"
        and obj.read_typetree().get("m_Name") == ASSET_NAME
    ]
    if len(matching) != 1:
        raise ValueError("Email login TextAsset inventory changed")
    target = matching[0]
    if before[target.path_id] != BASE_OBJECT_SHA256:
        raise ValueError("Email login TextAsset differs from reviewed baseline")
    tree = target.read_typetree()
    source = tree.get("m_Script")
    if not isinstance(source, str) or sha(source.encode("utf-8")) != BASE_SCRIPT_SHA256:
        raise ValueError("Email login Lua source differs from reviewed baseline")
    if source.count(OLD_LABEL) != 1:
        raise ValueError("Email login label anchor is ambiguous")
    updated = source.replace(OLD_LABEL, NEW_LABEL, 1)
    tree["m_Script"] = updated
    target.save_typetree(tree)

    result = bundle.file.save(packer="original")
    checked = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in checked.objects}
    if set(after) != set(before) or {
        path_id for path_id in before if before[path_id] != after[path_id]
    } != {target.path_id}:
        raise ValueError("Visible patch changed unrelated Unity objects")
    scripts = [
        obj.read_typetree().get("m_Script") for obj in checked.objects
        if obj.path_id == target.path_id
    ]
    if scripts != [updated]:
        raise ValueError("Visible patch did not round-trip")
    return result
