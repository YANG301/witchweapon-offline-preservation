"""Validate the composed Resource-page hot update against the complete v100 APK."""
from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_resource_shop_v23 as patch  # noqa: E402
from patch_feature_level_gates import _csv_tree  # noqa: E402
from build_online_apk import patch_index  # noqa: E402

APK = CLIENT / "build/witchweapon-welfare-return-v100-test.apk"
APK_SHA = "7d88a0a08f6ba4aa829b2f6473a7e9a37ae101e99419016e4df36bc79caaac67"


class ResourceShopV23Test(unittest.TestCase):
    def test_original_seven_goods_and_navigation_bundle(self):
        with APK.open("rb") as stream:
            self.assertEqual(hashlib.file_digest(stream, "sha256").hexdigest(), APK_SHA)
        with zipfile.ZipFile(APK) as source:
            output = patch.replacements(source.read)
            old_index = source.read("assets/m.assets_list.txt")
        self.assertEqual(set(output), set(patch.MEMBERS.values()))

        bigset = _csv_tree(output[patch.MEMBERS["ShopBigSet"]], "ShopBigSet")[3]
        row = next(line.split(",") for line in bigset.splitlines()
                   if line.startswith("47000003,25,"))
        self.assertEqual(row[5:15], ["44000009"] + [""] * 9)

        shop = _csv_tree(output[patch.MEMBERS["Shop"]], "Shop")[3]
        fields = shop.splitlines()[0].split(",")
        goods = next(line.split(",") for line in shop.splitlines()
                     if line.startswith("4502500001,"))
        identifiers = [goods[fields.index("goods" + str(index))]
                       for index in range(1, 9)]
        self.assertEqual(identifiers, ["45030125", "45030124", "45130009",
            "45130010", "45130011", "45030202", "45030267", ""])
        self.assertEqual(goods[fields.index("price_type")], "50")

        lua = UnityPy.load(output[patch.MEMBERS["Lua"]])
        scripts = [obj.read_typetree()["m_Script"] for obj in lua.objects
                   if obj.type.name == "TextAsset" and
                   obj.read_typetree().get("m_Name") == "init.lua"]
        self.assertEqual(len(scripts), 1)
        self.assertNotIn("for _,name in ipairs({'FreshView'}) do", scripts[0])
        self.assertIn("setID == '47000004'", scripts[0])
        self.assertIn("'btnList/BottomLeft'", scripts[0])
        self.assertIn("'DefultShop/leftBottom'", scripts[0])

        prefab = UnityPy.load(output[patch.MEMBERS["Prefab"]])
        fresh = [obj.read_typetree() for obj in prefab.objects
                 if obj.path_id == patch.FRESH_GO]
        self.assertEqual(len(fresh), 1)
        self.assertFalse(fresh[0]["m_IsActive"])

        assets = {member.removeprefix("assets/assetbundle"): raw
                  for member, raw in output.items()}
        index = patch_index(old_index, assets)
        self.assertNotEqual(index, old_index)
        for member, raw in output.items():
            entry = (hashlib.md5(raw).hexdigest() + "=" +
                     member.removeprefix("assets/assetbundle") + ":" +
                     str(len(raw))).encode("ascii")
            self.assertIn(entry, index)


if __name__ == "__main__":
    unittest.main()

