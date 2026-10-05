"""Real archived assets: gate scope, protocol-preserving tables, native ABI guards."""

from pathlib import Path
import csv
import sys
import unittest

CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_feature_access_unlocked as feature
import patch_all_campaign_unlocked as campaign
from patch_feature_level_gates import _csv_tree
from patch_chapter_level_up_duplicates import patch_level_up_dictionary

ORIGINAL = CLIENT.parents[1] / "魔女兵器工程恢复" / "原版" / "Android工程"
BUNDLES = ORIGINAL / "assets/assetbundle/config/clientexel"


def table(raw, name):
    return _csv_tree(raw, name)[3]


def rows(text):
    return {r["ID"]: r for r in csv.DictReader(text.splitlines())
            if r["ID"].isdigit()}


class FeatureAccessUnlockedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.instance = (BUNDLES / "instance.ab").read_bytes()
        cls.sets = (BUNDLES / "instanceset.ab").read_bytes()

    def test_complete_non_mainline_levels_and_economy_unchanged(self):
        original = table(self.instance, "Instance")
        result, changed = feature.patch_instance_text(original)
        self.assertEqual(changed, 170)
        before, after = rows(original), rows(result)
        self.assertEqual(before.keys(), after.keys())
        for identity, row in before.items():
            expected = dict(row)
            if identity in feature.INSTANCE_GATES:
                expected["instance_enter_level"] = "1"
            self.assertEqual(after[identity], expected, identity)
            if row["instance_type"] not in ("2", "3"):
                self.assertLessEqual(int(after[identity]["instance_enter_level"] or 0), 1)
        # Screenshot's three leaked magic difficulties must all open at Lv1.
        for identity in ("3120001001", "3120001002", "3120001003"):
            self.assertEqual(after[identity]["instance_enter_level"], "1")
            self.assertEqual(after[identity]["instance_enter_limit"], "2")
            self.assertEqual(after[identity]["instance_stamina_victory"], "10")
        self.assertEqual(feature.patch_instance_text(result), (result, 0))

    def test_set_scope_and_front_next_graph_preserved(self):
        original = table(self.sets, "InstanceSet")
        result, changed = feature.patch_instance_set_text(original)
        self.assertEqual(changed, 11)
        for identity, row in rows(original).items():
            expected = dict(row)
            if identity in feature.INSTANCE_SET_GATES:
                expected["instance_set_enter_level"] = "1"
            self.assertEqual(rows(result)[identity], expected)
        self.assertEqual(feature.patch_instance_set_text(result), (result, 0))

    def test_bundle_roundtrip_mainline_composition_and_idempotence(self):
        for raw, name, patch, other in (
            (self.instance, "Instance", feature.patch_instance_bundle,
             campaign.patch_instance_bundle),
            (self.sets, "InstanceSet", feature.patch_instance_set_bundle,
             campaign.patch_instance_set_bundle),
        ):
            with self.subTest(table=name):
                once = patch(raw)
                self.assertEqual(patch(once), once)
                # Disjoint fields/rows: either composition order is equivalent.
                self.assertEqual(table(patch(other(raw)), name),
                                 table(other(patch(raw)), name))

    def test_csv_drift_and_duplicate_rejected(self):
        original = table(self.instance, "Instance")
        lines = original.splitlines(keepends=True)
        row = next(x for x in lines if x.startswith("3120001001,"))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            feature.patch_instance_text(original + row)
        with self.assertRaisesRegex(ValueError, "Missing"):
            feature.patch_instance_text(original.replace(row, "", 1))
        columns = lines[0].rstrip("\r\n").split(",")
        altered = row.rstrip("\r\n").split(",")
        altered[columns.index("instance_enter_level")] = "99"
        with self.assertRaisesRegex(ValueError, "Unexpected feature gate"):
            feature.patch_instance_text(original.replace(row, ",".join(altered) + "\n", 1))

    def test_native_exact_scope_idempotence_and_existing_level_up_fix(self):
        for abi, gates in feature.NATIVE_GATES.items():
            with self.subTest(abi=abi):
                original = (ORIGINAL / "lib" / abi / "libil2cpp.so").read_bytes()
                baseline, count = patch_level_up_dictionary(original, abi)
                self.assertEqual(count, 19)
                patched, count = feature.patch_native_entry_gates(baseline, abi)
                self.assertEqual(count, 2)
                self.assertEqual(len(patched), len(baseline))
                segments = feature._load_segments(baseline, feature._ELF_PROFILES[abi])
                rebuilt = bytearray(patched)
                for _, _, _, address, _ in gates:
                    offset = feature._file_offset(segments, address)
                    self.assertEqual(patched[offset:offset + 4],
                                     feature.NATIVE_INSTRUCTIONS[abi][1])
                    rebuilt[offset:offset + 4] = feature.NATIVE_INSTRUCTIONS[abi][0]
                self.assertEqual(bytes(rebuilt), baseline)
                self.assertEqual(feature.patch_native_entry_gates(patched, abi), (patched, 0))
                self.assertEqual(patch_level_up_dictionary(patched, abi), (patched, 0))
                # A nearby method-byte change must fail even if target opcode matches.
                altered = bytearray(baseline)
                offset = feature._file_offset(segments, gates[0][1])
                altered[offset] ^= 1
                with self.assertRaisesRegex(ValueError, "Unexpected native entry method"):
                    feature.patch_native_entry_gates(bytes(altered), abi)
                wrong_abi = "arm64-v8a" if abi == "armeabi-v7a" else "armeabi-v7a"
                with self.assertRaisesRegex(ValueError, "ELF format"):
                    feature.patch_native_entry_gates(baseline, wrong_abi)


if __name__ == "__main__":
    unittest.main()
