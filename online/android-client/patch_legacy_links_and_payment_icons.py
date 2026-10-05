"""Return reviewed game asset bundles with the original UI links/icons adjusted.

This patches no executable code and does not build, sign, install, or deploy an
APK. The caller must update m.assets_list.txt for every replaced bundle.
"""

from __future__ import annotations

import hashlib
from typing import Dict

import UnityPy


UI = "assets/assetbundle/lua/lua_projx_ui.ab"
LOGIN = "assets/assetbundle/assets/resources/ui/prefab/login/loginmain.ab"
SHOP = "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab"
WIKI = "https://witchweapon.wiki"
EXPECTED_BUNDLES = {
    UI: "35344944880334cbfbd23eda3573dd5c8ce5d317537c6f4bffbca1b3d15b114b",
    LOGIN: "7b4670103035dfe86b9254f267b2fb9519182647d02e7f6a56be25f9db9b7c78",
    SHOP: "78b42f9d095d956fdca40a965e470ae29972ef4316d39400edd7a3a782add21a",
}
EXPECTED_OBJECTS = {
    UI: {"UIActivities.lua": "ffa709331a3ed0be3a43af59d87e71473012c209bed2869c6fd8711ec5809f08"},
    LOGIN: {
        "WechatContainner": "94e5ea4ae727e04b9ea6e87a35f13d537f103be5489836e36b3e8f005642ea12",
        "WeixinRegistBtn": "141ece7c1fe530a7a06143b9d6742f45cdb41d79998581bdbfa5b8659384a0da",
    },
    SHOP: {
        "zhifubao": "08b0ec536c7cc8a087e78ac300c625b36310b9813cc96c067e3cbbf4998a5188",
        "weixin": "c4dccebd6c68e5c44531bdb81cbf2f5a297795814fdc6b8239cfbabc05079e13",
    },
}
WIKI_ANCHOR = ("\t\tURL_Wiki = ManagerCsv.GetInstance():GetClientPlatformConstant('URL_Wiki')\n"
               "\tend\n\n\n\tlocal BottomModule = this.page.transform:Find('BottomModule')")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch_one(member: str, raw: bytes) -> bytes:
    if member not in EXPECTED_BUNDLES or digest(raw) != EXPECTED_BUNDLES[member]:
        raise ValueError("Unreviewed link/payment icon bundle: " + member)
    bundle = UnityPy.load(raw)
    before = {obj.path_id: digest(obj.get_raw_data()) for obj in bundle.objects}
    found = {}
    expected = EXPECTED_OBJECTS[member]
    for obj in bundle.objects:
        kind = "TextAsset" if member == UI else "GameObject"
        if obj.type.name != kind:
            continue
        tree = obj.read_typetree()
        name = tree.get("m_Name")
        if name not in expected:
            continue
        if name in found or before[obj.path_id] != expected[name]:
            raise ValueError("Unreviewed or duplicate UI object: " + str(name))
        found[name] = obj.path_id
        if member == UI:
            old = tree.get("m_Script")
            if not isinstance(old, str) or old.count(WIKI_ANCHOR) != 1 or WIKI in old:
                raise ValueError("Original Wiki Lua entry changed")
            if old.count("AwardUtils.OpenWebURLNotie(URL_Wiki,false,nil)") != 1:
                raise ValueError("Original Wiki click handler changed")
            tree["m_Script"] = old.replace(WIKI_ANCHOR,
                WIKI_ANCHOR.replace("\tend\n\n\n\tlocal BottomModule",
                    "\tend\n\t-- Online preservation Wiki; keep the original Wiki button and click flow.\n"
                    "\tURL_Wiki = '" + WIKI + "'\n\n\n\tlocal BottomModule"), 1)
        else:
            if tree.get("m_IsActive") is not True:
                raise ValueError("Original payment/login icon is not active: " + str(name))
            tree["m_IsActive"] = False
        obj.save_typetree(tree)
    if set(found) != set(expected):
        raise ValueError("Original Wiki/payment/login UI object missing")

    result = bundle.file.save(packer="original")
    after = UnityPy.load(result)
    changed = {obj.path_id for obj in after.objects
               if digest(obj.get_raw_data()) != before[obj.path_id]}
    if changed != set(found.values()):
        raise ValueError("Unrelated UI object changed")
    for obj in after.objects:
        if obj.path_id not in found.values():
            continue
        tree = obj.read_typetree()
        if member == UI:
            if tree["m_Script"].count("URL_Wiki = '" + WIKI + "'") != 1:
                raise ValueError("Wiki URL failed to round-trip")
        elif tree["m_IsActive"] is not False:
            raise ValueError("Hidden icon failed to round-trip")
    return result


def patch_bundles(raw_bundles: Dict[str, bytes]) -> Dict[str, bytes]:
    if set(raw_bundles) != set(EXPECTED_BUNDLES):
        raise ValueError("All three original UI bundles are required")
    return {name: patch_one(name, raw) for name, raw in raw_bundles.items()}
