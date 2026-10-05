import csv
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from patch_exchange_shop_tables import (
    patch_shopstructure_text, patch_shopbigset_text,
    patch_shop_level_text, patch_shopstructure_bundle, patch_shopbigset_bundle,
    patch_shop_level_bundle,
    exchange_bundle_replacements,
)
from patch_gift_shop_tables import gift_bundle_replacements

SOURCE = Path(r"D:\Project\魔女兵器工程恢复")
OFFLINE = SOURCE / "单机版" / "Android工程" / "assets" / "assetbundle" / "config" / "clientexel"
ORIGINAL = SOURCE / "原版" / "Android工程" / "assets" / "assetbundle" / "config" / "clientexel"
OFFLINE_CSV = SOURCE / "单机版" / "可读脚本与配置" / "配置" / "clientexel"
ORIGINAL_CSV = SOURCE / "原版" / "可读脚本与配置" / "配置" / "clientexel"


class OriginalExchangeShopPatchTest(unittest.TestCase):
    def test_underlying_original_goods_unchanged(self):
        generated = json.loads((HERE.parent.parent / "legacy-server" / "resources" /
                                "exchange_shop_catalog.json").read_text(encoding="utf-8"))
        ids_by_table = {
            "shopset.txt": {str(entry["id"]) for entry in generated["sets"]},
            "shop.txt": {str(shop["id"]) for entry in generated["sets"]
                         for shop in entry["shops"]},
            "goods.txt": {str(good["id"]) for entry in generated["sets"]
                          for shop in entry["shops"] for good in shop["goods"]},
        }
        self.assertEqual(tuple(len(ids_by_table[name]) for name in
                               ("shopset.txt", "shop.txt", "goods.txt")),
                         (23, 90, 482))
        for name, ids in ids_by_table.items():
            def table(base):
                with (base / name).open(encoding="utf-8-sig", newline="") as f:
                    return {row["ID"]: row for row in list(csv.DictReader(f))[2:]
                            if row.get("ID")}
            offline, original = table(OFFLINE_CSV), table(ORIGINAL_CSV)
            for key in ids:
                self.assertEqual(offline[key], original[key])

    def test_text_idempotent_and_isolated(self):
        for name, patch, count in (
                ("shopstructure", patch_shopstructure_text, 3),
                ("shopbigset", patch_shopbigset_text, 9),
                ("shop", patch_shop_level_text, 19)):
            before = (OFFLINE_CSV / f"{name}.txt").read_text(encoding="utf-8-sig")
            reference = (ORIGINAL_CSV / f"{name}.txt").read_text(encoding="utf-8-sig")
            after, changed = patch(before, reference)
            self.assertEqual(changed, count)
            self.assertEqual(patch(after, reference), (after, 0))
            self.assertEqual(len(before.splitlines()), len(after.splitlines()))
            if name == "shopstructure":
                self.assertIn("Exchange,25,cn,兑换商店,", after)
                self.assertIn("EverydaySecret,25,cn,每日神秘商店,9005|47000011", after)
                self.assertIn("WeekendSecret,25,cn,周末神秘商店（小飞艇）", after)
                exchange = next(line for line in after.splitlines()
                                if line.startswith("Exchange,25,cn,"))
                self.assertIn("47000024", exchange)
                self.assertIn("47000005", exchange)
                daily = next(line for line in after.splitlines()
                             if line.startswith("EverydaySecret,25,cn,"))
                self.assertIn("47000025", daily)
            if name == "shop":
                original_rows = {row.split(",")[0]: row.split(",")
                                 for row in reference.splitlines()}
                patched_rows = {row.split(",")[0]: row.split(",")
                                for row in after.splitlines()}
                for shop_id in ("4501060008", "4501010028", "4501500018"):
                    self.assertEqual(patched_rows[shop_id][2:4],
                                     ["92", "100"] if shop_id == "4501060008" else ["1", "100"])
                    self.assertEqual(patched_rows[shop_id][:2] + patched_rows[shop_id][4:],
                                     original_rows[shop_id][:2] + original_rows[shop_id][4:])
                for shop_id in ("4501070010", "4501070011", "4501070013"):
                    self.assertEqual(patched_rows[shop_id][2:4], ["61", "100"])

    def test_bundle_round_trip(self):
        for name, patch in (
                ("shopstructure", patch_shopstructure_bundle),
                ("shopbigset", patch_shopbigset_bundle),
                ("shop", patch_shop_level_bundle)):
            source = (OFFLINE / f"{name}.ab").read_bytes()
            reference = (ORIGINAL / f"{name}.ab").read_bytes()
            after = patch(source, reference)
            self.assertNotEqual(source, after)
            self.assertEqual(patch(after, reference), after)

    def test_composition_after_gift_patch(self):
        current = lambda member: (OFFLINE / Path(member).name).read_bytes()
        original = lambda member: (ORIGINAL / Path(member).name).read_bytes()
        gifts = gift_bundle_replacements(current, original)
        exchange = exchange_bundle_replacements(
            lambda member: gifts.get(member, current(member)), original)
        self.assertEqual(len(exchange), 3)
        self.assertTrue(all(name in gifts for name in exchange))
        self.assertTrue(all(exchange[name] != gifts[name] for name in exchange))


if __name__ == "__main__":
    unittest.main()
