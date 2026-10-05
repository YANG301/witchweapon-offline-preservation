"""Guard the original shop counter against the inherited timer override."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

from build_shop_runtime_v21_local_apk import (  # noqa: E402
    LUA_BUNDLE, NEW_TIMER, OLD_TIMER, preserve_native_counter,
)


class ShopNativeCounterTest(unittest.TestCase):
    def test_only_archived_timer_is_removed(self):
        apk = CLIENT / "build" / "witchweapon-online-local-staging-shop-runtime-v20.apk"
        with zipfile.ZipFile(apk) as archive:
            before = archive.read(LUA_BUNDLE)
        after = preserve_native_counter(before)
        original = UnityPy.load(before)
        patched = UnityPy.load(after)
        changes = [(a, b) for a, b in zip(original.objects, patched.objects)
                   if a.get_raw_data() != b.get_raw_data()]
        self.assertEqual(len(changes), 1)
        old_script = changes[0][0].read_typetree()["m_Script"]
        new_script = changes[0][1].read_typetree()["m_Script"]
        self.assertEqual(old_script.count(OLD_TIMER), 1)
        self.assertEqual(new_script, old_script.replace(OLD_TIMER, NEW_TIMER))
        self.assertNotIn("buyWidget", new_script)
        with self.assertRaises(ValueError):
            preserve_native_counter(after)


if __name__ == "__main__":
    unittest.main()
