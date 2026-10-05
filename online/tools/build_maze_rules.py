"""Build the small, source-attributed maze rule resource; no server rollout."""
import csv
import hashlib
import json
from pathlib import Path

PROJECT = Path(r"D:\Project\魔女兵器在线版")
CLIENT = Path(r"D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel")
GROWTH = PROJECT / "参考资料/战斗数据核查/2019编辑器战斗表/1.1.70/MobLevelInfo.csv"

def rows(path):
    return [r for r in csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()) if r["ID"].isdigit()]

def main():
    character = CLIENT / "characterlevelinfo.txt"
    loot = CLIENT / "coreinstancelootinfo.txt"
    result = {
        "schemaVersion": 1,
        "sources": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in (character, loot, GROWTH)],
        "reconstruction": {"itemQuantity": "每个原表图标对应真实物品发1份；原服概率、数量未恢复", "roleExp": "普通通关5EXP沿用本地规则", "encounters": "保留各层原布局与怪物组，按原玩家等级表与MobLevelInfo成长系数同步动态等级/属性"},
        "roleLevels": {}, "loots": {}, "mobGrowth": {},
    }
    for r in rows(character):
        result["roleLevels"][r["ID"]] = {
            "levels": [int(r[f"core_instance_level{i}"]) for i in range(1, 13)],
            "loots": [int(r[f"core_instance_loot{i}"]) for i in range(1, 13)],
            "bonuses": [int(r[f"core_instance_loot_bonus{i}"]) for i in range(1, 5)],
        }
    for r in rows(loot):
        result["loots"][r["ID"]] = {"gold": int(r["gold"]), "items": [int(r[f"icon{i}"]) for i in range(1, 6) if r[f"icon{i}"]]}
    for r in rows(GROWTH):
        result["mobGrowth"][r["ID"]] = [int(r[f"attribute_modulus{i}"]) if r[f"attribute_modulus{i}"] else 0 for i in range(1, 11)]
    assert len(result["roleLevels"]) == 100 and len(result["mobGrowth"]) == 105
    assert result["roleLevels"]["100"]["levels"][-1] == 105
    target = PROJECT / "legacy-server/resources/maze_rules.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(target.read_text(encoding="utf-8")) == result
    print(json.dumps({"path": str(target), "bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}, ensure_ascii=False))

if __name__ == "__main__":
    main()
