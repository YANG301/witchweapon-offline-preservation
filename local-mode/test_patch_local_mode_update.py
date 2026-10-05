"""Small read-only checks for the local signed-updater source variant."""

from __future__ import annotations

import ast
import difflib
import unittest

import patch_local_mode_update as updater


class LocalUpdatePatchTest(unittest.TestCase):
    def test_only_recovery_and_manifest_hunks_change(self) -> None:
        original = updater.ONLINE_UPDATER.read_bytes()
        patched = updater.patch(original)
        before = original.decode("utf-8").splitlines(keepends=True)
        after = patched.decode("utf-8").splitlines(keepends=True)
        changes = [(tag, i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in
                   difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes()
                   if tag != "equal"]
        self.assertEqual(changes, [("replace", 1, 5), ("insert", 0, 6)])
        self.assertEqual(updater.ONLINE_UPDATER.read_bytes(), original)

    def test_guard_matches_both_modified_apk_members(self) -> None:
        label_file = updater.Path(__file__).with_name("patch_local_mode_login_label.py")
        tree = ast.parse(label_file.read_text(encoding="utf-8"))
        members = {}
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id in {"LOGIN_PREFAB", "LOGIN_SCENE"}:
                        members[target.id] = ast.literal_eval(statement.value)
        self.assertEqual(set(members), {"LOGIN_PREFAB", "LOGIN_SCENE"})
        patched = updater.patch(updater.ONLINE_UPDATER.read_bytes()).decode("utf-8")
        for member in members.values():
            self.assertTrue(member.startswith("assets/assetbundle/"))
            self.assertIn('"' + member.removeprefix("assets/") + '".equalsIgnoreCase(path)',
                          patched.replace("\n                    ", ""))

    def test_changed_online_source_is_rejected(self) -> None:
        original = updater.ONLINE_UPDATER.read_bytes()
        with self.assertRaisesRegex(ValueError, "changed"):
            updater.patch(original + b" ")


if __name__ == "__main__":
    unittest.main()
