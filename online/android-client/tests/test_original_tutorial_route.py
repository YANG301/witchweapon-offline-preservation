"""Check that the older, preserved onboarding route is selected in isolation."""

from pathlib import Path
import sys
import unittest
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import patch_original_tutorial_route as route


SOURCE = (Path(__file__).resolve().parents[1] / "build" /
          "witchweapon-online-original-ui-new-account-v2-register-fix.apk")
TRIGGER = "assets/assetbundle/config/clientexel/lessontrigger.ab"


class OriginalTutorialRouteTest(unittest.TestCase):
    def test_only_first_two_trigger_rows_change(self):
        with zipfile.ZipFile(SOURCE) as apk:
            original_bundle = apk.read(TRIGGER)
        _, _, _, before, _ = route._read(original_bundle)
        patched_bundle = route.patch_bundle(original_bundle)
        _, _, _, after, _ = route._read(patched_bundle)
        old_lines = before.splitlines()
        new_lines = after.splitlines()
        self.assertEqual(len(old_lines), len(new_lines))
        changed = [(old.split(",", 1)[0], old, new)
                   for old, new in zip(old_lines, new_lines) if old != new]
        self.assertEqual([record for record, _, _ in changed], ["1", "2"])
        self.assertIn(",10001,61100011001,", changed[0][2])
        self.assertIn("2,3,,509005002,", changed[1][2])
        self.assertIn(",00001,,,PreCombatBegin,3150001001,", changed[1][2])
        self.assertEqual(route.patch_bundle(patched_bundle), patched_bundle)

    def test_unexpected_stage_is_rejected(self):
        text = route.HEADER + "\n" + \
            "1,2,,-1,-1,-1,14001,61100011001,6010001,EnterInitialGuideScene,,-1,0,opening\n" + \
            "2,3,,509021001,-1,-1,01001,,,PreCombatBegin,3150001999,-1,0,fight\n"
        with self.assertRaisesRegex(ValueError, "Unexpected tutorial trigger"):
            route.patch_csv(text)


if __name__ == "__main__":
    unittest.main()
