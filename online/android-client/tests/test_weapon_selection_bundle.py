"""Verify the new observer preserves the existing real client bundle."""

from pathlib import Path
import sys
import unittest
import zipfile

sys.dont_write_bytecode = True
CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

import UnityPy
import patch_weapon_selection_cache as patch


APK = Path(r"E:\Desktop\魔女兵器本地模式\魔女兵器-在线本地双区服-v110-测试.apk")


def objects(raw):
    return {obj.path_id: (obj.type.name, obj.get_raw_data())
            for obj in UnityPy.load(raw).objects}


def script(raw):
    return next(obj.read_typetree()["m_Script"] for obj in UnityPy.load(raw).objects
                if obj.type.name == "TextAsset"
                and obj.read_typetree()["m_Name"] == patch.ASSET_NAME)


class WeaponSelectionBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(APK) as archive:
            cls.raw = archive.read(patch.MEMBER)

    def test_only_active_init_changes_and_existing_fixes_survive(self):
        before = objects(self.raw)
        after_raw = patch.patch_bundle(self.raw)
        after = objects(after_raw)
        self.assertEqual(set(before), set(after))
        changed = [pid for pid in before if before[pid] != after[pid]]
        self.assertEqual(len(changed), 1)
        self.assertEqual(before[changed[0]][0], "TextAsset")
        self.assertEqual(script(after_raw), script(self.raw) + "\n" +
                         patch.SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual(patch.patch_bundle(after_raw), after_raw)

    def test_other_init_changes_are_preserved_when_composed(self):
        bundle = UnityPy.load(self.raw)
        obj = next(obj for obj in bundle.objects if obj.type.name == "TextAsset"
                   and obj.read_typetree()["m_Name"] == patch.ASSET_NAME)
        tree = obj.read_typetree()
        existing = tree["m_Script"] + "\n-- existing independent init fix\n"
        tree["m_Script"] = existing
        obj.save_typetree(tree)
        raw = bundle.file.save(packer="original")
        self.assertEqual(script(patch.patch_bundle(raw)),
                         existing + "\n" + patch.SCRIPT.read_text(encoding="utf-8"))

    def test_changed_existing_observer_is_rejected(self):
        source = script(self.raw) + "\n" + patch.MARKER + "\nunknown observer\n"
        with self.assertRaises(ValueError):
            patch.patch_init(source)


if __name__ == "__main__":
    unittest.main()
