"""Make an isolated mainline 1-2 battle profile from preserved evidence.

The source catalog already labels server waves, positions and stats as local
reconstruction. This tool does not claim they are the shutdown-era server data.
The normal simple-campaign catalog is read-only and remains the production
default. The generated catalog is loaded only when explicitly placed first on
the Java classpath for a disposable local test server.
"""
from __future__ import annotations

import argparse
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ROOT / "resources"
DEFAULT = RESOURCES / "stage_catalog.json"
RECONSTRUCTION = RESOURCES / "stage_catalog_reconstruction.json"
OUTPUT = ROOT / "test-profiles" / "original-1-2" / "stage_catalog.json"
RESTORED = Path(r"D:\Project\魔女兵器工程恢复\原版")
CONFIG = RESTORED / "可读脚本与配置/配置/clientexel"
SPELLS = RESTORED / "可读脚本与配置/配置/xmlconf/skill/spells.xml"
ASSETS = Path(r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets")
BUNDLE = RESTORED / "Android工程/assets/assetbundle/scene/map_1004_metroplatform.ab"
STAGE_ID = "3110001002"
RECONSTRUCTION_SHA256 = "90a8cd2a161d98362b0b1a7046e4a6c0d7d56378346463f9ba329fcaa7516e9e"
SCENE_SHA256 = "a9357d8badabc75fab4671dfb3cdb06ff27e58632bdae5d384b798bb8d25afd6"
NAV_SHA256 = "02eea2c2b289231c952d127c205f5d27aff1f9898411f10f3fc4c50dcd20e62b"
BUNDLE_SHA256 = "6a4f052fdec71e09c146ba34a9552849b2d357c241308259f0d4e79d1603d26d"
ORIGINAL_MOB_SKILL = b"Mob_NormalAttack_Melee_Physical"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def row(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))[2:]
    found = [item for item in rows if item.get("ID") == STAGE_ID]
    require(len(found) == 1, "Original table must contain exactly one 1-2 row: " + str(path))
    return found[0]


def validate_sources(active: dict, reconstruction: dict) -> dict:
    require(active.get("mode") == "simple-campaign-v1", "The default simple campaign changed")
    require(len(active["stages"]) == 235, "The default campaign is incomplete")
    require(len(reconstruction["stages"]) == 235, "The reconstructed evidence is incomplete")
    require(sha256(RECONSTRUCTION) == RECONSTRUCTION_SHA256,
            "Pinned reconstruction changed; review it before generating an experimental profile")
    require(active.get("restorationSource", {}).get("sha256") == RECONSTRUCTION_SHA256,
            "The default catalog points to different restoration evidence")
    old = reconstruction["stages"][STAGE_ID]
    require(old["source"]["instance"] == row(CONFIG / "instance.txt"),
            "Reconstructed 1-2 Instance row differs from original")
    require(old["source"]["mobList"] == row(CONFIG / "instancemoblist.txt"),
            "Reconstructed 1-2 mob row differs from original")
    mob_row = old["source"]["mobList"]
    require(mob_row["mapID"] == "1004" and old["mapId"] == 1004,
            "Original 1-2 should use map 1004")
    require(old["sceneName"] == "map_1004_metroplatform" and
            old["combatJson"]["MapInfo"]["sceneName"] == old["sceneName"],
            "Scene reference differs from original map 1004")
    scene = ASSETS / "resources-/scene/map/map_1004_metroplatform.unity"
    nav = ASSETS / "TextAsset/mapinfo_1004_metroplatform.bytes"
    evidence = old["navigation"]
    for path, expected, recorded in (
        (scene, SCENE_SHA256, evidence["sceneSha256"]),
        (nav, NAV_SHA256, evidence["navigationSha256"]),
        (BUNDLE, BUNDLE_SHA256, evidence["geometry"]["bundleSha256"]),
    ):
        require(sha256(path) == expected == recorded, "Original map evidence mismatch: " + str(path))
    expected_enemies = {
        (int(mob_row[f"mob{i}"]), int(mob_row[f"mob{i}_type"]), int(mob_row[f"mob{i}_lv"]))
        for i in range(1, 6) if mob_row.get(f"mob{i}")
    }
    actual_enemies = {(entry["id"], entry["rank"], entry["level"]) for entry in old["enemies"]}
    require(len(expected_enemies) == 2 and actual_enemies == expected_enemies,
            "Reconstructed enemy identities differ from the original table")
    monsters = [monster for area in old["combatJson"]["EnemyLayer"]["areas"]
                for zone in area["zones"] for wave in zone["waves"]
                for monster in wave["monsters"]]
    require({tuple(map(int, monster["statID"].split("-"))) for monster in monsters}
            == expected_enemies, "Wire battle layout changed the original enemy slots")
    mob_info = base64.b64decode(old["combatMobInfo"]["base64"], validate=True)
    require(ORIGINAL_MOB_SKILL in mob_info and ORIGINAL_MOB_SKILL in SPELLS.read_bytes(),
            "The test enemy's skill must exist in the original spell bundle")
    require(b"Offline_" not in mob_info, "1-2 enemy still refers to an author-only skill")
    require(old["localReconstruction"] and evidence["enemyPoints"],
            "Missing explicit locally reconstructed wave and spawn labels")
    return old


def generate() -> dict:
    active = json.loads(DEFAULT.read_text(encoding="utf-8"))
    reconstruction = json.loads(RECONSTRUCTION.read_text(encoding="utf-8"))
    restored_stage = validate_sources(active, reconstruction)
    require(active["stages"][STAGE_ID]["mapId"] == 1010,
            "The default 1-2 stage is no longer the expected simple placeholder")
    profile = copy.deepcopy(active)
    profile["stages"][STAGE_ID] = copy.deepcopy(restored_stage)
    profile["experimentalProfile"] = {
        "id": "original-1-2-local-reconstruction",
        "testOnly": True,
        "changedStageIds": [int(STAGE_ID)],
        "originalEvidence": ["map", "scene", "navigation", "enemy IDs and ranks", "enemy skill template"],
        "localReconstruction": ["waves", "spawn coordinates", "stats", "AI", "role skill mapping"],
        "sourceCatalogSha256": sha256(DEFAULT),
        "reconstructionSha256": sha256(RECONSTRUCTION),
    }
    require(len(profile["stages"]) == len(active["stages"]), "Stage count changed")
    require(all(profile["stages"][key] == value for key, value in active["stages"].items()
                if key != STAGE_ID), "The test profile modified another stage")
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT,
                        help="Test-only stage_catalog.json; production resources are protected")
    args = parser.parse_args()
    output = args.output.resolve()
    require(output != DEFAULT.resolve() and output != RECONSTRUCTION.resolve(),
            "Refusing to replace the active or preserved catalog")
    profile = generate()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, ensure_ascii=False, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    require(json.loads(output.read_text(encoding="utf-8"))["experimentalProfile"]["testOnly"],
            "Generated test marker did not survive UTF-8 round-trip")
    print(json.dumps({"output": str(output), "sha256": sha256(output), "changedStage": STAGE_ID,
                      "map": profile["stages"][STAGE_ID]["mapId"],
                      "enemyCount": len(profile["stages"][STAGE_ID]["enemies"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
