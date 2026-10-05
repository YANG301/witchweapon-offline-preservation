"""Allow a real zero-price shop item through the original client cost check.

The archived IL2CPP ``ShopInfoHelper.getCostAfterDiscount`` returns at least
one even when the server and table both say a gift costs zero.  Keep the
original minimum-one rule for every positive calculated price while letting
an exact zero stay zero.  Only one comparison instruction changes per ABI.

This is a pure, composable binary replacement; the APK builder owns ZIP
members and signing.  Addresses and guard bytes belong to the 2017 archive.
"""

from __future__ import annotations

from patch_chapter_level_up_duplicates import _PROFILES, _file_offset, _load_segments


_SITES = {
    "arm64-v8a": (
        0x3ECB3A8,
        bytes.fromhex("1f040071e803003200b1801a"),
        bytes.fromhex("1f000071e803003200b1801a"),
    ),
    "armeabi-v7a": (
        0x3A5B844,
        bytes.fromhex("010050e3010000b3"),
        bytes.fromhex("000050e3010000b3"),
    ),
}


def patch_zero_price_shop_cost(libil2cpp_bytes: bytes, abi: str) -> bytes:
    """Return an ELF with zero-cost purchases accepted by the native checker.

    ARM64: ``cmp w0,#1`` -> ``cmp w0,#0`` before ``csel w0,w8,w0,lt``.
    ARMv7: ``cmp r0,#1`` -> ``cmp r0,#0`` before ``movwlt r0,#1``.
    Positive values keep their original result; negative values still become
    one.  Unexpected binaries fail closed instead of patching by pattern.
    """
    if abi not in _SITES:
        raise ValueError("Unsupported shop-price architecture")
    address, before, after = _SITES[abi]
    offset = _file_offset(_load_segments(libil2cpp_bytes, _PROFILES[abi]), address)
    actual = libil2cpp_bytes[offset:offset + len(before)]
    if actual == after:
        return libil2cpp_bytes
    if actual != before:
        raise ValueError(f"Unexpected original shop-price code: {abi} 0x{address:X}")
    return libil2cpp_bytes[:offset] + after + libil2cpp_bytes[offset + len(before):]


def zero_price_shop_replacements(read_member):
    """Return both ABI replacements for the final combined APK builder."""
    result = {}
    for abi in _SITES:
        member = f"lib/{abi}/libil2cpp.so"
        before = read_member(member)
        after = patch_zero_price_shop_cost(before, abi)
        if before != after:
            result[member] = after
    return result
