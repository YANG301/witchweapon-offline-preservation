"""The temporary combat preview must retain the original sweep UI gate."""

from pathlib import Path
import unittest

from patch_simple_campaign import (
    MAINLINE_IDS, _csv_tree, _repeatable_mainline,
    patch_moblist_text, patch_simple_moblist,
)
from patch_sweep_bonus import patch_sweep_bonus_bundle, patch_sweep_bonus_text


CONFIG = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")


def rows(text):
    header = text.splitlines()[0].split(",")
    result = {}
    for line in text.splitlines()[1:]:
        parts = line.split(",")
        if parts[0] in MAINLINE_IDS:
            # The original chapter-12 table has five duplicate odd stages;
            # the patch intentionally retains the first occurrence.
            result.setdefault(parts[0], dict(zip(header, parts)))
    return result


class SimpleCampaignSweepBonusTest(unittest.TestCase):
    def test_original_repeatable_gates_survive_simple_preview(self):
        original_mob = (CONFIG / "instancemoblist.txt").read_text(encoding="utf-8-sig")
        original_inst = (CONFIG / "instance.txt").read_text(encoding="utf-8-sig")
        patched = patch_moblist_text(original_mob)
        self.assertEqual(patch_moblist_text(patched), patched)
        old, actual = rows(original_mob), rows(patched)
        self.assertEqual(len(actual), 235)
        self.assertEqual(actual["3110001001"]["instBonusType"], "0")
        self.assertEqual(actual["3110001002"]["instBonusType"], "2")
        self.assertEqual(actual["3110016002"]["instBonusType"], "2")
        self.assertEqual(actual["3110016001"]["instBonusType"], "0")

        instance_rows = {}
        names = original_inst.splitlines()[0].split(",")
        for line in original_inst.splitlines()[1:]:
            columns = line.split(",")
            if columns[0] in MAINLINE_IDS:
                instance_rows[columns[0]] = dict(zip(names, columns))
        self.assertEqual(len(instance_rows), 235)
        for identity in MAINLINE_IDS:
            repeatable = instance_rows[identity]["instance_repeatable"] == "1"
            self.assertEqual(_repeatable_mainline(identity), repeatable, identity)
            if repeatable:
                self.assertNotEqual(actual[identity]["instBonusType"], "0", identity)
            if identity in old and old[identity]["instBonusType"] != "0":
                self.assertEqual(actual[identity]["instBonusType"],
                                 old[identity]["instBonusType"], identity)

    def test_repairs_previously_zeroed_repeatable_row(self):
        original = (CONFIG / "instancemoblist.txt").read_text(encoding="utf-8-sig")
        patched = patch_moblist_text(original)
        lines = patched.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if line.startswith("3110001002,"):
                content = line.rstrip("\r\n")
                columns = content.split(",")
                columns[3] = "0"
                lines[index] = ",".join(columns) + line[len(content):]
                break
        repaired = patch_moblist_text("".join(lines))
        self.assertEqual(rows(repaired)["3110001002"]["instBonusType"], "2")

    def test_original_bundle_round_trip_without_apk_packaging(self):
        source = CONFIG.parents[2] / "Android工程/assets/assetbundle/config/clientexel/instancemoblist.ab"
        patched = patch_simple_moblist(source.read_bytes())
        _, _, _, text, _ = _csv_tree(patched, "InstanceMobList")
        actual = rows(text)
        self.assertEqual(len(actual), 235)
        self.assertEqual(actual["3110001002"]["instBonusType"], "2")
        self.assertEqual(actual["3110016002"]["instBonusType"], "2")

    def test_targeted_preview_upgrade_restores_original_type_and_param(self):
        reference = (CONFIG.parents[2] /
                     "Android工程/assets/assetbundle/config/clientexel/instancemoblist.ab").read_bytes()
        current = patch_simple_moblist(reference)
        patched = patch_sweep_bonus_bundle(current, reference)
        self.assertEqual(patch_sweep_bonus_bundle(patched, reference), patched)
        _, _, _, before, _ = _csv_tree(current, "InstanceMobList")
        _, _, _, after, _ = _csv_tree(patched, "InstanceMobList")
        self.assertEqual(len(before.splitlines()), len(after.splitlines()))
        changed_type = changed_param = 0
        for old, new in zip(before.splitlines(), after.splitlines()):
            old_cols, new_cols = old.split(","), new.split(",")
            if old_cols[0] not in MAINLINE_IDS:
                self.assertEqual(old, new)
            else:
                self.assertEqual(len(old_cols), len(new_cols))
                self.assertEqual(old_cols[:3] + old_cols[5:],
                                 new_cols[:3] + new_cols[5:])
                changed_type += old_cols[3] != new_cols[3]
                changed_param += old_cols[4] != new_cols[4]
        self.assertEqual(changed_type, 0)
        self.assertEqual(changed_param, 213)
        self.assertEqual(rows(after)["3110001002"]["instBonusType"], "2")
        self.assertEqual(rows(after)["3110001002"]["intstBonusParam"], "0.5")
        self.assertEqual(rows(after)["3110016002"]["intstBonusParam"], "0")

    def test_repairs_1_2_type_and_param_without_touching_chapter_16(self):
        original = (CONFIG / "instancemoblist.txt").read_text(encoding="utf-8-sig")
        current = patch_moblist_text(original)
        lines = current.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if line.startswith("3110001002,"):
                content = line.rstrip("\r\n")
                fields = content.split(",")
                fields[3:5] = ["0", "0"]
                lines[index] = ",".join(fields) + line[len(content):]
                break
        repaired = patch_sweep_bonus_text("".join(lines), original)
        self.assertEqual(rows(repaired)["3110001002"]["instBonusType"], "2")
        self.assertEqual(rows(repaired)["3110001002"]["intstBonusParam"], "0.5")
        self.assertEqual(rows(repaired)["3110016002"], rows(current)["3110016002"])


if __name__ == "__main__":
    unittest.main()
