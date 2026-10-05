"""Exact client level-gate patch checks; no APK is written or installed."""

from pathlib import Path
import sys
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from patch_feature_level_gates import (  # noqa: E402
    CHAT_LEVELS, INSTANCE_ENTER_LEVELS, SINGLE_CHANNEL_GATES,
    _constant_tree, _instance_set_tree, patch_bundle, patch_constant_text,
    patch_instance_set_bundle, patch_instance_set_text,
)


CURRENT_APK = (Path(__file__).resolve().parents[1] / "build" /
               "witchweapon-online-original-ui-task-progress-v4-test.apk")
CONSTANT_MEMBER = "assets/assetbundle/config/clientexel/constant.ab"
INSTANCE_MEMBER = "assets/assetbundle/config/clientexel/instanceset.ab"


def sample_text():
    rows = ["ID,value1,value2,value3,value4,channel_group,,,,,,\r\n",
            "string,string,long,int,int,int,,,,,,\r\n",
            "CHARACTER_MAX_LEVEL,,,65,,25,,,,,,\r\n",
            "CORE_INSTANCE_SERVANT_MIN_LEVEL,,,20,,0,,,,,,\r\n"]
    rows.extend(f"{key},,,{value},,0,,,,,,\r\n"
                for key, value in SINGLE_CHANNEL_GATES.items())
    rows.extend(f"{key},,,{value},,{channel},,,,,,\r\n"
                for key, channels in CHAT_LEVELS.items()
                for channel, value in channels.items())
    return "".join(rows)


class FeatureLevelGateTests(unittest.TestCase):
    def test_exact_rows_and_repeatability(self):
        source = sample_text()
        patched, count = patch_constant_text(source)
        self.assertEqual(count, len(SINGLE_CHANNEL_GATES) +
                         sum(len(channels) for channels in CHAT_LEVELS.values()))
        self.assertIn("CHARACTER_MAX_LEVEL,,,65,,25", patched)
        self.assertIn("CORE_INSTANCE_SERVANT_MIN_LEVEL,,,20,,0", patched)
        self.assertEqual(patch_constant_text(patched), (patched, 0))
        original_rows = source.splitlines()
        patched_rows = patched.splitlines()
        self.assertEqual(len(original_rows), len(patched_rows))
        for before, after in zip(original_rows, patched_rows):
            if before != after:
                self.assertEqual(before.split(",")[0], after.split(",")[0])
                self.assertEqual(before.split(",")[:3], after.split(",")[:3])
                self.assertEqual(after.split(",")[3], "1")
                self.assertEqual(before.split(",")[4:], after.split(",")[4:])

    def test_unknown_or_duplicate_gate_rejected(self):
        text = sample_text()
        with self.assertRaises(ValueError):
            patch_constant_text(text.replace("ASSOCIATION_ENTER_LEVEL,,,15",
                                             "ASSOCIATION_ENTER_LEVEL,,,99"))
        with self.assertRaises(ValueError):
            patch_constant_text(text + "ASSOCIATION_ENTER_LEVEL,,,15,,0,,,,,,\r\n")
        with self.assertRaises(ValueError):
            patch_constant_text(text.replace("ASSOCIATION_ENTER_LEVEL,,,15,,0,,,,,,\r\n", ""))

    def test_instance_set_exact_columns(self):
        header = ("ID,instance_set_enter_level,instance_set_sweep_level,front_instance\r\n")
        rows = [header, "0,0,99,\r\n"]
        rows.extend(f"{row_id},{level},99,precondition\r\n"
                    for row_id, level in INSTANCE_ENTER_LEVELS.items())
        source = "".join(rows)
        patched, count = patch_instance_set_text(source)
        self.assertEqual(count, len(INSTANCE_ENTER_LEVELS))
        self.assertEqual(patch_instance_set_text(patched), (patched, 0))
        self.assertIn("0,0,99,\r\n", patched)
        for before, after in zip(source.splitlines(), patched.splitlines()):
            if before != after:
                self.assertEqual(before.split(",")[0], after.split(",")[0])
                self.assertEqual(before.split(",")[2:], after.split(",")[2:])
                self.assertEqual(after.split(",")[1], "1")
        with self.assertRaises(ValueError):
            patch_instance_set_text(source + "9999999,20,1,\r\n")
        with self.assertRaises(ValueError):
            patch_instance_set_text(source.replace("3010002,5", "3010002,99"))

    @unittest.skipUnless(CURRENT_APK.is_file(), "Current original-UI test APK is absent")
    def test_current_client_bundle_round_trip(self):
        with zipfile.ZipFile(CURRENT_APK) as apk:
            raw = apk.read(CONSTANT_MEMBER)
            instance_raw = apk.read(INSTANCE_MEMBER)
        _, _, _, old, _ = _constant_tree(raw)
        patched = patch_bundle(raw)
        _, _, _, actual, _ = _constant_tree(patched)
        expected, count = patch_constant_text(old)
        self.assertGreater(count, 0)
        self.assertEqual(actual, expected)
        self.assertEqual(patch_bundle(patched), patched)
        _, _, _, instance_old, _ = _instance_set_tree(instance_raw)
        instance_patched = patch_instance_set_bundle(instance_raw)
        _, _, _, instance_actual, _ = _instance_set_tree(instance_patched)
        instance_expected, instance_count = patch_instance_set_text(instance_old)
        self.assertEqual(instance_count, len(INSTANCE_ENTER_LEVELS))
        self.assertEqual(instance_actual, instance_expected)
        self.assertEqual(patch_instance_set_bundle(instance_patched), instance_patched)


if __name__ == "__main__":
    unittest.main()
