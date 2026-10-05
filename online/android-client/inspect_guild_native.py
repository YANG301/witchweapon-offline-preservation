"""Print reviewed original ARMv7 guild recall instruction windows (read only)."""

import struct
import zipfile
import re
import bisect
import sys
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM


APK = Path(__file__).resolve().parent / "build/witchweapon-original-stardust-v105-test.apk"
METHODS = {
    "RecallMercenary.ParseProtoBuf": (0x3B3F138, 0x3B3F4BC),
    "GuildMercenaryManagerController.RemoveSv": (0x973874, 0x973C04),
    "GuildMercenaryManagerController.FinishRemoveSv": (0x973C04, 0x973FF0),
    "GuildMercenaryManagerView.FinishRemoveExecuted": (0x976D74, 0x977858),
    "GuildMercenaryControl.GetReward": (0x352A064, 0x352A174),
    "ObservablePlayerGuild.UpdatePlayer": (0x3A75158, 0x3A75544),
    "ObservablePlayerGuild.UpdateContent": (0x3A75558, 0x3A760F0),
    "ObservablePlayerGuild.CaculateRecall": (0x3A74C10, 0x3A750B8),
    "GetAwardsPanel.ShowGuildServantReward": (0x3609510, 0x360971C),
    "ProtocolManager.ParseExtraInfo": (0x3B1C508, 0x3B1CBD0),
    "RoleGetRoleInfoLogic.ParseProtoBuf": (0x3B46018, 0x3B4657C),
}


def main() -> None:
    dump = Path(r"D:\Project\魔女兵器在线版\联调记录\ARMv7登录研究\dump.cs").read_text(encoding="utf-8")
    names = {}
    for match in re.finditer(r"// RVA: (0x[0-9A-F]+).*?\n\s*(?:public|private|protected|internal) (?:static )?(?:virtual )?(?:override )?.*? ([A-Za-z_][\w<>.]+)\([^\n]*", dump):
        names[int(match.group(1), 16)] = match.group(2)
    addresses = sorted(names)
    with zipfile.ZipFile(APK) as source:
        raw = source.read("lib/armeabi-v7a/libil2cpp.so")
    if raw[:5] != b"\x7fELF\x01":
        raise ValueError("Expected original ELF32 library")
    phoff = struct.unpack_from("<I", raw, 28)[0]
    entsize, count = struct.unpack_from("<HH", raw, 42)
    segments = []
    for i in range(count):
        kind, offset, vaddr, _, size, *_ = struct.unpack_from("<IIIIIIII", raw, phoff+i*entsize)
        if kind == 1:
            segments.append((vaddr, vaddr+size, offset))
    disasm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    for name, (start, end) in METHODS.items():
        if len(sys.argv) > 1 and not any(term in name for term in sys.argv[1:]):
            continue
        match = next(((lo, off) for lo, hi, off in segments if lo <= start < hi), None)
        if match is None:
            raise ValueError("Method outside loadable ELF segment: " + name)
        lo, off = match
        chunk = raw[off+start-lo:off+end-lo]
        print("METHOD", name, hex(start), len(chunk))
        instructions = list(disasm.disasm(chunk, start))
        for index, instruction in enumerate(instructions):
            if index < 500 or instruction.mnemonic.startswith("bl") or (name.endswith("UpdateContent") and 0x3A75E00 <= instruction.address < 0x3A76080):
                label = ""
                if instruction.mnemonic.startswith("bl"):
                    try:
                        dest = int(instruction.op_str.split()[0].lstrip("#"), 16)
                        pos = bisect.bisect_right(addresses, dest)-1
                        if pos >= 0 and dest-addresses[pos]<2048:
                            label = f" [{names[addresses[pos]]}+0x{dest-addresses[pos]:x}]"
                    except ValueError:
                        pass
                print(hex(instruction.address), instruction.mnemonic, instruction.op_str + label)


if __name__ == "__main__":
    main()
