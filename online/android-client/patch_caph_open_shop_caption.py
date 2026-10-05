"""Hide the obsolete C.A.P.H shop-closed caption in the original prefab.

The original native VipPanel.OpenPanel reactivates closeShopTitle whenever
ActivityPlay.ActOpen is false.  The point shop is open through Serial/TimeData,
but switching ActOpen on breaks login because special action is incomplete.
Only the caption UILabel is disabled; the original shop button is untouched.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/assets/resources/ui/prefab/vip/vippanel.ab"
SOURCE_SHA256 = "cae1c504eda3573c94c58e747c59b669c3dccece4d58949d9cfd1e567330a392"
CAPTION_GO = -1676103318769569056
CAPTION_LABEL = -6129238833096444051


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_bundle(raw: bytes) -> bytes:
    if digest(raw) != SOURCE_SHA256:
        raise ValueError("Unreviewed C.A.P.H prefab")
    bundle = UnityPy.load(raw)
    objects = {obj.path_id: obj for obj in bundle.objects}
    before = {path_id: digest(obj.get_raw_data()) for path_id, obj in objects.items()}
    game_object = objects[CAPTION_GO].read_typetree()
    components = {part["component"]["m_PathID"] for part in game_object["m_Component"]}
    if (game_object["m_Name"] != "closeShopTitle" or
            game_object["m_IsActive"] is not True or
            components != {2876530322376492412, CAPTION_LABEL}):
        raise ValueError("C.A.P.H caption hierarchy changed")
    label_obj = objects[CAPTION_LABEL]
    if label_obj.type.name != "MonoBehaviour":
        raise ValueError("C.A.P.H caption is not a UILabel")
    label = label_obj.read_typetree()
    if (label.get("m_Enabled") != 1 or label.get("mColor", {}).get("a") != 1.0 or
            not label.get("mText")):
        raise ValueError("C.A.P.H caption state changed")
    label["m_Enabled"] = 0
    label["mColor"]["a"] = 0.0
    label_obj.save_typetree(label)
    result = bundle.file.save(packer="original")
    reloaded = UnityPy.load(result)
    actual = {obj.path_id for obj in reloaded.objects
              if digest(obj.get_raw_data()) != before[obj.path_id]}
    if actual != {CAPTION_LABEL}:
        raise ValueError("Unrelated C.A.P.H prefab object changed")
    after = {obj.path_id: obj.read_typetree() for obj in reloaded.objects
             if obj.path_id in (CAPTION_GO, CAPTION_LABEL)}
    if (after[CAPTION_GO] != game_object or
            after[CAPTION_LABEL]["m_Enabled"] != 0 or
            after[CAPTION_LABEL]["mColor"]["a"] != 0.0):
        raise ValueError("C.A.P.H caption patch failed to round-trip")
    return result
