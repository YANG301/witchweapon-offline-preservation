"""Read-only audit of the original client evidence behind the battle profile.

This does not generate encounters or modify either catalog. In particular,
equal behavior-tree assets do not recover the server's per-monster tree IDs,
spell arguments, combat stats, wave topology, or spawn coordinates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RECOVERY = Path(r"D:\Project\魔女兵器工程恢复")
ASSET_ROOT = Path(r"C:\Project\魔女兵器工程恢复")
PROFILE = ROOT / "test-profiles/original-normal/stage_catalog.json"
DEFAULT = ROOT / "resources/stage_catalog.json"
ORIGINAL_CONFIG = RECOVERY / "原版/可读脚本与配置/配置"
ORIGINAL_BUNDLES = RECOVERY / "原版/Android工程/assets/assetbundle/config"

REFERENCE = re.compile(r"(?m)^  - \{fileID: \d+, guid: ([0-9a-f]+), type: \d+\}$")
REFERENCE_BLOCK = re.compile(
    r"(?ms)^  _objectReferences:\r?\n.*?(?=^  _deserializationFailed:)"
)
GUID = re.compile(r"(?m)^guid: ([0-9a-f]+)$")


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def behavior_assets(root: Path) -> tuple[dict[str, Path], dict[str, str]]:
    require(root.is_dir(), f"Missing exported behavior assets: {root}")
    files = {path.relative_to(root).as_posix(): path for path in root.rglob("*.asset")}
    guids: dict[str, str] = {}
    for relative, path in files.items():
        match = GUID.search(path.with_suffix(path.suffix + ".meta").read_text(encoding="utf-8"))
        require(match is not None, f"Behavior asset has no GUID: {path}")
        require(match.group(1) not in guids, f"Duplicate behavior GUID: {path}")
        guids[match.group(1)] = relative
    return files, guids


def logical_behavior(path: Path, guids: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    source = path.read_text(encoding="utf-8")
    references: list[str] = []
    for match in REFERENCE.finditer(source):
        guid = match.group(1)
        require(guid in guids, f"Unresolved behavior reference {guid}: {path}")
        references.append(guids[guid])
    body = REFERENCE_BLOCK.sub("  _objectReferences: <resolved separately>\n", source)
    return body.replace("\r\n", "\n"), tuple(references)


def audit_behavior(original: Path, offline: Path) -> dict[str, int]:
    first, first_guids = behavior_assets(original)
    second, second_guids = behavior_assets(offline)
    require(first.keys() == second.keys(), "Original and offline behavior asset sets differ")
    raw_changes = 0
    graph_count = 0
    for relative, path in first.items():
        other = second[relative]
        body, refs = logical_behavior(path, first_guids)
        other_body, other_refs = logical_behavior(other, second_guids)
        require((body, refs) == (other_body, other_refs),
                f"Behavior tree changed beyond export GUID remapping: {relative}")
        if digest(path) != digest(other):
            raw_changes += 1
        if "  _serializedGraph:" in body:
            graph_count += 1
    return {"behaviorAssets": len(first), "serializedGraphs": graph_count,
            "rawHashDifferencesOnlyFromGuidRemapping": raw_changes}


def table_header(path: Path) -> list[str]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle))


def audit_stage_references() -> dict[str, int | str]:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    active = json.loads(DEFAULT.read_text(encoding="utf-8"))
    marker = profile["experimentalProfile"]
    require(marker["testOnly"] and marker["id"] == "original-normal-local-reconstruction",
            "Expected isolated original-normal test profile")
    require(marker["sourceCatalogSha256"] == digest(DEFAULT),
            "The default catalog changed since experimental profile generation")
    identifiers = [str(value) for value in marker["changedStageIds"]]
    require(len(identifiers) == len(set(identifiers)) == 139,
            "Unexpected experimental stage membership")
    require(all(active["stages"][sid] != profile["stages"][sid] for sid in identifiers),
            "An experimental stage did not differ from the default fallback")
    rows = [profile["stages"][sid]["source"]["instance"] for sid in identifiers]
    config_names = [row["instance_mob_config"] for row in rows]
    require(all(config_names) and len(set(config_names)) == len(config_names),
            "Expected one named server encounter reference per stage")
    empty_zone_rows = sum(not any(row[f"instance_zone{i}"] for i in range(1, 4))
                          for row in rows)
    preserved_filenames = {path.stem.lower()
                           for root in (ORIGINAL_CONFIG, ORIGINAL_BUNDLES)
                           for path in root.rglob("*") if path.is_file()}
    named_payloads = sum(name.lower() in preserved_filenames for name in config_names)
    mob_columns = table_header(ORIGINAL_CONFIG / "clientexel/mob.txt")
    moblist_columns = table_header(ORIGINAL_CONFIG / "clientexel/instancemoblist.txt")
    require(mob_columns == ["ID", "channel_group", "name", "mob_stage", "description",
                            "description_battle", "model", "icon", "wideicon",
                            "data_name", "developer_name"],
            "Mob table now has new fields; review possible original combat evidence")
    require(not any("wave" in field.lower() or "spawn" in field.lower() or
                    "position" in field.lower() or "behavior" in field.lower()
                    for field in moblist_columns),
            "Mob list now has battle layout fields; review original evidence")
    return {"experimentalNormalStages": len(identifiers),
            "uniqueServerEncounterNames": len(set(config_names)),
            "encounterPayloadsInOriginalClientConfig": named_payloads,
            "stagesWithEmptyInstanceZoneFields": empty_zone_rows,
            "defaultCatalogSha256": digest(DEFAULT)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-behavior", type=Path,
                        default=ASSET_ROOT / "原版/Unity恢复/ExportedProject/Assets/resources-/behavior")
    parser.add_argument("--offline-behavior", type=Path,
                        default=ASSET_ROOT / "单机版/Unity恢复/ExportedProject/Assets/resources-/behavior")
    args = parser.parse_args()
    result = {**audit_behavior(args.original_behavior, args.offline_behavior),
              **audit_stage_references()}
    print(json.dumps({"status": "ORIGINAL_COMBAT_GAPS_AUDITED", **result},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
