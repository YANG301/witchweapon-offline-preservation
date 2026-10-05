"""Static regression checks for the original six-daily weekday-only patch."""

from __future__ import annotations

import sys
from pathlib import Path
import struct
import unittest
import zipfile


CLIENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLIENT))

import build_daily_weekday_unlocked_apk as build
from patch_chapter_level_up_duplicates import _PROFILES, _file_offset, _load_segments
from patch_daily_weekday_unlocked import METHODS, RETURN_TRUE, patch_daily_weekday


CALLS = {
    "arm64-v8a": (
        (0x154EB14, 0x154F62C, True),  # DrawTrial -> UI weekday gate
        (0x154F16C, 0x154F62C, True),  # DrawTask -> UI weekday gate
        (0x3EB08D4, 0x3EB0CC8, False),  # trial check -> Check.CanPlay
        (0x3EB0B1C, 0x3EB0CC8, False),  # task check -> Check.CanPlay
    ),
    "armeabi-v7a": (
        (0xA40028, 0xA40DC4, True),
        (0xA407F0, 0xA40DC4, True),
        (0x3A38718, 0x3A38BF0, False),
        (0x3A389C4, 0x3A38BF0, False),
    ),
}


def branch(abi: str, address: int, target: int, link: bool) -> int:
    if abi == "arm64-v8a":
        return (0x94000000 if link else 0x14000000) | \
            (((target - address) // 4) & 0x3FFFFFF)
    return (0xEB000000 if link else 0xEA000000) | \
        (((target - address - 8) // 4) & 0xFFFFFF)


class DailyWeekdayPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not build.SOURCE.is_file():
            raise unittest.SkipTest("Pinned priced-draw APK not available")
        cls.libraries = {}
        with zipfile.ZipFile(build.SOURCE) as source:
            for abi in METHODS:
                cls.libraries[abi] = source.read(build.member(abi))

    def test_six_daily_sets_group_into_two_ui_paths(self) -> None:
        table = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置"
                     r"\配置\clientexel\everydaygames.txt")
        rows = table.read_text(encoding="utf-8").splitlines()
        first = rows[3].split(",")
        second = rows[4].split(",")
        self.assertEqual(first[3:7], ["3020001", "3020002", "3020003", "3020004"])
        self.assertEqual(second[3:5], ["3020005", "3020006"])

    def test_both_menu_and_prebattle_paths_call_weekday_predicates(self) -> None:
        for abi, library in self.libraries.items():
            with self.subTest(abi=abi):
                segments = _load_segments(library, _PROFILES[abi])
                for callsite, target, link in CALLS[abi]:
                    offset = _file_offset(segments, callsite)
                    observed = struct.unpack_from("<I", library, offset)[0]
                    self.assertEqual(observed, branch(abi, callsite, target, link))

    def test_only_two_eight_byte_entries_change_and_patch_is_idempotent(self) -> None:
        for abi, original in self.libraries.items():
            with self.subTest(abi=abi):
                patched, count = patch_daily_weekday(original, abi)
                self.assertEqual(count, 2)
                self.assertEqual(len(original), len(patched))
                offsets = build.changed_offsets(original, patched, abi)
                self.assertEqual(len(offsets), 2)
                for offset in offsets:
                    self.assertEqual(patched[offset:offset + 8], RETURN_TRUE[abi])
                again, changed = patch_daily_weekday(patched, abi)
                self.assertEqual(changed, 0)
                self.assertEqual(again, patched)

    def test_tampered_or_partial_library_is_rejected(self) -> None:
        for abi, original in self.libraries.items():
            with self.subTest(abi=abi):
                segments = _load_segments(original, _PROFILES[abi])
                first, second = (_file_offset(segments, m.rva) for m in METHODS[abi])
                partial = bytearray(original)
                partial[first:first + 8] = RETURN_TRUE[abi]
                with self.assertRaisesRegex(ValueError, "Partially patched"):
                    patch_daily_weekday(bytes(partial), abi)
                tampered = bytearray(original)
                tampered[second + 12] ^= 1
                with self.assertRaisesRegex(ValueError, "Unexpected weekday method body"):
                    patch_daily_weekday(bytes(tampered), abi)


if __name__ == "__main__":
    unittest.main()
