"""Read-only audit of the original ARM64 shop rendering methods.

The Unity export contains empty C# stubs. This resolves their real IL2CPP
addresses and prints direct calls and ARM64 instructions without modifying
either APK or library.
"""

from __future__ import annotations

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
    "WaterBell.ProjX.Data.Entity.ShopInfoHelper$$GetGoodPriceSpriteNameByPriceType",
    "WaterBell.ProjX.Data.Entity.ShopInfoHelper$$GetGoodPriceSpriteNameFromShop",
    "WaterBell.ProjX.View.Panel.UIShopItemData$$HandlePriceInfo",
    "WaterBell.ProjX.View.Panel.UIShopItemSpriteEx$$RenderPrice",
    "WaterBell.ProjX.View.Panel.UIShopItemSpriteEx$$SetCurrency",
    "NewShopPanelControl$$SetShopPrice",
    "NewShopPanelControl$$GetPriceList",
    "ShopItemInfo$$SetGoPrice",
)


def symbols():
    by_address = {}
    current = None
    with SCRIPT.open(encoding="utf-8-sig") as source:
        for line in source:
            if '"ScriptString"' in line:
                break
            found = re.search(r'"Address": (\d+)', line)
            if found:
                current = int(found.group(1))
            found = re.search(r'"Name": "([^"]+)"', line)
            if found and current is not None:
                by_address.setdefault(current, []).append(json.loads('"' + found.group(1) + '"'))
    return by_address


def audit(targets=TARGETS, listing=False):
    by_address = symbols()
    sorted_addresses = sorted(by_address)
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    results = []
    with SO.open("rb") as binary:
        for name in targets:
            matches = [(address, names) for address, names in by_address.items() if name in names]
            if len(matches) != 1:
                raise ValueError(f"Expected one match for {name}, found {len(matches)}")
            start = matches[0][0]
            end = sorted_addresses[bisect.bisect_right(sorted_addresses, start)]
            if not 0 < end - start <= 32768:
                raise ValueError(f"Unbounded method {name}: {end-start}")
            binary.seek(native.file_offset(binary, start))
            raw = binary.read(end - start)
            calls = []
            instructions = []
            for ins in decoder.disasm(raw, start):
                if listing:
                    instructions.append(f"{ins.address:#x}: {ins.mnemonic} {ins.op_str}")
                if ins.mnemonic in ("bl", "b") and ins.operands and ins.operands[0].type == capstone.arm64.ARM64_OP_IMM:
                    target = ins.operands[0].imm
                    if not start <= target < end:
                        names = [symbol for symbol in by_address.get(target, [])
                                 if any(term in symbol for term in ("Shop", "UILabel$$set_text", "UISprite$$set_spriteName",
                                                                     "GameObject$$SetActive", "CurrencyView", "VIP"))]
                        if names:
                            calls.append({"pc": hex(ins.address), "target": hex(target), "symbols": names[:6]})
            results.append({"method": name, "start": hex(start), "end": hex(end), "calls": calls,
                            "instructions": instructions if listing else None})
    return results


if __name__ == "__main__":
    targets = tuple(name for name in TARGETS
                    if "--target" not in sys.argv or sys.argv[sys.argv.index("--target") + 1] in name)
    print(json.dumps(audit(targets, listing="--listing" in sys.argv), ensure_ascii=False, indent=2))
