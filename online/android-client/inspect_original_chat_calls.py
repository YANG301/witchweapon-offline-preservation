"""Read-only AArch64 call-site probe for original chat initialization.

It scans direct BL instructions in the installed candidate's IL2CPP library and
maps them back to recovered method names. Indirect calls are not covered.
"""

import bisect
import json
import struct
import sys
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
APK = HERE / "build" / "witchweapon-online-original-ui-xinfengzhou-hide-white-v2-test.apk"
METHODS = HERE.parent.parent / "魔女兵器工程恢复" / "原版" / "原生代码" / "类型与方法索引" / "script.json"
TARGET_NAMES = (
    "WaterBell.ProjX.Data.NetIO.GetChatInfo$$.ctor",
    "WaterBell.ProjX.Data.NetIO.GetChatInfo$$AddArgumentsBeforeSend",
    "WaterBell.ProjX.Data.NetIO.GetChatInfo$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.GetChatInfo$$ParseProtoBuf",
    "ChatInitialization$$Init",
    "WaterBell.ProjX.Core.Manager.LeanCloudChatSystemManager$$Init",
    "WaterBell.ProjX.Core.Manager.LeanCloudChatSystemManager$$LoginUser",
)


def executable_segments(raw):
    if raw[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", raw, 18)[0] != 183:
        raise ValueError("Expected little-endian ARM64 ELF")
    phoff = struct.unpack_from("<Q", raw, 32)[0]
    entsize, count = struct.unpack_from("<HH", raw, 54)
    for index in range(count):
        pos = phoff + index * entsize
        if struct.unpack_from("<I", raw, pos)[0] != 1:
            continue
        flags = struct.unpack_from("<I", raw, pos + 4)[0]
        if not flags & 1:
            continue
        offset, virtual, size = (
            struct.unpack_from("<Q", raw, pos + 8)[0],
            struct.unpack_from("<Q", raw, pos + 16)[0],
            struct.unpack_from("<Q", raw, pos + 32)[0],
        )
        if offset + size > len(raw):
            raise ValueError("Truncated ELF segment")
        yield offset, virtual, size


def main():
    if not APK.is_file() or not METHODS.is_file():
        raise ValueError("Pinned APK or recovered method index missing")
    methods = json.loads(METHODS.read_text(encoding="utf-8-sig"))["ScriptMethod"]
    names = {item["Name"]: item["Address"] for item in methods}
    targets = {names[name]: name for name in TARGET_NAMES}
    ordered = sorted((item["Address"], item["Name"]) for item in methods)
    starts = [value[0] for value in ordered]
    with zipfile.ZipFile(APK) as file:
        raw = file.read("lib/arm64-v8a/libil2cpp.so")
    found = {name: [] for name in TARGET_NAMES}
    for offset, virtual, size in executable_segments(raw):
        words = memoryview(raw)[offset:offset + size].cast("I")
        for index, instruction in enumerate(words):
            if instruction & 0xFC000000 != 0x94000000:
                continue
            imm = instruction & 0x03FFFFFF
            if imm & 0x02000000:
                imm -= 0x04000000
            caller = virtual + 4 * index
            callee = caller + 4 * imm
            name = targets.get(callee)
            if name is None:
                continue
            method_index = bisect.bisect_right(starts, caller) - 1
            owner = ordered[method_index][1] if method_index >= 0 else "<unknown>"
            found[name].append({"callSite": hex(caller), "owner": owner})
    print(json.dumps({"directCalls": found, "note": "Indirect IL2CPP delegate and vtable calls are not visible"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
