"""Read-only original ARM64 method call audit for RecycleItem protocol."""
from pathlib import Path
import json
import struct
import sys

sys.path.insert(0, r"D:\Environment\UnityTools\python-libs")
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

root = Path(r"D:\Project\魔女兵器工程恢复\原版")
binary = (root / "Android工程/lib/arm64-v8a/libil2cpp.so").read_bytes()
index = json.loads((root / "原生代码/类型与方法索引/script.json").read_text("utf-8-sig"))
methods = index["ScriptMethod"]
symbols = {}
for entry in methods:
    symbols.setdefault(entry["Address"], []).append(entry["Name"])


def offset(virtual_address):
    program_offset = struct.unpack_from("<Q", binary, 0x20)[0]
    header_size, count = struct.unpack_from("<HH", binary, 0x36)
    for index in range(count):
        at = program_offset + index * header_size
        kind, _, file_offset, start, _, file_size, _, _ = struct.unpack_from("<IIQQQQQQ", binary, at)
        if kind == 1 and start <= virtual_address < start + file_size:
            return file_offset + virtual_address - start
    raise ValueError(hex(virtual_address))


for name in ("CycleItem$$AddArgumentsBeforeSend", "CycleItem$$OnProtoBufData",
             "CycleItem$$ParseProtoBuf", "GetCycleShopInfo$$ParseProtoBuf",
             "RecycleShop$$SellItem", "RecycleShop$$SellAll"):
    found = [entry for entry in methods if name in entry["Name"]]
    if len(found) != 1:
        print(name, "found", len(found))
        continue
    address = found[0]["Address"]
    next_address = min(entry["Address"] for entry in methods if entry["Address"] > address)
    size = min(next_address - address, 4096)
    print("\n", name, hex(address), "size", size)
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for instruction in decoder.disasm(binary[offset(address):offset(address) + size], address):
        if name.endswith("RecycleShop$$SellItem") and instruction.mnemonic in ("mul", "madd"):
            print(hex(instruction.address), instruction.mnemonic, instruction.op_str)
        if instruction.mnemonic in ("bl", "b"):
            try:
                target = int(instruction.op_str.lstrip("#"), 16)
            except ValueError:
                continue
            names = symbols.get(target, [])
            if names:
                print(hex(instruction.address), hex(target), names[:4])
