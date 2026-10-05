"""Unlock only the six original daily stages' client-side weekday checks.

The archived ``EverydayGames`` table lists four trial sets (3020001..4)
and two task sets (3020005..6). Their menu rendering calls
``TrialPanelController.IsPlay``; the pre-battle validator uses
``WaterBell.ProjX.Data.Entity.Check.CanPlay``. Both methods only decide
whether today's weekday is marked playable. All entry counts, stage data,
rewards, and other battle checks remain in their original code paths.

Profiles refer to the original game's IL2CPP metadata and native methods.
They are pinned by a SHA-256 of each entire method, with our two changed
instructions normalized to the original bytes for an idempotent recheck.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from patch_chapter_level_up_duplicates import (
    _PROFILES as _ELF_PROFILES,
    _file_offset,
    _load_segments,
)


@dataclass(frozen=True)
class WeekdayMethod:
    name: str
    rva: int
    size: int
    original_entry: bytes
    original_sha256: str


# ARM64 RVAs come from the archived original dump.cs. ARM32 RVAs were
# independently reconstructed with Il2CppDumper from the final source APK's
# lib/armeabi-v7a/libil2cpp.so and the archived original global-metadata.dat.
METHODS = {
    "arm64-v8a": (
        WeekdayMethod(
            "TrialPanelController.IsPlay", 0x154F62C, 0x144,
            bytes.fromhex("f657bda9f44f01a9"),
            "320ef9ca2aae39a16582abcf1f26c4e26da8de49d118ee2ab0d810ad801bcbef",
        ),
        WeekdayMethod(
            "Check.CanPlay", 0x3EB0CC8, 0x1AC,
            bytes.fromhex("f657bda9f44f01a9"),
            "34255e11e6701f2c9484e6ebb2b4ebc3ec3f601c45fc997423f495b031d7e120",
        ),
    ),
    "armeabi-v7a": (
        WeekdayMethod(
            "TrialPanelController.IsPlay", 0xA40DC4, 0x270,
            bytes.fromhex("30482de908b08de2"),
            "a1989f84e4208086d01d5e8b7d9bd97744e332fb32a13a3e24db194f44b31320",
        ),
        WeekdayMethod(
            "Check.CanPlay", 0x3A38BF0, 0x304,
            bytes.fromhex("f0482de910b08de2"),
            "fda95b321ccc311e540d6c4f412ce297a27b58c9b3f71bed3744262e2ce5d071",
        ),
    ),
}

# Return true before entering either method's prologue. The methods have no
# side effects required by callers; these are the ARM/AArch64 boolean return
# registers. Each ABI patch touches exactly two 4-byte instructions/method.
RETURN_TRUE = {
    "arm64-v8a": bytes.fromhex("20008052c0035fd6"),  # mov w0,#1; ret
    "armeabi-v7a": bytes.fromhex("0100a0e31eff2fe1"),  # mov r0,#1; bx lr
}


def patch_daily_weekday(library: bytes, abi: str) -> tuple[bytes, int]:
    """Return patched ELF and changed-method count (0 or 2).

    Rejects unknown libraries and partially patched binaries. Does not
    modify resources, quota logic, or methods other than the two named gates.
    """
    if abi not in METHODS:
        raise ValueError("Unsupported daily weekday ABI: " + abi)
    segments = _load_segments(library, _ELF_PROFILES[abi])
    replacement = RETURN_TRUE[abi]
    offsets = []
    states = []
    for method in METHODS[abi]:
        start = _file_offset(segments, method.rva)
        end = _file_offset(segments, method.rva + method.size - 4) + 4
        if end - start != method.size or len(method.original_entry) != len(replacement):
            raise ValueError("Invalid weekday method extent: " + method.name)
        observed = library[start:start + len(replacement)]
        if observed == method.original_entry:
            states.append(False)
        elif observed == replacement:
            states.append(True)
        else:
            raise ValueError("Unexpected weekday method entry: " + method.name)
        normalized = bytearray(library[start:end])
        normalized[:len(replacement)] = method.original_entry
        if hashlib.sha256(normalized).hexdigest() != method.original_sha256:
            raise ValueError("Unexpected weekday method body: " + method.name)
        offsets.append(start)
    if any(states) and not all(states):
        raise ValueError("Partially patched daily weekday library")
    if all(states):
        return library, 0
    result = bytearray(library)
    for offset in offsets:
        result[offset:offset + len(replacement)] = replacement
    return bytes(result), len(offsets)


__all__ = ["METHODS", "RETURN_TRUE", "patch_daily_weekday"]
