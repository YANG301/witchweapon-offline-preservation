"""Validate the composed exchange counter patch against the local v13 APK."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_exchange_counter_ui as counter  # noqa: E402
import patch_virtual_yuan_display as yuan  # noqa: E402
from build_online_apk import patch_index  # noqa: E402


APK = CLIENT / "build" / "witchweapon-online-local-staging-exchange-shared-v13.apk"
APK_SHA256 = "ceaf9eadc117116386ff439b583a92afc088ff58cc1790f79b49a3f8ac92fe3b"
PREFAB = "assets/assetbundle/assets/resources/ui/prefab/shop/newshoppanel.ab"
ITEM_PREFAB = "assets/assetbundle/assets/resources/ui/prefab/common/uishopitemspriteexobj.ab"
INDEX = "assets/m.assets_list.txt"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class ExchangeCounterPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not APK.is_file() or file_sha256(APK) != APK_SHA256:
            raise unittest.SkipTest("Reviewed local v13 APK missing or changed")
        with zipfile.ZipFile(APK) as archive:
            cls.original = archive.read(counter.MEMBER)
            cls.index = archive.read(INDEX)
            cls.prefab = archive.read(PREFAB)
            cls.item_prefab = archive.read(ITEM_PREFAB)

    def test_virtual_yuan_then_counter_composes_without_replacing_other_lua(self):
        first = yuan.patch(self.original)
        self.assertEqual(sha256(first), counter.EXPECTED_BUNDLE_SHA256)
        final = counter.patch_bundle(first)
        self.assertEqual(sha256(final),
                         "19ce17daf0ed3bf209ee562185f216dbd627add89aa862ac9ddb52f080bcfd95")
        old = {o.path_id: sha256(o.get_raw_data()) for o in UnityPy.load(first).objects}
        changed = {o.path_id for o in UnityPy.load(final).objects
                   if sha256(o.get_raw_data()) != old[o.path_id]}
        self.assertEqual(len(changed), 1)
        script = next(o.read_typetree()["m_Script"] for o in UnityPy.load(final).objects
                      if o.type.name == "TextAsset" and
                      o.read_typetree().get("m_Name") == counter.ASSET_NAME)
        self.assertIn("virtualYuanSets", script)
        self.assertIn("showVirtualPrices()", script)
        self.assertIn("label.text = '¥0'", script)
        self.assertIn("if setID == '47000006' then limit = 4 end", script)
        self.assertIn("if setID == '47000023' then limit = 6 end", script)
        self.assertIn("setID == '47000008'", script)
        self.assertIn("transform:GetChild(index):Find('Mid/Num')", script)
        self.assertNotIn("ShopItemInfo.", script)
        updated_index = patch_index(self.index, {"/lua/lua_projx_patch.ab": final})
        self.assertNotEqual(updated_index, self.index)
        expected_entry = (hashlib.md5(final).hexdigest() +
                          "=/lua/lua_projx_patch.ab:" + str(len(final))).encode("ascii")
        self.assertIn(expected_entry, updated_index)

    def test_original_ui_binding_and_store_ids(self):
        objects = {o.path_id: o for o in UnityPy.load(self.prefab).objects}
        panel = next(o.read_typetree() for o in objects.values()
                     if o.type.name == "MonoBehaviour" and
                     "buyWidget" in o.read_typetree())
        buy_transform = objects[panel["buyWidget"]["m_PathID"]].read_typetree()
        buy_go = objects[buy_transform["m_GameObject"]["m_PathID"]].read_typetree()
        self.assertEqual(buy_go["m_Name"], "buyWidget")
        count = objects[panel["buyCount"]["m_PathID"]].read_typetree()
        self.assertEqual(count["mText"], "6/6")
        original = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
        rows = (original / "shopbigset.txt").read_text(encoding="utf-8", errors="replace")
        self.assertIn("47000006,25,4,14700000601,14700000602,44000071", rows)
        self.assertIn("47000023,25,4,14700002301,14700002302,44000068", rows)
        self.assertIn("47000024,0,4,14700002401,14700002402,44000016", rows)
        self.assertIn("47000005,0,4,14700000501,14700000502,44000002", rows)
        self.assertIn("47000008,25,4,14700000801,14700000802,44000015", rows)

    def test_wish_stock_node_is_on_shop_card_only(self):
        objects = {o.path_id: o for o in UnityPy.load(self.item_prefab).objects}
        transforms = {o.path_id: o.read_typetree() for o in objects.values()
                      if o.type.name in ("Transform", "RectTransform")}
        names = {path_id: objects[node["m_GameObject"]["m_PathID"]]
                 .read_typetree()["m_Name"] for path_id, node in transforms.items()}
        num_nodes = [path_id for path_id, name in names.items() if name == "Num"]
        self.assertEqual(len(num_nodes), 1)
        num_parent = transforms[num_nodes[0]]["m_Father"]["m_PathID"]
        self.assertEqual(names[num_parent], "Mid")
        root_nodes = [path_id for path_id, name in names.items()
                      if name == "UIShopItemSpriteExObj"]
        self.assertEqual(len(root_nodes), 1)
        self.assertEqual(transforms[num_parent]["m_Father"]["m_PathID"],
                         root_nodes[0])

    def test_unreviewed_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            counter.patch_bundle(self.original)


if __name__ == "__main__":
    unittest.main()
