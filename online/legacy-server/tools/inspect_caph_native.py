"""Read-only ARM64 call audit for the original CAPH activity entry points.

The Unity export contains placeholder C# method bodies. This inspects the
original IL2CPP library and maps direct calls back to script.json symbols.
It deliberately does not patch a client or a server.
"""

import bisect
import importlib.util
import json
import re
import sys
from pathlib import Path


ORIGINAL = Path(r"D:\Project\魔女兵器工程恢复\原版\原生代码")
SCRIPT = ORIGINAL / "类型与方法索引" / "script.json"
SO = ORIGINAL / "输入" / "arm64" / "libil2cpp.so"
HELPER = Path(r"D:\Project\魔女兵器工程恢复\恢复脚本\Inspect-DescriptorInitializers.py")
sys.path.insert(0, r"D:\Environment\UnityTools\python-libs")
import capstone

spec = importlib.util.spec_from_file_location("native_offset", HELPER)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)

TARGETS = (
    "WaterBell.ProjX.Data.Entity.ActivityPlay$$.ctor",
    "WaterBell.ProjX.Data.NetIO.ProtocolManager$$ParseActivityGameInstance",
    "WaterBell.ProjX.Data.NetIO.ProtocolManager.<Login>c__Iterator0$$MoveNext",
    "WaterBell.ProjX.Data.NetIO.GetActivityPlayInfo$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.GetActivityPlayInfo$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.GetRule1Data$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.GetRule2Data$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.GetRule3Data$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.GetRule4Data$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.GetRule5Data$$ParseProtoBuf",
    "WaterBell.ProjX.Data.NetIO.ActivityPlayEnter$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.GetActivityPlayMobs$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.GetActivityPlayRoleInfo$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.ActivityPlayStartBattle$$OnProtoBufData",
    "WaterBell.ProjX.Data.NetIO.ActivityPlayWin$$OnProtoBufData",
)


def symbols():
    addresses = {}
    address = None
    with SCRIPT.open(encoding="utf-8-sig") as source:
        for line in source:
            if '"ScriptString"' in line:
                break
            found = re.search(r'"Address": (\d+)', line)
            if found:
                address = int(found.group(1))
            found = re.search(r'"Name": "([^"]+)"', line)
            if found and address is not None:
                name = json.loads('"' + found.group(1) + '"')
                addresses.setdefault(address, []).append(name)
    return addresses


def audit(addresses):
    sorted_addresses = sorted(addresses)
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    results = []
    with SO.open("rb") as binary:
        for requested in TARGETS:
            matches = [(at, names) for at, names in addresses.items() if requested in names]
            for start, names in matches:
                position = bisect.bisect_right(sorted_addresses, start)
                end = sorted_addresses[position]
                if not 0 < end - start <= 32768:
                    raise ValueError(f"Unbounded method: {requested} at {start:#x}")
                binary.seek(native.file_offset(binary, start))
                raw = binary.read(end - start)
                calls = []
                other_calls = []
                login_activity_calls = []
                for ins in decoder.disasm(raw, start):
                    if ins.mnemonic not in ("bl", "b") or not ins.operands:
                        continue
                    operand = ins.operands[0]
                    if operand.type != capstone.arm64.ARM64_OP_IMM:
                        continue
                    target = operand.imm
                    if start <= target < end:
                        continue
                    target_names = addresses.get(target, [])
                    if "<Login>" in requested and 0x3F7FE20 <= ins.address < 0x3F80280:
                        login_activity_calls.append({"pc": hex(ins.address), "target": hex(target),
                                                     "symbols": target_names[:5]})
                    meaningful = [name for name in target_names if any(
                        tag in name for tag in ("get_Parser", "ParseFrom", "ActivityPlay", "CommonInfo",
                                            "RuleDatas", "GetRule", "OnProto", "Send", "Refresh"))]
                    if meaningful:
                        calls.append({"pc": hex(ins.address), "target": hex(target),
                                      "symbols": meaningful[:8]})
                    elif len(raw) <= 256:
                        other_calls.append({"pc": hex(ins.address), "target": hex(target),
                                            "symbols": target_names[:5]})
                results.append({"method": requested, "rva": hex(start), "size": len(raw),
                                "calls": calls, "other_calls": other_calls,
                                "login_activity_calls": login_activity_calls})
    return results


if __name__ == "__main__":
    results = audit(symbols())

    def verifies(method_suffix, callee):
        return any(row["method"].endswith(method_suffix) and any(
            callee in symbol for call in row["calls"] for symbol in call["symbols"])
                   for row in results)

    assert verifies("<Login>c__Iterator0$$MoveNext", "GetRule3Data$$.ctor")
    assert verifies("GetRule3Data$$ParseProtoBuf", "Apmod.R3Data$$get_Parser")
    assert verifies("GetActivityPlayMobs$$OnProtoBufData", "Combatmod.Basket$$get_Parser")
    assert verifies("GetActivityPlayRoleInfo$$OnProtoBufData", "Combatmod.RoleCombatInfoProto$$get_Parser")
    assert verifies("ActivityPlayWin$$OnProtoBufData", "Lootmod.LootResult$$get_Parser")
    print(json.dumps(results, ensure_ascii=False, indent=2))
