"""Verify the two archived IL2CPP zero-price instruction replacements."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import unittest
import zipfile


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
from patch_chapter_level_up_duplicates import _PROFILES, _file_offset, _load_segments
from patch_zero_price_shop_cost import patch_zero_price_shop_cost, zero_price_shop_replacements


SOURCE = CLIENT / "build/witchweapon-online-original-ui-draw-retry-all-week-v2.apk"
PINS = {
    "arm64-v8a": ("24330b8e142b6c5e77fbe4ae6df5746eaabeea0c308c47609a4834f458ac12a1",
                  0x3ECB3A8, bytes.fromhex("1f040071e803003200b1801a"),
                  bytes.fromhex("1f000071e803003200b1801a")),
    "armeabi-v7a": ("9c8038cb4737c58f7ea5d48355de1164d66f9bcdd7071ef29bd5c095faf0692e",
                    0x3A5B844, bytes.fromhex("010050e3010000b3"),
                    bytes.fromhex("000050e3010000b3")),
}


class ZeroPriceShopCostTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest("Pinned source APK is unavailable")
        with zipfile.ZipFile(SOURCE) as source:
            cls.inputs = {f"lib/{abi}/libil2cpp.so":
                          source.read(f"lib/{abi}/libil2cpp.so") for abi in PINS}

    def test_both_architectures_change_only_comparison_immediate(self):
        for abi, (digest, address, before, after) in PINS.items():
            with self.subTest(abi=abi):
                raw = self.inputs[f"lib/{abi}/libil2cpp.so"]
                self.assertEqual(hashlib.sha256(raw).hexdigest(), digest)
                offset = _file_offset(_load_segments(raw, _PROFILES[abi]), address)
                self.assertEqual(raw[offset:offset + len(before)], before)
                patched = patch_zero_price_shop_cost(raw, abi)
                self.assertEqual(len(patched), len(raw))
                self.assertEqual(patched[offset:offset + len(after)], after)
                self.assertEqual(patched[:offset], raw[:offset])
                self.assertEqual(patched[offset + len(after):], raw[offset + len(before):])
                self.assertEqual(patch_zero_price_shop_cost(patched, abi), patched)

    def test_unknown_binary_and_abi_fail_closed(self):
        for abi, (_, address, _, _) in PINS.items():
            with self.subTest(abi=abi):
                raw = self.inputs[f"lib/{abi}/libil2cpp.so"]
                offset = _file_offset(_load_segments(raw, _PROFILES[abi]), address)
                broken = raw[:offset] + b"\xFF" + raw[offset + 1:]
                with self.assertRaisesRegex(ValueError, "Unexpected original"):
                    patch_zero_price_shop_cost(broken, abi)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            patch_zero_price_shop_cost(b"", "x86")

    def test_combined_builder_mapping_is_local_to_native_members(self):
        result = zero_price_shop_replacements(self.inputs.__getitem__)
        self.assertEqual(set(result), set(self.inputs))
        self.assertTrue(all(result[name] != raw for name, raw in self.inputs.items()))


if __name__ == "__main__":
    unittest.main()
