"""Pinned original Wiki and payment/login icon bundle regression."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
import zipfile

import UnityPy


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
import patch_legacy_links_and_payment_icons as patch  # noqa: E402


def targets(raw: bytes, kind: str, names: set[str]):
    return {tree["m_Name"]: tree for obj in UnityPy.load(raw).objects
            if obj.type.name == kind for tree in (obj.read_typetree(),)
            if tree.get("m_Name") in names}


class OriginalUiLinksPaymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apk = CLIENT / "build" / "witchweapon-online-password-copy-v5-test.apk"
        with zipfile.ZipFile(apk) as source:
            cls.before = {name: source.read(name) for name in patch.EXPECTED_BUNDLES}
        cls.after = patch.patch_bundles(cls.before)

    def test_wiki_uses_previous_domain_in_original_click_flow(self):
        original = targets(self.before[patch.UI], "TextAsset", {"UIActivities.lua"})["UIActivities.lua"]["m_Script"]
        updated = targets(self.after[patch.UI], "TextAsset", {"UIActivities.lua"})["UIActivities.lua"]["m_Script"]
        self.assertEqual(updated.count("URL_Wiki = 'https://witchweapon.wiki'"), 1)
        self.assertEqual(updated.count("AwardUtils.OpenWebURLNotie(URL_Wiki,false,nil)"), 1)
        self.assertEqual(updated.replace("\t-- Online preservation Wiki; keep the original Wiki button and click flow.\n"
                                         "\tURL_Wiki = 'https://witchweapon.wiki'\n", ""), original)

    def test_original_payment_and_wechat_objects_are_hidden(self):
        for member, names in ((patch.LOGIN, {"WechatContainner", "WeixinRegistBtn"}),
                              (patch.SHOP, {"zhifubao", "weixin"})):
            original = targets(self.before[member], "GameObject", names)
            updated = targets(self.after[member], "GameObject", names)
            self.assertEqual(set(updated), names)
            for name in names:
                self.assertIs(original[name]["m_IsActive"], True)
                self.assertIs(updated[name]["m_IsActive"], False)

    def test_pinned_input_rejects_bundle_drift(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed link/payment icon bundle"):
            patch.patch_one(patch.SHOP, self.before[patch.SHOP] + b"drift")


if __name__ == "__main__":
    unittest.main()
