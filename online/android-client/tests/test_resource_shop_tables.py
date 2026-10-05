"""Round-trip the free Resource/Sundry/Recharge and Gift-table changes."""

import pathlib
import sys
import unittest
import zipfile


CLIENT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
from patch_feature_level_gates import _csv_tree
from patch_resource_shop_tables import (MEMBERS, RECHARGE_GOODS,
                                        RECHARGE_AMOUNTS, recharge_desc_id,
                                        replacements)


SOURCE = CLIENT / "build/witchweapon-online-local-staging-exchange-shared-v13.apk"
ORIGINAL = pathlib.Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel")


class ResourceShopTablesTest(unittest.TestCase):
    def test_composed_bundles(self):
        if not SOURCE.is_file():
            self.skipTest("v13 local staging APK missing")
        with zipfile.ZipFile(SOURCE) as apk:
            changed = replacements(apk.read,
                                   lambda member: (ORIGINAL / pathlib.Path(member).name).read_bytes())
        self.assertEqual(set(changed), set(MEMBERS.values()))
        texts = {name: _csv_tree(changed[member], name)[3]
                 for name, member in MEMBERS.items()}
        self.assertIn("Resource,25,cn,资源商店,14700000301|47000003#"
                      "14700000401|47000004#14700000101|47000001#"
                      "9000|47000002|47000016", texts["ShopStructure"])
        self.assertNotIn("Resource,25,cn,离线补给商店,", texts["ShopStructure"])
        self.assertIn("47000001,25,1,14700000101,14700000102,44000007,",
                      texts["ShopBigSet"])
        self.assertIn("47000003,25,3,14700000301,14700000302,44000028,44000009,",
                      texts["ShopBigSet"])
        self.assertIn("47000004,25,3,14700000401,14700000402,44000247,",
                      texts["ShopBigSet"])
        self.assertIn("47000002,25,2,14700000201,14700000202,"
                      "44000025,44000088,44000006,", texts["ShopBigSet"])
        self.assertIn("14700000101\t充值\t加值\tチャージ\t충전\tRecharge\t0\t15",
                      texts["Dictionary"])
        self.assertIn("14700000102\t钻晶商店\t鑽晶商店\tダイヤショップ\t다이아상점\tGem Shop\t0\t15",
                      texts["Dictionary"])
        self.assertNotIn("14700000101\t免费补给", texts["Dictionary"])
        shop_rows = {row.split(",", 1)[0]: row.split(",")
                     for row in texts["Shop"].splitlines()}
        fields = texts["Shop"].splitlines()[0].split(",")
        recharge = shop_rows["4502990003"]
        self.assertEqual(recharge[fields.index("price_type")], "50")
        for slot in range(1, 7):
            self.assertEqual(recharge[fields.index("price" + str(slot))], "0")
        uniform = shop_rows["4502990002"]
        self.assertEqual([uniform[fields.index("goods" + str(i))] for i in (1, 2, 3)],
                         ["45030620", "45030621", ""])
        set_row = next(row.split(",") for row in texts["ShopSet"].splitlines()
                       if row.startswith("44000006,"))
        set_fields = texts["ShopSet"].splitlines()[0].split(",")
        self.assertEqual(set_row[set_fields.index("shop2")], "")
        goods_fields = texts["Goods"].splitlines()[0].split(",")
        goods_rows = {row.split(",", 1)[0]: row.split(",")
                      for row in texts["Goods"].splitlines()}
        dictionary_rows = {row.split("\t", 1)[0]: row.split("\t")
                           for row in texts["Dictionary"].splitlines()}
        for good_id, amount in zip(RECHARGE_GOODS, RECHARGE_AMOUNTS):
            row = goods_rows[good_id]
            description = recharge_desc_id(good_id)
            self.assertEqual(row[goods_fields.index("good_desc")], description)
            self.assertNotEqual(description, row[goods_fields.index("name")])
            self.assertEqual(dictionary_rows[description][1],
                             f"领取后获得{amount}钻晶。")
        for good_id in range(45030268, 45030273):
            self.assertEqual(goods_rows[str(good_id)][goods_fields.index("time_id")], "")
        second = replacements(changed.__getitem__,
                              lambda member: (ORIGINAL / pathlib.Path(member).name).read_bytes())
        self.assertEqual(second, {})


if __name__ == "__main__":
    unittest.main()
