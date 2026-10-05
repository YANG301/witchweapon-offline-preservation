"""Audit staged ¥0 Lua assets and prove they are not bound to the CN prefab.

This test is a serialization check, not a runtime UI acceptance test.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
from patch_feature_level_gates import _csv_tree
from patch_hide_gift_duplicate_diamond import patch as hide_duplicate
from patch_resource_shop_tables import MEMBERS, replacements as resource_replacements
from patch_virtual_yuan_display import MEMBER, patch as show_yuan


SOURCE = CLIENT / "build/witchweapon-online-local-staging-exchange-shared-v13.apk"
ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel")
RMB_ATLAS = "assets/assetbundle/assets/resources/ui/formalatlas/newresbar/newresbar.ab"
SHOP_PREFAB = "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab"


def raw_objects(data):
    return {obj.path_id: hashlib.sha256(obj.get_raw_data()).hexdigest()
            for obj in UnityPy.load(data).objects}


class VirtualYuanDisplayTest(unittest.TestCase):
    def test_staged_lua_is_unbound_and_zero_cost_route(self):
        if not SOURCE.is_file():
            self.skipTest("Pinned local staging APK missing")
        with zipfile.ZipFile(SOURCE) as apk:
            original_lua = apk.read(MEMBER)
            atlas = UnityPy.load(apk.read(RMB_ATLAS))
            shop_prefab = UnityPy.load(apk.read(SHOP_PREFAB))
            changed_tables = resource_replacements(
                apk.read,
                lambda member: (ORIGINAL / Path(member).name).read_bytes())
        atlas_sprites = {sprite["name"] for obj in atlas.objects
                         if obj.type.name == "MonoBehaviour"
                         for sprite in obj.read_typetree().get("mSprites", [])}
        self.assertIn("Currency_Icon_RMB", atlas_sprites)
        behaviours = [obj.read_typetree() for obj in shop_prefab.objects
                      if obj.type.name == "MonoBehaviour"]
        self.assertGreater(len(behaviours), 300)
        self.assertTrue(all("m_luaPath" not in tree and "m_Type" not in tree
                            for tree in behaviours))
        self.assertNotIn("price1", {obj.read_typetree().get("m_Name")
                                   for obj in shop_prefab.objects
                                   if obj.type.name == "GameObject"})
        after_yuan = show_yuan(original_lua)
        after_both = hide_duplicate(after_yuan)
        self.assertEqual(show_yuan(after_yuan), after_yuan)
        self.assertEqual(hide_duplicate(after_both), after_both)
        old_objects, new_objects = raw_objects(original_lua), raw_objects(after_both)
        self.assertEqual(set(old_objects), set(new_objects))
        self.assertEqual(len({key for key, value in old_objects.items()
                              if new_objects[key] != value}), 2)

        scripts = {tree["m_Name"]: tree["m_Script"]
                   for obj in UnityPy.load(after_both).objects
                   if obj.type.name == "TextAsset"
                   for tree in [obj.read_typetree()]
                   if tree.get("m_Name") in
                   ("NewShopPanelPatch.lua", "DiamondScrollViewPatch.lua")}
        self.assertEqual(set(scripts),
                         {"NewShopPanelPatch.lua", "DiamondScrollViewPatch.lua"})
        self.assertIn("icon.spriteName = 'Currency_Icon_RMB'",
                      scripts["NewShopPanelPatch.lua"])
        self.assertIn("icon.gameObject:SetActive(true)",
                      scripts["NewShopPanelPatch.lua"])
        self.assertIn("label.text = '0'", scripts["NewShopPanelPatch.lua"])
        self.assertNotIn("label.text = '¥0'", scripts["NewShopPanelPatch.lua"])
        self.assertIn("setID == '47000002' or setID == '47000016'",
                      scripts["DiamondScrollViewPatch.lua"])
        for script in scripts.values():
            self.assertNotIn("BuyShop(", script)
            self.assertNotIn("PAY_TYPE_", script)
            self.assertNotIn("SetShopPrice(", script)

        text = _csv_tree(changed_tables[MEMBERS["Shop"]], "Shop")[3]
        rows = [line.split(",") for line in text.splitlines()]
        columns = {name: index for index, name in enumerate(rows[0])}
        shops = {row[0]: row for row in rows[1:]}
        for shop_id in ("4502990011", "4502990006", "4502990002",
                        "4502990008", "4502990003"):
            row = shops[shop_id]
            self.assertEqual(row[columns["price_type"]], "50")
            for slot in range(1, 7):
                if row[columns["goods" + str(slot)]]:
                    self.assertEqual(row[columns["price" + str(slot)]], "0")


if __name__ == "__main__":
    unittest.main()
