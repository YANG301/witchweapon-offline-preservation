"""Hide the original lobby's red NEW guide envelope without touching hero UI.

The source is the reviewed MainScenePanel AssetBundle.  The guide button is a
separate prefab child, so a resource hot update can hide it without changing
the tutorial data, player state, or other lobby controls.
"""

from __future__ import annotations

import hashlib

import UnityPy


MEMBER = "assets/assetbundle/assets/resources/ui/prefab/mainscenepanel.ab"
INDEX_KEY = "/assets/resources/ui/prefab/mainscenepanel.ab"
SOURCE_SHA256 = "d0e25c003dd1349e66cc2fb00ae6679e70248cc8bab1d196693877832bff5577"

BUTTON = 3820261630292998280
BUTTON_TRANSFORM = -1152630636205673369
BUTTON_SPRITE = 6339127332513134425
BUTTON_COLLIDER = -4910367181958768289
CHILD = -5190237726021659157
CHILD_TRANSFORM = -6260525298606889768
CHILD_SPRITE = -7192404532478362958
CHANGED = {BUTTON, BUTTON_SPRITE, BUTTON_COLLIDER, CHILD, CHILD_SPRITE}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _components(tree: dict) -> set[int]:
    return {entry["component"]["m_PathID"] for entry in tree["m_Component"]}


def patch(raw: bytes) -> bytes:
    if sha(raw) != SOURCE_SHA256:
        raise ValueError("Unreviewed MainScenePanel AssetBundle")
    bundle = UnityPy.load(raw)
    objects = {obj.path_id: obj for obj in bundle.objects}
    before = {path_id: sha(obj.get_raw_data()) for path_id, obj in objects.items()}

    button = objects[BUTTON].read_typetree()
    child = objects[CHILD].read_typetree()
    button_transform = objects[BUTTON_TRANSFORM].read_typetree()
    child_transform = objects[CHILD_TRANSFORM].read_typetree()
    if (objects[BUTTON].type.name != "GameObject"
            or objects[CHILD].type.name != "GameObject"
            or button["m_Name"] != "GuideTaskBtn" or button["m_IsActive"] is not True
            or child["m_Name"] != "taskBG" or child["m_IsActive"] is not True
            or not {BUTTON_TRANSFORM, BUTTON_SPRITE, BUTTON_COLLIDER}.issubset(_components(button))
            or not {CHILD_TRANSFORM, CHILD_SPRITE}.issubset(_components(child))
            or child_transform["m_Father"]["m_PathID"] != BUTTON_TRANSFORM
            or CHILD_TRANSFORM not in {
                entry["m_PathID"] for entry in button_transform["m_Children"]
            }):
        raise ValueError("Reviewed guide envelope hierarchy changed")

    for path_id, tree in ((BUTTON, button), (CHILD, child)):
        tree["m_IsActive"] = False
        objects[path_id].save_typetree(tree)

    for path_id, name in ((BUTTON_SPRITE, "Icon_envelope_new"),
                          (CHILD_SPRITE, "Button_MainUI_Mission_Light")):
        sprite = objects[path_id]
        tree = sprite.read_typetree()
        if (sprite.type.name != "MonoBehaviour" or tree.get("mSpriteName") != name
                or tree.get("m_Enabled") != 1 or tree.get("mColor", {}).get("a") != 1.0):
            raise ValueError("Reviewed guide envelope sprite changed: " + name)
        tree["m_Enabled"] = 0
        tree["mColor"]["a"] = 0.0
        sprite.save_typetree(tree)

    collider = objects[BUTTON_COLLIDER]
    collider_tree = collider.read_typetree()
    if collider.type.name != "BoxCollider" or collider_tree.get("m_Enabled") is not True:
        raise ValueError("Reviewed guide envelope collider changed")
    collider_tree["m_Enabled"] = False
    collider.save_typetree(collider_tree)

    updated = bundle.file.save(packer="original")
    check = {obj.path_id: obj for obj in UnityPy.load(updated).objects}
    actual = {path_id for path_id, obj in check.items()
              if sha(obj.get_raw_data()) != before[path_id]}
    if set(check) != set(objects) or actual != CHANGED:
        raise ValueError("Guide envelope patch changed unrelated prefab objects")
    if any(check[path_id].read_typetree()["m_IsActive"] is not False
           for path_id in (BUTTON, CHILD)):
        raise ValueError("Guide envelope remained active after repacking")
    if check[BUTTON_COLLIDER].read_typetree()["m_Enabled"] is not False:
        raise ValueError("Guide envelope collider remained enabled")
    return updated
