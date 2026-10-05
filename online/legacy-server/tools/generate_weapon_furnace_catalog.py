"""Reconstruct the five E.M.E Aggregator encounters from preserved assets.

The original instance/mob/weapon IDs and map are evidence. Enemy placement,
wave grouping, combat stats, and reward quantities are local recovery rules.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import generate_stage_catalog as stage


IDS = tuple(range(3120007001, 3120007006))


def generate(args):
    instances = {int(r["ID"]): r for r in stage.table(args.config / "instance.txt")}
    mob_lists = {int(r["ID"]): r for r in stage.table(args.config / "instancemoblist.txt")}
    mobs = {r["ID"]: r for r in stage.table(args.config / "mob.txt")}
    item_ids = {r["ID"] for r in stage.table(args.config / "item.txt")}
    weapon_rows = stage.table(args.config / "servantweapon.txt")
    core_by_weapon = {}
    for weapon in weapon_rows:
        wid, core = weapon["ID"], weapon["decompose_item_id3"]
        if core and core in item_ids:
            core_by_weapon[wid] = int(core)
    if len(core_by_weapon) < 50:
        raise ValueError("Original weapon core mapping is incomplete")

    scene = stage.scene_catalog(args.assets)[1028]
    stage.prepare_scene_geometry(scene, args.bundles / "map_1028_smelter.ab")
    entries, points, evidence = stage.placements(scene, [5])
    responses = json.loads(args.responses.read_text(encoding="utf-8"))
    cls = stage.basket_class(args.descriptors)
    base_info = cls.FromString(base64.b64decode(responses["/combat/mob/info"]["base64"]))
    base_json = json.loads(responses["/combat/mob/json"]["body"])
    result = {}
    for index, sid in enumerate(IDS):
        instance, row = instances[sid], mob_lists[sid]
        if int(instance["instance_set_attached"]) != 3020007 or int(row["mapID"]) != 1028:
            raise ValueError("Furnace source identity or map changed")
        if int(instance["instance_enter_level"]) != 25 + index * 10:
            raise ValueError("Furnace original unlock level changed")
        enemies = []
        for i in range(1, 6):
            mid = row[f"mob{i}"]
            if not mid or mid not in mobs or not mobs[mid]["model"]:
                raise ValueError("Missing furnace enemy identity/model")
            enemies.append(dict(id=int(mid), rank=int(row[f"mob{i}_type"]),
                                level=int(row[f"mob{i}_lv"]), model=mobs[mid]["model"]))
        if enemies[0]["rank"] != 3:
            raise ValueError("Furnace boss identity changed")
        grouping = [[enemies]]
        combat = stage.combat_json(base_json, instance, row, scene, enemies,
                                   entries, points, grouping)
        mob_payload = stage.combat_info(base_info, enemies).SerializeToString()
        confirmed = cls.FromString(mob_payload)
        keys = {(m.ID, m.CurType, m.Level) for m in confirmed.MobInfos}
        if keys != {(e["id"], e["rank"], e["level"]) for e in enemies}:
            raise ValueError("Furnace JSON/protobuf combat identity mismatch")
        result[str(sid)] = dict(
            id=sid, chapterId=3020007,
            recommendedLevel=int(instance["instance_enter_level"]),
            staminaVictory=int(instance["instance_stamina_victory"]),
            staminaEnter=int(instance["instance_stamina_enter"]),
            originalDropItems=[int(instance[f"instance_loot_item{i}"])
                               for i in range(1, 7) if instance[f"instance_loot_item{i}"]],
            enemies=enemies, combatJson=combat,
            combatMobInfo=dict(type="application/octet-stream",
                               base64=base64.b64encode(mob_payload).decode("ascii")))
    output = dict(schemaVersion=1, source="original Instance/InstanceMobList/ServantWeapon/scene/navigation",
                  localReconstruction=["enemy spawn positions", "single-zone wave topology",
                                       "combat attribute curve", "reward amounts"],
                  evidence=dict(instanceSha256=stage.digest(args.config / "instance.txt"),
                                mobListSha256=stage.digest(args.config / "instancemoblist.txt"),
                                weaponSha256=stage.digest(args.config / "servantweapon.txt"),
                                sceneSha256=scene["sceneSha256"],
                                navigationSha256=scene["navigationSha256"],
                                placement=evidence),
                  weaponCoreItems=core_by_weapon, stages=result)
    args.output.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n",
                           encoding="utf-8")
    check = json.loads(args.output.read_text(encoding="utf-8"))
    if len(check["stages"]) != 5 or len(check["weaponCoreItems"]) != len(core_by_weapon):
        raise ValueError("Furnace catalog readback failed")
    print(json.dumps(dict(stages=list(result), weapons=len(core_by_weapon),
                          sha256=stage.digest(args.output)), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=stage.CONFIG)
    parser.add_argument("--assets", type=Path, default=stage.ASSETS)
    parser.add_argument("--bundles", type=Path, default=stage.BUNDLES)
    parser.add_argument("--descriptors", type=Path, default=stage.DESCRIPTORS)
    parser.add_argument("--responses", type=Path,
                        default=stage.PROJECT / "resources/offline_responses.json")
    parser.add_argument("--output", type=Path,
                        default=stage.PROJECT / "resources/weapon_furnace_catalog.json")
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
