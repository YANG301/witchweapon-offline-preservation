"""Check the archived game's exact level-up native callsite patch."""

from pathlib import Path
import struct
import sys
import unittest


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))
from patch_chapter_level_up_duplicates import (  # noqa: E402
    _PROFILES, _branch_instruction, _file_offset, _load_segments,
    patch_level_up_dictionary,
)


ORIGINAL_LIBS = (
    CLIENT.parents[1] / "魔女兵器工程恢复" / "原版" / "Android工程" / "lib"
)


class ChapterLevelUpDuplicatesTests(unittest.TestCase):
    def test_exact_nineteen_callsites_per_abi(self):
        for abi, profile in _PROFILES.items():
            with self.subTest(abi=abi):
                path = ORIGINAL_LIBS / abi / "libil2cpp.so"
                if not path.is_file():
                    self.skipTest(f"Archived libil2cpp not found: {path}")
                original = path.read_bytes()
                segments = _load_segments(original, profile)
                patched, changed = patch_level_up_dictionary(original, abi)
                self.assertEqual(changed, 19)
                self.assertEqual(len(patched), len(original))
                expected_offsets = set()
                for address in profile.callsites:
                    offset = _file_offset(segments, address)
                    expected_offsets.update(range(offset, offset + 4))
                    old = struct.unpack_from("<I", original, offset)[0]
                    new = struct.unpack_from("<I", patched, offset)[0]
                    self.assertEqual(old, _branch_instruction(abi, address,
                                                               profile.add))
                    self.assertEqual(new, _branch_instruction(abi, address,
                                                               profile.set_item))
                actual_offsets = {index for index, (old, new) in
                                  enumerate(zip(original, patched)) if old != new}
                self.assertTrue(actual_offsets)
                self.assertLessEqual(actual_offsets, expected_offsets)
                self.assertEqual(patch_level_up_dictionary(patched, abi),
                                 (patched, 0))

    def test_drift_partial_and_architecture_fail_closed(self):
        abi = "armeabi-v7a"
        profile = _PROFILES[abi]
        path = ORIGINAL_LIBS / abi / "libil2cpp.so"
        if not path.is_file():
            self.skipTest(f"Archived libil2cpp not found: {path}")
        original = path.read_bytes()
        offset = _file_offset(_load_segments(original, profile),
                              profile.callsites[0])
        damaged = bytearray(original)
        damaged[offset] ^= 1
        with self.assertRaisesRegex(ValueError, "Unexpected or partial"):
            patch_level_up_dictionary(bytes(damaged), abi)

        partial = bytearray(original)
        struct.pack_into("<I", partial, offset,
                         _branch_instruction(abi, profile.callsites[0],
                                             profile.set_item))
        with self.assertRaisesRegex(ValueError, "Unexpected or partial"):
            patch_level_up_dictionary(bytes(partial), abi)
        with self.assertRaisesRegex(ValueError, "ELF format"):
            patch_level_up_dictionary(original, "arm64-v8a")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            patch_level_up_dictionary(original, "x86")


if __name__ == "__main__":
    unittest.main()
