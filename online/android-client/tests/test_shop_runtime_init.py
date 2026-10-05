"""Verify the opt-in local shop hook changes only the active init TextAsset."""

from __future__ import annotations

import sys
from pathlib import Path
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

import patch_shop_runtime_init as runtime  # noqa: E402
from build_online_apk import patch_index  # noqa: E402


SOURCE = CLIENT / "build" / "witchweapon-online-local-staging-exchange-shared-v13.apk"


class ShopRuntimeInitTest(unittest.TestCase):
    def test_opt_in_changes_only_init_and_indexes_it(self):
        with zipfile.ZipFile(SOURCE) as archive:
            original = archive.read(runtime.MEMBER)
            index = archive.read("assets/m.assets_list.txt")
        self.assertIs(runtime.patch_bundle(original), original)
        patched = runtime.patch_bundle(original, enabled=True)
        self.assertNotEqual(patched, original)
        self.assertEqual(runtime.patch_bundle(patched, enabled=True), patched)

        old = UnityPy.load(original)
        new = UnityPy.load(patched)
        altered = [(a, b) for a, b in zip(old.objects, new.objects)
                   if a.get_raw_data() != b.get_raw_data()]
        self.assertEqual(len(altered), 1)
        self.assertEqual(altered[0][1].read_typetree().get("m_Name"), "init.lua")
        source = altered[0][1].read_typetree()["m_Script"]
        for required in ("LOCAL_SHOP_PRESENTATION", "Currency_Icon_RMB",
                         "currentBigSetID", "ShopItemInfoView", "Mid/p1Icon",
                         "Center/Table", "goldIcon", "sellGold", "resouceDesc",
                         "FreshView", "47000020",
                         "['47000002']", "['47000016']"):
            self.assertIn(required, source)
        self.assertNotIn("detail_debug", source)
        self.assertNotIn("recharge_detail", source)
        self.assertNotIn("star_refresh", source)
        # The original panel synchronously uses Shop.Number to hide or show
        # its shared counter; a later Lua override caused transition flashes
        # and could hide the guild's valid 4/4 counter.
        self.assertNotIn("Center/buyWidget", source)
        updated_index = patch_index(index, {"/lua/lua.ab": patched})
        self.assertNotEqual(updated_index, index)
        self.assertIn(("=/lua/lua.ab:" + str(len(patched))).encode("ascii"),
                      updated_index)


if __name__ == "__main__":
    unittest.main()
