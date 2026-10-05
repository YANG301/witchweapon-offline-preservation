"""Hide legacy payment/login marks even if native UI reactivates their buttons.

The first-pass v8 patch only disabled parent GameObjects. Native shop code can
SetActive(true) on those buttons when a shop tab is drawn, so the still-active
child UISprites appeared. This incremental patch targets the reviewed v9 pair:
it also disables the visual children, makes their UISprites transparent, and
disables the button colliders. It never edits scripts or server settings.
"""

from __future__ import annotations

import hashlib
from typing import Dict

import UnityPy


NEW_SHOP = "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab"
OLD_SHOP = "assets/assetbundle/assets/resources/ui/prefab/shop/shoppanel.ab"
LOGIN = "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab"

EXPECTED_BUNDLES = {
    NEW_SHOP: "e2140c97c5ff2264833a3a1a8b1c079afb3f9e44e3430299c3c8d5744ed9c822",
    OLD_SHOP: "af30ce8d693af518b497c857a35cfbc4776feae190673162d59c79b370c11c14",
    LOGIN: "a1036a64f60a00e3a109d60059e61b56986dd3350c26a74bd1874ef8d064a6bc",
}

# (button GameObject, visible child GameObject, UISprite, BoxCollider, sprite name)
SHOP_BUTTONS = {
    NEW_SHOP: (
        (4414544176396467195, -5458806229509453345, 4785162760398344128,
         -5176159606530794353, "Pay-Alipay2"),
        (5225837975323778115, -6991741400238151912, -2058132610374674567,
         1495580409685156185, "Pay-WeChat2"),
    ),
    OLD_SHOP: (
        (8426299377041914631, -5200983169682029064, -4951600389366647159,
         -7796977137230123127, "Button_Recharge_Zhifubao_1"),
        (-1992504772179768129, 1885545049673727690, -1503706102528955308,
         5314524607087883683, "Button_Recharge_Weixin_1"),
    ),
}

# LoginMain: WechatContainner > WeixinRegistBtn > Background.
LOGIN_CONTAINER = -3886501974472910783
LOGIN_BUTTON = -1346711990232608672
LOGIN_ICON = -51297200415749579
LOGIN_COLLIDER = -4105127998256625413
LOGIN_VISUALS = (
    1645963511157964814,  # WechatContainner graphic
    3750197300626615100,  # WeixinRegistBtn graphic
    -3409878848356133240,  # icon_weixin UISprite
)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _objects(bundle):
    return {obj.path_id: obj for obj in bundle.objects}


def _component_ids(tree: dict) -> set[int]:
    return {entry["component"]["m_PathID"] for entry in tree["m_Component"]}


def _parent_id(objects: dict, game_object_id: int) -> int:
    game_object = objects[game_object_id]
    for component_id in _component_ids(game_object.read_typetree()):
        component = objects[component_id]
        if component.type.name != "Transform":
            continue
        father_id = component.read_typetree()["m_Father"]["m_PathID"]
        if not father_id:
            return 0
        return objects[father_id].read_typetree()["m_GameObject"]["m_PathID"]
    raise ValueError("Reviewed UI GameObject has no Transform")


def _hide_game_object(objects: dict, object_id: int, name: str, changed: set[int]):
    obj = objects[object_id]
    if obj.type.name != "GameObject":
        raise ValueError("Reviewed UI object type changed: " + name)
    tree = obj.read_typetree()
    if tree["m_Name"] != name or tree["m_IsActive"] is not True:
        raise ValueError("Reviewed visible icon changed: " + name)
    tree["m_IsActive"] = False
    obj.save_typetree(tree)
    changed.add(object_id)


def _hide_visual(objects: dict, object_id: int, sprite_name: str | None,
                 changed: set[int]):
    obj = objects[object_id]
    if obj.type.name != "MonoBehaviour":
        raise ValueError("Reviewed icon visual type changed")
    tree = obj.read_typetree()
    if sprite_name is not None and tree.get("mSpriteName") != sprite_name:
        raise ValueError("Reviewed icon sprite changed: " + sprite_name)
    if tree.get("m_Enabled") != 1 or tree.get("mColor", {}).get("a") != 1.0:
        raise ValueError("Reviewed icon visual state changed")
    tree["m_Enabled"] = 0
    tree["mColor"]["a"] = 0.0
    obj.save_typetree(tree)
    changed.add(object_id)


