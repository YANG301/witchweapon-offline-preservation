"""Build the forty preserved daily-stage identities with playable local combat.

The original APK contains stage, enemy, and reward tables but no original
server wave layout or combat balance.  The known working one-room layout is
therefore reused as an explicit temporary replacement, one original enemy per
stage.  This file never changes the source tables.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
from pathlib import Path

from generate_stage_catalog import CONFIG, PROJECT, DESCRIPTORS, basket_class, table


OUTPUT = PROJECT / "resources/daily_stage_catalog.json"
SOURCE = PROJECT / "resources/stage_catalog.json"
RESPONSES = PROJECT / "resources/offline_responses.json"
WEEKDAYS = {
    3020001: [1, 4, 7],  # Man of Steel
    3020002: [2, 5, 7],  # Magic Overflow
    3020003: [3, 6, 7],  # Arrival of Boss
    3020004: [1, 2, 3, 4, 5, 6, 7],  # Free for All
    3020005: [1, 3, 5],  # Bounty
    3020006: [2, 4, 6, 7],  # Practice
}
EXPECTED_COUNTS = {3020001: 7, 3020002: 7, 3020003: 7,
                   3020004: 7, 3020005: 6, 3020006: 6}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> dict:
    sets = {int(r["ID"]): r for r in table(CONFIG / "instanceset.txt")}
    instances = [r for r in table(CONFIG / "instance.txt")
                 if r["instance_set_attached"] in map(str, WEEKDAYS)]
    mob_lists = {r["ID"]: r for r in table(CONFIG / "instancemoblist.txt")}
    mobs = {r["ID"]: r for r in table(CONFIG / "mob.txt")}
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    responses = json.loads(RESPONSES.read_text(encoding="utf-8"))
    if source.get("mode") != "simple-campaign-v1":
        raise ValueError("Reviewed one-room campaign template is required")
    template = source["stages"]["3110001001"]["combatJson"]
    base = basket_class(DESCRIPTORS).FromString(
        base64.b64decode(responses["/combat/mob/info"]["base64"]))
    if len(instances) != 40:
        raise ValueError("Expected all forty original daily stages")
    catalog = {}
    for row in sorted(instances, key=lambda r: int(r["ID"])):
        stage_id = int(row["ID"])
        set_id = int(row["instance_set_attached"])
        set_row = sets[set_id]
        mob_row = mob_lists.get(str(stage_id))
        if mob_row is None or not mob_row["mob1"]:
            raise ValueError(f"Missing original enemy: {stage_id}")
        enemy_id = mob_row["mob1"]
        enemy = mobs.get(enemy_id)
        if enemy is None or not enemy.get("model"):
            raise ValueError(f"Missing original enemy model: {enemy_id}")
        item_id = int(row["instance_loot_item1"] or 0)
        if item_id == 0 or str(item_id) not in responses["_catalog"]["items"]:
            raise ValueError(f"Missing original reward item: {stage_id}")
        rank = int(mob_row["mob1_type"])
        level = int(mob_row["mob1_lv"])
        if rank not in (1, 2, 3) or level < 1:
            raise ValueError(f"Invalid original enemy attributes: {stage_id}")
        battle = copy.deepcopy(template)
        battle["EnemyLayer"]["levelID"] = str(stage_id)
        battle["EnemyLayer"]["lvMin"] = level
        battle["EnemyLayer"]["lvMax"] = level
        battle["MapInfo"]["globalBuff"] = int(mob_row["globalbuff"] or 0)
        zone = battle["EnemyLayer"]["areas"][0]["zones"][0]
        first_wave = zone["waves"][0]
        first_enemy = first_wave["monsters"][0]
        first_enemy["opName"] = enemy["model"]
        first_enemy["statID"] = f"{enemy_id}-{rank}-{level}"
        first_wave["monsters"] = [first_enemy]
        zone["waves"] = [first_wave]
        boss = type(base)()
        boss.CopyFrom(base)
        boss.ClearField("MobInfos")
        boss.ClearField("MobTypeInfos")
        original = base.MobInfos[0 if rank >= 2 else min(1, len(base.MobInfos) - 1)]
        info = boss.MobInfos.add()
        info.CopyFrom(original)
        info.ID = int(enemy_id)
        info.CurType = rank
        info.Level = level
        info.Model = enemy["model"]
        info.MobTypeInfoNormal = info.MobTypeInfoElite = info.MobTypeInfoBoss = int(enemy_id)
        info.Hp = min(3000, (180 + level * 22) * (2 if rank == 3 else 1))
        info.PhysicalAttack = info.MagicalAttack = min(50, 5 + level)
        info.PhysicalDefense = info.MagicalDefense = 0
        typ = boss.MobTypeInfos.add()
        typ.CopyFrom(base.MobTypeInfos[0 if rank >= 2 else min(1, len(base.MobTypeInfos) - 1)])
        typ.ID = int(enemy_id)
        if boss.MobInfos[0].ID != int(enemy_id) or boss.MobInfos[0].Model != enemy["model"]:
            raise ValueError(f"Combat payload mismatch: {stage_id}")
        item = {
            "id": stage_id,
            "setId": set_id,
            "difficulty": int(row["instance_number"]),
            "dailyLimit": int(set_row["instance_set_enter_limit"]),
            "weekdays": WEEKDAYS[set_id],
            "staminaOnWin": int(row["instance_stamina_victory"]),
            "rewardItem": item_id,
            "originalMapId": int(mob_row["mapID"]),
            "originalEnemy": {"id": int(enemy_id), "rank": rank, "level": level,
                              "model": enemy["model"]},
            "originalMinLevel": int(row["instance_enter_level"]),
            "combatJson": battle,
            "combatMobInfo": base64.b64encode(boss.SerializeToString()).decode("ascii"),
        }
        if set_row["instance_set_enter_limit"] not in ("2", "3") or item["staminaOnWin"] != 10:
            raise ValueError(f"Unexpected daily limit or stamina: {stage_id}")
        catalog[str(stage_id)] = item
    for set_id, count in EXPECTED_COUNTS.items():
        matches = [s for s in catalog.values() if s["setId"] == set_id]
        if len(matches) != count or sorted(s["difficulty"] for s in matches) != list(range(1, count + 1)):
            raise ValueError(f"Incomplete daily difficulty group: {set_id}")
    return {
        "schemaVersion": 1,
        "mode": "one-room-local-reconstruction",
        "note": "原版关卡、敌人、掉落物和开放日；单区单敌波次、数值和每次固定掉落为本地重建。",
        "inputs": {name: sha(CONFIG / name) for name in
                   ("instanceset.txt", "instance.txt", "instancemoblist.txt", "mob.txt")},
        "templateSha256": sha(SOURCE),
        "stages": catalog,
    }


def main() -> None:
    data = build()
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    check = json.loads(OUTPUT.read_text(encoding="utf-8"))
    if len(check["stages"]) != 40 or check["mode"] != data["mode"]:
        raise ValueError("Daily catalog read-back failed")
    print("DAILY_CATALOG_GENERATED", len(check["stages"]), sha(OUTPUT))


if __name__ == "__main__":
    main()
