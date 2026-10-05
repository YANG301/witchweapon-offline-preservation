"""Generate an opt-in normal-stage profile from original APK evidence.

Original Instance/MobList, scene/navigation and monster identities survive.
Server waves, spawn coordinates, attributes and AI do not. The latter are
retained from an explicitly labelled local reconstruction. Tutorial stages
and chapter 16 remain on the existing simple fallback, as does production.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import copy
import csv
import hashlib
import json
from pathlib import Path

import generate_original_1_2_test_profile as original12

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "test-profiles/original-normal/stage_catalog.json"
SKILL = b"Mob_NormalAttack_Melee_Physical"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_rows(filename: str) -> dict[str, list[dict[str, str]]]:
    with (original12.CONFIG / filename).open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in list(csv.DictReader(source))[2:] if row.get("ID", "").isdigit()]
    result: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        result.setdefault(row["ID"], []).append(row)
    return result


def selected_ids(reconstruction: dict, mob_rows: dict) -> tuple[str, ...]:
    candidates = tuple(stage_id for stage_id, stage in reconstruction["stages"].items()
                       if stage["type"] == 2 and stage["supported"] and not stage.get("guide"))
    ambiguous = tuple(stage_id for stage_id in candidates
                      if len(mob_rows.get(stage_id, ())) != 1)
    # The original APK has conflicting duplicate enemy lists/levels for five
    # chapter-12 normal stages. Do not choose either row without server proof.
    require(ambiguous == tuple(f"311001200{i}" for i in (1, 3, 5, 7, 9)),
            "Unreviewed duplicate or missing original MobList rows")
    result = tuple(stage_id for stage_id in candidates if stage_id not in ambiguous)
    by_chapter = Counter(reconstruction["stages"][stage_id]["chapterId"] for stage_id in result)
    require(len(result) == 139 and by_chapter == {3010001: 4, 3010012: 5,
                    **{3010000 + i: 10 for i in range(2, 16) if i != 12}},
            "Unreviewed normal-stage/tutorial membership change")
    return result


def validate_stage(stage_id: str, active: dict, restored: dict, rows: dict,
                   file_hashes: dict[Path, str], original_spells: bytes) -> None:
    simple = active["stages"][stage_id]
    stage = restored["stages"][stage_id]
    require(len(rows["instance"].get(stage_id, ())) == 1 and
            stage["source"]["instance"] == rows["instance"][stage_id][0],
            f"Original Instance mismatch: {stage_id}")
    mob_row = rows["moblist"][stage_id][0]
    require(stage["source"]["mobList"] == mob_row and
            stage["mapId"] == int(mob_row["mapID"]),
            f"Original MobList/map mismatch: {stage_id}")
    source_enemy_order = [(int(mob_row[f"mob{i}"]), int(mob_row[f"mob{i}_type"]),
                           int(mob_row[f"mob{i}_lv"])) for i in range(1, 6)
                          if mob_row.get(f"mob{i}")]
    stage_enemy_order = [(enemy["id"], enemy["rank"], enemy["level"])
                         for enemy in stage["enemies"]]
    wire_enemy_order = [tuple(map(int, monster["statID"].split("-")))
                        for area in stage["combatJson"]["EnemyLayer"]["areas"]
                        for zone in area["zones"] for wave in zone["waves"]
                        for monster in wave["monsters"]]
    require(len(source_enemy_order) in (4, 5) and
            source_enemy_order == stage_enemy_order == wire_enemy_order,
            f"Enemy ID/rank/level/order mismatch: {stage_id}")
    require(simple["mapId"] == 1010 and len(simple["enemies"]) == 1 and
            simple["supported"], f"Simple fallback changed: {stage_id}")
    require(stage["sceneName"].startswith(f"map_{stage['mapId']}_") and
            stage["combatJson"]["MapInfo"]["sceneName"] == stage["sceneName"] and
            stage["combatJson"]["EnemyLayer"]["levelID"] == stage_id,
            f"Map or battle stage reference mismatch: {stage_id}")
    scene = original12.ASSETS / "resources-/scene/map" / (stage["sceneName"] + ".unity")
    nav = original12.ASSETS / "TextAsset" / stage["navigation"]["navigationFile"]
    bundle = original12.BUNDLE.parent / (stage["sceneName"] + ".ab")
    for path, recorded in ((scene, stage["navigation"]["sceneSha256"]),
                           (nav, stage["navigation"]["navigationSha256"]),
                           (bundle, stage["navigation"]["geometry"]["bundleSha256"])):
        if path not in file_hashes:
            require(path.is_file(), f"Original map asset missing: {path}")
            file_hashes[path] = digest(path)
        require(file_hashes[path] == recorded, f"Original map asset changed: {path}")
    wire = base64.b64decode(stage["combatMobInfo"]["base64"], validate=True)
    require(SKILL in wire and SKILL in original_spells and b"Offline_" not in wire,
            f"Enemy skill not preserved by the original APK: {stage_id}")
    navigation = stage["navigation"]
    require(stage["localReconstruction"] and
            navigation["geometry"]["method"] ==
                "original-scene-world-mesh-and-navigation-intersection" and
            navigation["geometry"]["floorSafeNodes"] > 0 and
            len(navigation["enemyPoints"]) == len(source_enemy_order),
            f"Missing provenance or safe navigation evidence: {stage_id}")


def generate() -> dict:
    active = json.loads(original12.DEFAULT.read_text(encoding="utf-8"))
    reconstruction = json.loads(original12.RECONSTRUCTION.read_text(encoding="utf-8"))
    require(active.get("mode") == "simple-campaign-v1" and
            len(active["stages"]) == len(reconstruction["stages"]) == 235,
            "Production fallback or preserved catalog changed")
    require(digest(original12.RECONSTRUCTION) == original12.RECONSTRUCTION_SHA256 and
            active.get("restorationSource", {}).get("sha256") == original12.RECONSTRUCTION_SHA256,
            "Pinned original-reconstruction evidence changed")
    rows = {"instance": source_rows("instance.txt"),
            "moblist": source_rows("instancemoblist.txt")}
    ids = selected_ids(reconstruction, rows["moblist"])
    for name in ("instance.txt", "instancemoblist.txt"):
        require(digest(original12.CONFIG / name) == reconstruction["inputs"][name],
                f"Original {name} source changed")
    original_spells = original12.SPELLS.read_bytes()
    file_hashes: dict[Path, str] = {}
    profile = copy.deepcopy(active)
    for stage_id in ids:
        validate_stage(stage_id, active, reconstruction, rows,
                       file_hashes, original_spells)
        profile["stages"][stage_id] = copy.deepcopy(reconstruction["stages"][stage_id])
    profile["experimentalProfile"] = {
        "id": "original-normal-local-reconstruction", "testOnly": True,
        "changedStageIds": [int(stage_id) for stage_id in ids],
        "originalEvidence": ["Instance/MobList rows", "scene, map and navigation",
                             "enemy IDs, ranks, levels and order", "basic enemy skill template"],
        "localReconstruction": ["waves", "spawn coordinates", "stats", "AI"],
        "unchangedFallback": ["six tutorial normal stages", "five ambiguous chapter-12 normals",
                              "chapter 16", "all elite stages"],
        "sourceCatalogSha256": digest(original12.DEFAULT),
        "reconstructionSha256": digest(original12.RECONSTRUCTION),
    }
    require(all(profile["stages"][key] == stage for key, stage in active["stages"].items()
                if key not in ids), "Experimental profile changed an excluded stage")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    arguments = parser.parse_args()
    destination = arguments.output.resolve()
    require(destination not in (original12.DEFAULT.resolve(),
                                original12.RECONSTRUCTION.resolve()),
            "Refusing to replace production or preservation resources")
    profile = generate()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes((json.dumps(profile, ensure_ascii=False,
                                         separators=(",", ":")) + "\n").encode("utf-8"))
    require(json.loads(destination.read_text(encoding="utf-8")) == profile,
            "Generated UTF-8 profile failed round-trip verification")
    print(json.dumps({"status": "ORIGINAL_NORMAL_TEST_PROFILE_OK",
                      "changedStages": len(profile["experimentalProfile"]["changedStageIds"]),
                      "outputSha256": digest(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
