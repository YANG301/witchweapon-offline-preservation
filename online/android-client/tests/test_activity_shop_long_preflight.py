import hashlib
import sys
import unittest
import zipfile
from pathlib import Path

import UnityPy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from patch_activity_shop_long_preflight import (
    ASSET_NAME, MEMBER, OLD_CHECK, NEW_CHECK, patch_bundle, patch_script,
)

V10 = (
    HERE.parent / "build" / "witchweapon-online-activity-payment-v10-test.apk",
    HERE.parent / "build" / "witchweapon-online-local-staging-activity-payment-v10.apk",
)


def asset_script(raw):
    items = [obj.read_typetree()["m_Script"] for obj in UnityPy.load(raw).objects
             if obj.type.name == "TextAsset"
             and obj.read_typetree().get("m_Name") == ASSET_NAME]
    if len(items) != 1:
        raise AssertionError("Original activity script missing or duplicated")
    return items[0]


class ActivityShopLongPreflightTest(unittest.TestCase):
    def test_only_shop_time_type_guard_changes(self):
        with zipfile.ZipFile(V10[1]) as apk:
            before = asset_script(apk.read(MEMBER))
        after = patch_script(before)
        self.assertEqual(after, before.replace(OLD_CHECK, NEW_CHECK, 1))
        self.assertIn("bigShopsID = 47000011", after)
        self.assertIn("bigShopsID = 47000012", after)
        with self.assertRaises(ValueError):
            patch_script(after)

    def test_production_and_staging_bundle_match(self):
        digests = []
        for path in V10:
            with zipfile.ZipFile(path) as apk:
                result = patch_bundle(apk.read(MEMBER))
            self.assertIn(NEW_CHECK, asset_script(result))
            digests.append(hashlib.sha256(result).hexdigest())
        self.assertEqual(digests[0], digests[1])


if __name__ == "__main__":
    unittest.main()
