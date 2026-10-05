"""Validate the one-bundle v5 task-row hotfix without building an APK."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_task_row_tolua_arity as patch  # noqa: E402


class TaskRowToluaArityPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        apk = CLIENT / "build" / "witchweapon-online-local-staging-password-copy-v5.apk"
        with zipfile.ZipFile(apk) as source:
            cls.original = source.read(patch.MEMBER)
        cls.patched = patch.patch_bundle(cls.original)

    def test_one_text_asset_changes(self) -> None:
        before = UnityPy.load(self.original)
        after = UnityPy.load(self.patched)
        changed = [b.read_typetree()["m_Name"] for b, a in zip(before.objects, after.objects)
                   if b.get_raw_data() != a.get_raw_data()]
        self.assertEqual(changed, ["TaskItemPatch.lua"])

    def test_fail_closed_on_unreviewed_bundle(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unreviewed task-row Lua bundle"):
            patch.patch_bundle(self.original + b"drift")


if __name__ == "__main__":
    unittest.main()
