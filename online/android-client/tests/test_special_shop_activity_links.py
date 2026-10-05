import hashlib
import sys
import unittest
import zipfile
from pathlib import Path

import UnityPy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from patch_special_shop_activity_links import (
    ASSET_NAME, MEMBER, patch_bundle, patch_script,
)

BUILD = HERE.parent / "build"
V9 = (
    BUILD / "witchweapon-online-exchange-levels-v9-test.apk",
    BUILD / "witchweapon-online-local-staging-exchange-levels-v9.apk",
)


def script(raw):
    assets = [obj.read_typetree()["m_Script"] for obj in UnityPy.load(raw).objects
              if obj.type.name == "TextAsset"
              and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(assets) != 1:
        raise AssertionError("UIActivities.lua missing or duplicated")
    return assets[0]


class SpecialShopActivityLinksTest(unittest.TestCase):
    def test_navigation_matches_restored_original_bigsets(self):
        with zipfile.ZipFile(V9[1]) as apk:
            before = script(apk.read(MEMBER))
        after = patch_script(before)
        self.assertEqual(after.count("shopsID = 44000070"), 2)
        self.assertEqual(after.count("bigShopsID = 47000011"), 1)
        self.assertEqual(after.count("shopsID = 44000012"), 2)
        self.assertEqual(after.count("bigShopsID = 47000012"), 1)
        self.assertNotIn("shopsID = 44000014", after)
        self.assertIn("UIActivitiesModel.GoOneShopPageByID( bigShopsID", after)
        self.assertIn("online7DailyResetSeconds()", after)
        with self.assertRaises(ValueError):
            patch_script(after)

    def test_both_v9_variants_receive_identical_single_asset_patch(self):
        outputs = []
        for path in V9:
            with zipfile.ZipFile(path) as apk:
                patched = patch_bundle(apk.read(MEMBER))
            self.assertIn("shopIDs = {44000001, 44000070, 44000012}", script(patched))
            outputs.append(hashlib.sha256(patched).hexdigest())
        self.assertEqual(len(set(outputs)), 1)


if __name__ == "__main__":
    unittest.main()
