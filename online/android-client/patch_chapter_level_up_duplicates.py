"""Repair the original level-up panel after feature-level gates are lowered.

The original ``ChapterLevelUpPanel.GetText`` creates a dictionary keyed by the
feature unlock level.  The online build lowers several unlock levels to 1, so
its original ``Dictionary.Add`` calls throw on duplicate keys.  Redirect only
those calls to the same generic dictionary's ``set_Item`` implementation.  The
original popup and the lowered entry gates remain intact.

This module patches ``libil2cpp.so`` bytes; the APK builder owns ZIP updates.
The addresses and branch targets below are for the archived 2017 APK only.
Each instruction is checked before modification to fail closed on a new build.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class _PatchProfile:
    elf_class: int
    machine: int
    get_text: int
    add: int
    set_item: int
    callsites: tuple[int, ...]


_PROFILES = {
    "armeabi-v7a": _PatchProfile(
        elf_class=1,
        machine=40,
        get_text=0x38B0D30,
        add=0x2DF7984,
        set_item=0x2DF6978,
        callsites=(
            0x38B10D0, 0x38B10EC, 0x38B1108, 0x38B1124, 0x38B1140,
            0x38B115C, 0x38B1178, 0x38B1194, 0x38B11B0, 0x38B11DC,
            0x38B11FC, 0x38B121C, 0x38B123C, 0x38B125C, 0x38B127C,
            0x38B129C, 0x38B12BC, 0x38B12DC, 0x38B1308,
        ),
    ),
    "arm64-v8a": _PatchProfile(
        elf_class=2,
        machine=183,
        get_text=0x3D74B14,
        add=0x3415344,
        set_item=0x341448C,
        callsites=(
            0x3D74E50, 0x3D74E6C, 0x3D74E88, 0x3D74EA4, 0x3D74EC0,
            0x3D74EDC, 0x3D74EF8, 0x3D74F14, 0x3D74F30, 0x3D74F5C,
            0x3D74F7C, 0x3D74F9C, 0x3D74FBC, 0x3D74FDC, 0x3D74FFC,
            0x3D7501C, 0x3D7503C, 0x3D7505C, 0x3D75084,
        ),
    ),
}


def _load_segments(data: bytes, profile: _PatchProfile) -> list[tuple[int, int, int]]:
    if len(data) < 64 or data[:4] != b"\x7fELF" or data[4] != profile.elf_class:
        raise ValueError("Unexpected libil2cpp ELF format")
    if data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != profile.machine:
        raise ValueError("Unexpected libil2cpp architecture")
    if profile.elf_class == 1:
        phoff = struct.unpack_from("<I", data, 28)[0]
        entsize, count = struct.unpack_from("<HH", data, 42)
        format_ = "<IIIIIIII"
        expected_size = 32
        indexes = (2, 4, 1)
    else:
        phoff = struct.unpack_from("<Q", data, 32)[0]
        entsize, count = struct.unpack_from("<HH", data, 54)
        format_ = "<IIQQQQQQ"
        expected_size = 56
        indexes = (3, 5, 2)
    if entsize < expected_size or phoff + entsize * count > len(data):
        raise ValueError("Invalid libil2cpp program headers")
    segments = []
    for index in range(count):
        entry = struct.unpack_from(format_, data, phoff + entsize * index)
        if entry[0] != 1:  # PT_LOAD
            continue
        vaddr, filesz, offset = (entry[i] for i in indexes)
        if offset + filesz > len(data):
            raise ValueError("Invalid libil2cpp load segment")
        segments.append((vaddr, vaddr + filesz, offset))
    return segments


def _file_offset(segments: list[tuple[int, int, int]], address: int) -> int:
    for start, end, offset in segments:
        if start <= address and address + 4 <= end:
            return offset + address - start
    raise ValueError(f"Address outside file-backed load segment: 0x{address:X}")


def _branch_instruction(abi: str, address: int, target: int) -> int:
    if abi == "armeabi-v7a":
        delta = target - address - 8
        bits = 24
        opcode = 0xEB000000  # ARM-state BL; PC points two instructions ahead.
    else:
        delta = target - address
        bits = 26
        opcode = 0x94000000  # AArch64 BL.
    if delta % 4 or not -(1 << (bits - 1)) <= delta // 4 < (1 << (bits - 1)):
        raise ValueError("Level-up branch target is out of range")
    return opcode | ((delta // 4) & ((1 << bits) - 1))


def patch_level_up_dictionary(libil2cpp_bytes: bytes, abi: str) -> tuple[bytes, int]:
    """Return a patched ELF and the number of changed callsites (0 or 19).

    Supports the archived APK's ARMv7 and ARM64 libraries, including builds
    previously modified elsewhere. An already patched library is accepted.
    Raises ``ValueError`` if one expected instruction has drifted or if the
    library is only partially patched.
    """
    if abi not in _PROFILES:
        raise ValueError(f"Unsupported libil2cpp ABI: {abi}")
    profile = _PROFILES[abi]
    segments = _load_segments(libil2cpp_bytes, profile)
    _file_offset(segments, profile.get_text)  # Confirm this method is present.
    _file_offset(segments, profile.add)
    _file_offset(segments, profile.set_item)
    if len(profile.callsites) != 19 or len(set(profile.callsites)) != 19:
        raise ValueError("Unexpected level-up callsite profile")

    offsets = [_file_offset(segments, address) for address in profile.callsites]
    observed = [struct.unpack_from("<I", libil2cpp_bytes, offset)[0]
                for offset in offsets]
    before = [_branch_instruction(abi, address, profile.add)
              for address in profile.callsites]
    after = [_branch_instruction(abi, address, profile.set_item)
             for address in profile.callsites]
    if observed == after:
        return libil2cpp_bytes, 0
    if observed != before:
        bad = next(index for index, (got, old) in enumerate(zip(observed, before))
                   if got != old)
        raise ValueError(
            f"Unexpected or partial level-up patch at 0x{profile.callsites[bad]:X}"
        )

    result = bytearray(libil2cpp_bytes)
    for offset, instruction in zip(offsets, after):
        struct.pack_into("<I", result, offset, instruction)
    return bytes(result), len(offsets)


__all__ = ["patch_level_up_dictionary"]
