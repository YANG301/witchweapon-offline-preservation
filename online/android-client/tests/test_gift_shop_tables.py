"""Static round-trip checks for the composable Gift-tab asset patches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

from patch_feature_level_gates import _csv_tree
from patch_gift_shop_tables import (
    SHOPBIGSET_MEMBER, SHOPSTRUCTURE_MEMBER, SHOP_MEMBER, GOODS_MEMBER,
    gift_bundle_replacements,
    patch_shopbigset_bundle, patch_shopbigset_text,
    patch_shopstructure_bundle, patch_shopstructure_text,
    patch_shop_bundle, patch_shop_text,
    patch_goods_bundle, patch_goods_text,
)


SOURCE = CLIENT / "build/witchweapon-online-original-ui-draw-retry-all-week-v2.apk"
SOURCE_SHA = "b51a0768f3628dd7c2784f1f67501a195475a922329406e08de4b0bd8b3da68e"
ORIGINAL_TABLES = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
ORIGINAL_BUNDLES = Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel")


def different_rows(before, after):
    first, second = before.splitlines(keepends=True), after.splitlines(keepends=True)
    if len(first) != len(second):
        raise AssertionError("Asset row count changed")
    return [(old, new) for old, new in zip(first, second) if old != new]


class GiftShopTablesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest("Pinned draw-retry APK unavailable")
        if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA:
            raise AssertionError("Pinned draw-retry APK changed")
        with zipfile.ZipFile(SOURCE) as apk:
            cls.bundles = {member: apk.read(member) for member in
                           (SHOPSTRUCTURE_MEMBER, SHOPBIGSET_MEMBER, SHOP_MEMBER,
                            GOODS_MEMBER)}
        cls.original_bundles = {
            member: (ORIGINAL_BUNDLES / Path(member).name).read_bytes()
            for member in cls.bundles
        }

    def test_only_resource_row_changes(self):
        raw = self.bundles[SHOPSTRUCTURE_MEMBER]
        _, _, _, before, bom = _csv_tree(raw, "ShopStructure")
        expected, changed = patch_shopstructure_text(before)
        self.assertEqual(changed, 1)
        delta = different_rows(before, expected)
        self.assertEqual(len(delta), 1)
        self.assertEqual(delta[0][0].rstrip("\r\n"),
                         "Resource,25,cn,离线补给商店,14700000101|47000001")
        self.assertEqual(delta[0][1].rstrip("\r\n"),
                         "Resource,25,cn,离线补给商店,14700000101|47000001#9000|47000002|47000016")
        self.assertEqual(delta[0][0][len(delta[0][0].rstrip("\r\n")):],
                         delta[0][1][len(delta[0][1].rstrip("\r\n")):])
        patched = patch_shopstructure_bundle(raw,
            self.original_bundles[SHOPSTRUCTURE_MEMBER])
        _, _, _, actual, after_bom = _csv_tree(patched, "ShopStructure")
        self.assertEqual(actual, expected)
        self.assertEqual(bom, after_bom)
        self.assertEqual(patch_shopstructure_bundle(
            patched,self.original_bundles[SHOPSTRUCTURE_MEMBER]), patched)

    def test_only_bigset_row_changes_to_original_ids(self):
        raw = self.bundles[SHOPBIGSET_MEMBER]
        _, _, _, before, bom = _csv_tree(raw, "ShopBigSet")
        expected, changed = patch_shopbigset_text(before)
        self.assertEqual(changed, 2)
        delta = different_rows(before, expected)
        self.assertEqual(len(delta), 2)
        original = (ORIGINAL_TABLES / "shopbigset.txt").read_text(
            encoding="utf-8-sig").splitlines()
        for bigset_id,(before_row,after_row) in zip(("47000002","47000016"),delta):
            self.assertTrue(before_row.startswith(bigset_id+",25,4,"))
            original_row = [row for row in original if row.startswith(bigset_id+",25,")]
            self.assertEqual(len(original_row), 1)
            self.assertEqual(after_row.rstrip("\r\n"), original_row[0])
        patched = patch_shopbigset_bundle(raw,
            self.original_bundles[SHOPBIGSET_MEMBER])
        _, _, _, actual, after_bom = _csv_tree(patched, "ShopBigSet")
        self.assertEqual(actual, expected)
        self.assertEqual(bom, after_bom)
        self.assertEqual(patch_shopbigset_bundle(
            patched,self.original_bundles[SHOPBIGSET_MEMBER]), patched)

    def test_composable_replacements_and_index_ownership(self):
        replacements = gift_bundle_replacements(self.bundles.__getitem__,
                                                self.original_bundles.__getitem__)
        self.assertEqual(set(replacements), set(self.bundles))
        self.assertTrue(all(replacements[name] != self.bundles[name]
                            for name in self.bundles))
        self.assertFalse(any(name.endswith("m.assets_list.txt")
                             for name in replacements))

    def test_only_seven_gift_shops_change_to_free(self):
        raw = self.bundles[SHOP_MEMBER]
        source_raw = self.original_bundles[SHOP_MEMBER]
        _, _, _, before, bom = _csv_tree(raw,"Shop")
        _, _, _, reference, _ = _csv_tree(source_raw,"Shop")
        expected, changed = patch_shop_text(before,reference)
        delta = different_rows(before,expected)
        self.assertEqual(changed,7)
        self.assertEqual(len(delta),7)
        self.assertEqual({old.split(",",1)[0] for old,_ in delta},
                         {str(shop["id"]) for group in json.loads(
                             (CLIENT.parent / "legacy-server/resources/gift_shop_catalog.json")
                             .read_text(encoding="utf-8"))["sets"]
                          for shop in group["shops"]})
        patched=patch_shop_bundle(raw,source_raw)
        _, _, _, actual,after_bom=_csv_tree(patched,"Shop")
        self.assertEqual(actual,expected)
        self.assertEqual(after_bom,bom)
        self.assertEqual(patch_shop_bundle(patched,source_raw),patched)
        header=actual.splitlines()[0].split(",")
        catalog=json.loads((CLIENT.parent / "legacy-server/resources/gift_shop_catalog.json")
                           .read_text(encoding="utf-8"))
        rows={row.split(",",1)[0]:row.split(",") for row in actual.splitlines()}
        for group in catalog["sets"]:
            for shop in group["shops"]:
                fields=rows[str(shop["id"])]
                self.assertEqual(fields[header.index("price_type")],"50")
                for index,good in enumerate(shop["goods"],1):
                    self.assertEqual(fields[header.index("goods"+str(index))],str(good["id"]))
                    self.assertEqual(fields[header.index("price"+str(index))],"0")

    def test_only_five_retired_gift_timers_are_cleared(self):
        raw = self.bundles[GOODS_MEMBER]
        source_raw = self.original_bundles[GOODS_MEMBER]
        _, _, _, before, bom = _csv_tree(raw, "Goods")
        _, _, _, reference, _ = _csv_tree(source_raw, "Goods")
        expected, changed = patch_goods_text(before, reference)
        delta = different_rows(before, expected)
        self.assertEqual(changed, 5)
        self.assertEqual(len(delta), 5)
        self.assertEqual({old.split(",", 1)[0] for old, _ in delta},
                         {"45030639", "45030460", "45030461", "45030462",
                          "45820006"})
        header = before.splitlines()[0].split(",")
        time_column = header.index("time_id")
        for old, new in delta:
            old_fields = old.rstrip("\r\n").split(",")
            new_fields = new.rstrip("\r\n").split(",")
            self.assertTrue(old_fields[time_column])
            self.assertEqual(new_fields[time_column], "")
            old_fields[time_column] = ""
            self.assertEqual(old_fields, new_fields)
        patched = patch_goods_bundle(raw, source_raw)
        _, _, _, actual, after_bom = _csv_tree(patched, "Goods")
        self.assertEqual(actual, expected)
        self.assertEqual(after_bom, bom)
        self.assertEqual(patch_goods_bundle(patched, source_raw), patched)

    def test_unchanged_product_tables_match_original(self):
        catalog = json.loads((CLIENT.parent / "legacy-server/resources/gift_shop_catalog.json")
                             .read_text(encoding="utf-8"))
        ids = {
            "ShopSet": {str(group["id"]) for group in catalog["sets"]},
            "Shop": {str(shop["id"]) for group in catalog["sets"]
                     for shop in group["shops"]},
            "Goods": {str(good["id"]) for group in catalog["sets"]
                      for shop in group["shops"] for good in shop["goods"]},
            "MonthCard": {str(good["monthCardId"]) for group in catalog["sets"]
                          for shop in group["shops"] for good in shop["goods"]
                          if good["kind"] == "monthCard"},
        }
        with zipfile.ZipFile(SOURCE) as apk:
            for name, targets in ids.items():
                member = "assets/assetbundle/config/clientexel/" + name.lower() + ".ab"
                actual = _csv_tree(apk.read(member), name)[3].splitlines()
                reference = (ORIGINAL_TABLES / (name.lower()+".txt")).read_text(
                    encoding="utf-8-sig").splitlines()
                rows = lambda lines: {row.split(",", 1)[0]: row for row in lines
                                      if row.split(",", 1)[0] in targets}
                self.assertEqual(rows(actual), rows(reference), name)
                self.assertEqual(set(rows(actual)), targets, name)

    def test_unexpected_rows_are_rejected(self):
        structure = _csv_tree(self.bundles[SHOPSTRUCTURE_MEMBER],
                              "ShopStructure")[3]
        bigset = _csv_tree(self.bundles[SHOPBIGSET_MEMBER], "ShopBigSet")[3]
        shop = _csv_tree(self.bundles[SHOP_MEMBER], "Shop")[3]
        goods = _csv_tree(self.bundles[GOODS_MEMBER], "Goods")[3]
        with self.assertRaisesRegex(ValueError, "Resource entry"):
            patch_shopstructure_text(structure.replace(
                "Resource,25,cn,离线补给商店,",
                "Resource,25,cn,意外内容,", 1))
        with self.assertRaisesRegex(ValueError, "BigSet contents"):
            patch_shopbigset_text(bigset.replace(
                "47000002,25,4,14700000201,14700000202,44000001,",
                "47000002,25,4,14700000201,14700000202,44000022,", 1))
        original_shop=_csv_tree(self.original_bundles[SHOP_MEMBER],"Shop")[3]
        with self.assertRaisesRegex(ValueError, "Gift Shop product slot"):
            patch_shop_text(shop.replace("4502990008,02,1,100,0,,99",
                                         "4502990008,02,1,100,0,,50",1)
                            .replace("45820001,3000,0","45820001,42,0",1),
                            original_shop)
        original_goods = _csv_tree(self.original_bundles[GOODS_MEMBER],
                                   "Goods")[3]
        with self.assertRaisesRegex(ValueError, "retired Gift timer"):
            patch_goods_text(goods.replace(",1010130,", ",1234567,", 1),
                             original_goods)


if __name__ == "__main__":
    unittest.main()
