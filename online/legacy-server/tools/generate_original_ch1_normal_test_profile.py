"""Opt-in chapter-one normal battles using preserved client evidence.

The APK proves each stage's map and five enemy slots, not its server-side
waves, spawn coordinates, attributes or AI. Those fields are copied from the
explicitly labelled local reconstruction. The simple production catalog is
read-only and remains the default/fallback.
"""
from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path

import generate_original_1_2_test_profile as original12

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "test-profiles/original-ch1-normal/stage_catalog.json"
STAGE_IDS = ("3110001004", "3110001006", "3110001008", "3110001010")
ORIGINAL_SKILL = b"Mob_NormalAttack_Melee_Physical"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_row(name: str, stage_id: str) -> dict[str, str]:
    path = original12.CONFIG / name
    with path.open(encoding="utf-8-sig", newline="") as handle:
        found = [entry for entry in list(csv.DictReader(handle))[2:]
                 if entry.get("ID") == stage_id]
    require(len(found) == 1, f"Missing or duplicate original {name} row {stage_id}")
    return found[0]


def validate_stage(stage_id: str, active: dict, restored: dict) -> None:
    require(stage_id in active["stages"] and stage_id in restored["stages"],
            f"Missing chapter-one stage {stage_id}")
    stage = restored["stages"][stage_id]
    simple = active["stages"][stage_id]
    require(stage["supported"] and stage["type"] == 2 and
            stage["chapterId"] == 3010001, f"Not a supported normal stage: {stage_id}")
    require(not stage.get("guide"), f"Tutorial stage requires separate review: {stage_id}")
    require(simple["mapId"] == 1010 and len(simple["enemies"]) == 1,
            f"Default fallback changed: {stage_id}")
    require(stage["source"]["instance"] == original_row("instance.txt", stage_id),
            f"Instance source changed: {stage_id}")
    mob_row = original_row("instancemoblist.txt", stage_id)
    require(stage["source"]["mobList"] == mob_row and
            stage["mapId"] == int(mob_row["mapID"]), f"Enemy/map source changed: {stage_id}")
    source_enemies = {(int(mob_row[f"mob{i}"]), int(mob_row[f"mob{i}_type"]),
                       int(mob_row[f"mob{i}_lv"])) for i in range(1, 6)
                      if mob_row.get(f"mob{i}")}
    require(len(source_enemies) == 5 and
            source_enemies == {(entry["id"], entry["rank"], entry["level"])
                               for entry in stage["enemies"]},
            f"Original enemy identities/ranks/levels changed: {stage_id}")
    wire_enemies = [mob for area in stage["combatJson"]["EnemyLayer"]["areas"]
                    for zone in area["zones"] for wave in zone["waves"]
                    for mob in wave["monsters"]]
    require({tuple(map(int, mob["statID"].split("-"))) for mob in wire_enemies}
            == source_enemies, f"Wire enemy slots changed: {stage_id}")
    scene = original12.ASSETS / "resources-/scene/map" / (stage["sceneName"] + ".unity")
    nav = original12.ASSETS / "TextAsset" / stage["navigation"]["navigationFile"]
    bundle = original12.BUNDLE.parent / (stage["sceneName"] + ".ab")
    require(scene.is_file() and nav.is_file() and bundle.is_file(),
            f"Original map files missing: {stage_id}")
    for path, recorded in ((scene, stage["navigation"]["sceneSha256"]),
                           (nav, stage["navigation"]["navigationSha256"]),
                           (bundle, stage["navigation"]["geometry"]["bundleSha256"])):
        require(digest(path) == recorded, f"Original map hash changed: {path}")
    mob_wire = base64.b64decode(stage["combatMobInfo"]["base64"], validate=True)
    require(ORIGINAL_SKILL in mob_wire and b"Offline_" not in mob_wire and
            ORIGINAL_SKILL in original12.SPELLS.read_bytes(),
            f"Enemy skill is not preserved in original APK: {stage_id}")
    require(stage["localReconstruction"] and stage["navigation"]["enemyPoints"],
            f"Missing local wave/spawn provenance: {stage_id}")


def generate() -> dict:
    active = json.loads(original12.DEFAULT.read_text(encoding="utf-8"))
    reconstruction = json.loads(original12.RECONSTRUCTION.read_text(encoding="utf-8"))
    require(active.get("mode") == "simple-campaign-v1" and
            len(active["stages"]) == len(reconstruction["stages"]) == 235,
            "The production fallback or reconstructed catalog changed")
    require(digest(original12.RECONSTRUCTION) == original12.RECONSTRUCTION_SHA256 and
            active.get("restorationSource", {}).get("sha256") == original12.RECONSTRUCTION_SHA256,
            "Preserved reconstruction changed; review source evidence")
    profile = copy.deepcopy(active)
    for stage_id in STAGE_IDS:
        validate_stage(stage_id, active, reconstruction)
        profile["stages"][stage_id] = copy.deepcopy(reconstruction["stages"][stage_id])
    profile["experimentalProfile"] = {
        "id": "original-ch1-normal-local-reconstruction", "testOnly": True,
        "changedStageIds": [int(stage_id) for stage_id in STAGE_IDS],
        "originalEvidence": ["stage and map IDs", "original scene and navigation",
                             "enemy IDs, ranks and levels", "enemy skill template"],
        "localReconstruction": ["waves", "spawn coordinates", "stats", "AI"],
        "sourceCatalogSha256": digest(original12.DEFAULT),
        "reconstructionSha256": digest(original12.RECONSTRUCTION),
    }
    require(all(profile["stages"][key] == stage for key, stage in active["stages"].items()
                if key not in STAGE_IDS), "Experimental profile changed an unrelated stage")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    destination = args.output.resolve()
    require(destination not in (original12.DEFAULT.resolve(),
                                original12.RECONSTRUCTION.resolve()),
            "Refusing to overwrite the production or preservation catalog")
    profile = generate()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(profile, ensure_ascii=False, separators=(",", ":")) + "\n",
                           encoding="utf-8")
    require(json.loads(destination.read_text(encoding="utf-8")) == profile,
            "UTF-8 round trip failed")
    print(json.dumps({"status": "ORIGINAL_CH1_NORMAL_TEST_PROFILE_OK",
                      "stages": [int(i) for i in STAGE_IDS],
                      "outputSha256": digest(destination)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
