"""Prepare the original email UI to pass its password to the Android shim.

The preserved IL2CPP client hashes the password before POSTing the legacy
account form. The online Go API must continue verifying its existing PBKDF2
password records, so the future Java adapter needs the original input instead.
Only the two login/register call sites are changed in each ABI. This module
does not modify an APK, bypass authentication, or install anything by itself.
"""

import argparse
import hashlib
import json
import struct
import zipfile
from pathlib import Path


SOURCE = Path(r"D:\Project\魔女兵器工程恢复\单机版\作者源码构建\构建产物\witchweapon-author-source.apk")
SOURCE_SHA256 = "f16e8e4d913157e082ab3a770444a8b8995c47731a2a9e3b54372cb43f41f9cf"

# (ELF virtual address, file offset, original instruction, replacement).
# ARM64: x20 holds the UI password; ARM32: login r9/sb, register r5.
SPECS = {
    "arm64-v8a": {
        "elf_class": 2,
        "machine": 183,
        "size": 92312960,
        "sha256": "a38fb195b1c8d389036bcfaf6eec1663f7abb21f7035e13349971da8d788d4e4",
        "sites": (
            (0x141E934, 0x141E934, bytes.fromhex("1c01fc97"), bytes.fromhex("e00314aa")),
            (0x1421C74, 0x1421C74, bytes.fromhex("4cf4fb97"), bytes.fromhex("e00314aa")),
        ),
    },
    "armeabi-v7a": {
        "elf_class": 1,
        "machine": 40,
        "size": 76860472,
        "sha256": "8eb27c8cc66793f7493c7281410c4dcaa8efd115025d6867bf09586ba8bbc696",
        "sites": (
            (0x8D0FB0, 0x8D0FB0, bytes.fromhex("9f22fbeb"), bytes.fromhex("0900a0e1")),
            (0x8D4CD4, 0x8D4CD4, bytes.fromhex("5613fbeb"), bytes.fromhex("0500a0e1")),
        ),
    },
}


def _elf_offset(raw: bytes, abi: str, address: int) -> int:
    """Resolve one executable ELF virtual address without trusting RVA=offset."""
    spec = SPECS[abi]
    if len(raw) < 64 or raw[:4] != b"\x7fELF" or raw[4] != spec["elf_class"] or raw[5] != 1:
        raise ValueError("Unexpected IL2CPP ELF class or endianness: " + abi)
    if struct.unpack_from("<H", raw, 18)[0] != spec["machine"]:
        raise ValueError("Unexpected IL2CPP ELF machine: " + abi)
    if spec["elf_class"] == 2:
        phoff = struct.unpack_from("<Q", raw, 32)[0]
        phentsize, phnum = struct.unpack_from("<HH", raw, 54)
        minimum = 56
    else:
        phoff = struct.unpack_from("<I", raw, 28)[0]
        phentsize, phnum = struct.unpack_from("<HH", raw, 42)
        minimum = 32
    if phentsize < minimum or not 0 < phnum <= 128 or phoff + phentsize * phnum > len(raw):
        raise ValueError("Invalid IL2CPP program headers: " + abi)
    for index in range(phnum):
        pos = phoff + phentsize * index
        if struct.unpack_from("<I", raw, pos)[0] != 1:
            continue
        if spec["elf_class"] == 2:
            flags = struct.unpack_from("<I", raw, pos + 4)[0]
            offset, virtual, file_size = (
                struct.unpack_from("<Q", raw, pos + 8)[0],
                struct.unpack_from("<Q", raw, pos + 16)[0],
                struct.unpack_from("<Q", raw, pos + 32)[0],
            )
        else:
            offset, virtual, file_size = (
                struct.unpack_from("<I", raw, pos + 4)[0],
                struct.unpack_from("<I", raw, pos + 8)[0],
                struct.unpack_from("<I", raw, pos + 16)[0],
            )
            flags = struct.unpack_from("<I", raw, pos + 24)[0]
        if flags & 1 and virtual <= address < virtual + file_size:
            mapped = offset + address - virtual
            if mapped + 4 > len(raw) or address + 4 > virtual + file_size:
                raise ValueError("IL2CPP instruction extends beyond ELF segment: " + abi)
            return mapped
    raise ValueError("IL2CPP call site is not in executable ELF data: " + abi)


def patch(raw: bytes, abi: str) -> bytes:
    """Return patched library bytes; reject changed inputs and repeat calls."""
    if abi not in SPECS:
        raise ValueError("Unsupported IL2CPP ABI: " + abi)
    if not isinstance(raw, bytes):
        raise TypeError("IL2CPP input must be immutable bytes")
    spec = SPECS[abi]
    if len(raw) != spec["size"]:
        raise ValueError("IL2CPP library size changed: " + abi)
    mapped_sites = []
    for address, expected_offset, original, replacement in spec["sites"]:
        offset = _elf_offset(raw, abi, address)
        if offset != expected_offset:
            raise ValueError("IL2CPP call site moved: " + abi)
        current = raw[offset:offset + len(original)]
        if current == replacement:
            raise ValueError("Original account UI patch already applied: " + abi)
        if current != original:
            raise ValueError("Original account UI instruction changed: " + abi)
        mapped_sites.append((offset, replacement))
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise ValueError("IL2CPP source hash changed outside account UI: " + abi)
    output = bytearray(raw)
    for offset, replacement in mapped_sites:
        output[offset:offset + len(replacement)] = replacement
    return bytes(output)


def check() -> dict:
    """Read the pinned APK and validate both patches without writing files."""
    with SOURCE.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != SOURCE_SHA256:
            raise ValueError("Pinned author APK hash changed")
    results = {}
    with zipfile.ZipFile(SOURCE) as archive:
        for abi, spec in SPECS.items():
            name = "lib/" + abi + "/libil2cpp.so"
            original = archive.read(name)
            modified = patch(original, abi)
            try:
                patch(modified, abi)
            except ValueError as error:
                if "already applied" not in str(error):
                    raise
            else:
                raise AssertionError("Repeated account UI patch was accepted")
            results[abi] = {
                "sourceBytes": len(original),
                "sourceSha256": spec["sha256"],
                "patchedSha256": hashlib.sha256(modified).hexdigest(),
                "callSites": [hex(site[0]) for site in spec["sites"]],
            }
    return {"status": "ORIGINAL_AUTH_PATCH_STATIC_CHECK_OK", "libraries": results,
            "apkBuildRequired": True, "javaAdapterRequired": True,
            "runtimeValidated": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check(), ensure_ascii=False))
