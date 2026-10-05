"""Regression for shop payment marks resurrected by native tab redraw."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_payment_icons_runtime as patch  # noqa: E402


def load_apk(name: str) -> dict[str, bytes]:
    with zipfile.ZipFile(CLIENT / "build" / name) as apk:
        return {member: apk.read(member) for member in patch.EXPECTED_BUNDLES}


def objects(raw: bytes):
    return {obj.path_id: obj.read_typetree() for obj in UnityPy.load(raw).objects}


class RuntimePaymentIconsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = load_apk("witchweapon-online-local-staging-exchange-levels-v9.apk")
        cls.patched = patch.patch_bundles(cls.source)

    def test_candidate_and_staging_have_identical_reviewed_game_bundles(self):
        self.assertEqual(
            self.source, load_apk("witchweapon-online-exchange-levels-v9-test.apk"))
        self.assertEqual(
            {member: hashlib.sha256(raw).hexdigest()
             for member, raw in self.source.items()}, patch.EXPECTED_BUNDLES)

    def test_shop_tab_reactivation_cannot_show_or_click_marks(self):
        for member, buttons in patch.SHOP_BUTTONS.items():
            before, after = objects(self.source[member]), objects(self.patched[member])
            for button_id, child_id, sprite_id, collider_id, sprite_name in buttons:
                with self.subTest(member=member, button=before[button_id]["m_Name"]):
                    # Previous v8 patch hid only the parent. Native code can
                    # turn that parent back on when the tab redraws.
                    self.assertIs(before[button_id]["m_IsActive"], False)
                    self.assertIs(before[child_id]["m_IsActive"], True)
                    self.assertTrue(before[collider_id]["m_Enabled"])
                    self.assertEqual(before[sprite_id]["mSpriteName"], sprite_name)
                    self.assertIs(after[button_id]["m_IsActive"], False)
                    self.assertIs(after[child_id]["m_IsActive"], False)
                    self.assertIs(after[collider_id]["m_Enabled"], False)
                    self.assertEqual(after[sprite_id]["m_Enabled"], 0)
                    self.assertEqual(after[sprite_id]["mColor"]["a"], 0.0)
                    # Simulate SetActive(true) on the parent and child. The
                    # graphic component remains disabled and fully transparent.
                    after[button_id]["m_IsActive"] = True
                    after[child_id]["m_IsActive"] = True
                    self.assertEqual(after[sprite_id]["mColor"]["a"], 0.0)
                    self.assertEqual(after[sprite_id]["m_Enabled"], 0)
                    self.assertIs(after[collider_id]["m_Enabled"], False)

    def test_login_wechat_reactivation_cannot_show_or_click_mark(self):
        before, after = objects(self.source[patch.LOGIN]), objects(self.patched[patch.LOGIN])
        self.assertIs(before[patch.LOGIN_ICON]["m_IsActive"], True)
        self.assertIs(after[patch.LOGIN_CONTAINER]["m_IsActive"], False)
        self.assertIs(after[patch.LOGIN_BUTTON]["m_IsActive"], False)
        self.assertIs(after[patch.LOGIN_ICON]["m_IsActive"], False)
        self.assertIs(after[patch.LOGIN_COLLIDER]["m_Enabled"], False)
        for visual_id in patch.LOGIN_VISUALS:
            self.assertEqual(after[visual_id]["m_Enabled"], 0)
            self.assertEqual(after[visual_id]["mColor"]["a"], 0.0)

    def test_unreviewed_bundle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed runtime payment bundle"):
            patch.patch_one(patch.NEW_SHOP, self.source[patch.NEW_SHOP] + b"drift")


if __name__ == "__main__":
    unittest.main()