def _disable_collider(objects: dict, object_id: int, changed: set[int]):
    obj = objects[object_id]
    if obj.type.name != "BoxCollider":
        raise ValueError("Reviewed payment button collider type changed")
    tree = obj.read_typetree()
    if tree.get("m_Enabled") is not True:
        raise ValueError("Reviewed payment button collider state changed")
    tree["m_Enabled"] = False
    obj.save_typetree(tree)
    changed.add(object_id)


def patch_one(member: str, raw: bytes) -> bytes:
    if member not in EXPECTED_BUNDLES or digest(raw) != EXPECTED_BUNDLES[member]:
        raise ValueError("Unreviewed runtime payment bundle: " + member)
    bundle = UnityPy.load(raw)
    objects = _objects(bundle)
    before = {path_id: digest(obj.get_raw_data()) for path_id, obj in objects.items()}
    changed: set[int] = set()

    if member in SHOP_BUTTONS:
        for button_id, child_id, sprite_id, collider_id, sprite_name in SHOP_BUTTONS[member]:
            button = objects[button_id].read_typetree()
            if button["m_Name"] not in ("zhifubao", "weixin") or \
                    button["m_IsActive"] is not False or \
                    _parent_id(objects, child_id) != button_id or \
                    sprite_id not in _component_ids(objects[child_id].read_typetree()) or \
                    collider_id not in _component_ids(button):
                raise ValueError("Reviewed shop payment hierarchy changed")
            child_name = objects[child_id].read_typetree()["m_Name"]
            if not child_name.startswith("Sprite"):
                raise ValueError("Reviewed shop icon child changed")
            _hide_game_object(objects, child_id, child_name, changed)
            _hide_visual(objects, sprite_id, sprite_name, changed)
            _disable_collider(objects, collider_id, changed)
    else:
        container = objects[LOGIN_CONTAINER].read_typetree()
        button = objects[LOGIN_BUTTON].read_typetree()
        if container["m_Name"] != "WechatContainner" or \
                button["m_Name"] != "WeixinRegistBtn" or \
                container["m_IsActive"] is not False or \
                button["m_IsActive"] is not False or \
                _parent_id(objects, LOGIN_BUTTON) != LOGIN_CONTAINER or \
                _parent_id(objects, LOGIN_ICON) != LOGIN_BUTTON or \
                LOGIN_COLLIDER not in _component_ids(button):
            raise ValueError("Reviewed login WeChat hierarchy changed")
        _hide_game_object(objects, LOGIN_ICON, "Background", changed)
        for visual_id in LOGIN_VISUALS:
            expected_sprite = "icon_weixin" if visual_id == LOGIN_VISUALS[-1] else None
            _hide_visual(objects, visual_id, expected_sprite, changed)
        _disable_collider(objects, LOGIN_COLLIDER, changed)

    result = bundle.file.save(packer="original")
    after = UnityPy.load(result)
    actual = {obj.path_id for obj in after.objects
              if digest(obj.get_raw_data()) != before[obj.path_id]}
    if actual != changed:
        raise ValueError("Unrelated payment UI object changed")
    for obj in after.objects:
        if obj.path_id not in changed:
            continue
        tree = obj.read_typetree()
        if obj.type.name == "GameObject" and tree["m_IsActive"] is not False:
            raise ValueError("Icon child failed to round-trip")
        if obj.type.name == "MonoBehaviour" and \
                (tree["m_Enabled"] != 0 or tree["mColor"]["a"] != 0.0):
            raise ValueError("Hidden sprite failed to round-trip")
        if obj.type.name == "BoxCollider" and tree["m_Enabled"] is not False:
            raise ValueError("Disabled button collider failed to round-trip")
    return result


def patch_bundles(raw_bundles: Dict[str, bytes]) -> Dict[str, bytes]:
    if set(raw_bundles) != set(EXPECTED_BUNDLES):
        raise ValueError("All three original payment/login bundles are required")
    return {member: patch_one(member, raw) for member, raw in raw_bundles.items()}
