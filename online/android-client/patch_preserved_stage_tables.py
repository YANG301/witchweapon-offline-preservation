"""Restore only verified original stage previews, preserving unrelated fixes.

The caller supplies the active MobList bundle (APK plus signed overlays).  This
module neither selects a release nor writes/signs/publishes one.  Only the 247
stage IDs with source layouts are changed; missing layouts and all tutorial IDs
remain byte-for-byte unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path

from patch_feature_level_gates import _csv_tree
from patch_simple_campaign import _patch

PROJECT = Path(__file__).resolve().parents[1]
COVERAGE = PROJECT / "参考资料/战斗数据核查/关卡覆盖核对.json"
LOGICAL = "assetbundle/config/clientexel/instancemoblist.ab"
INSTANCE_LOGICAL = "assetbundle/config/clientexel/instance.ab"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def numeric_rows(text: str):
    lines = text.splitlines()
    header = lines[0].split(",")
    if header[0] != "ID" or len(set(header)) != len(header):
        raise ValueError("Malformed stage table header")
    rows = defaultdict(list)
    for line in lines[1:]:
        cells = line.split(",")
        if not cells[0].isdigit():
            continue
        if len(cells) > len(header):
            raise ValueError("Too many stage table columns: " + cells[0])
        rows[cells[0]].append(dict(zip(header, cells + [""] * (len(header) - len(cells)))))
    return header, rows


def prepare_rows(coverage_path: Path = COVERAGE):
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    selected = [row for row in coverage["coverage"] if row["selectedPaths"]]
    if len(selected) != 247 or len(coverage["coverage"]) != 297:
        raise ValueError("Unreviewed preserved stage coverage")
    layout_index = {row["path"]: row for row in coverage["layouts"]}
    targets, evidence = {}, []
    with zipfile.ZipFile(coverage["sourceArchive"]) as source:
        raw = source.read("assets/" + LOGICAL)
        _, _, _, original, _ = _csv_tree(raw, "InstanceMobList")
        header, rows = numeric_rows(original)
        for stage in selected:
            identity = stage["stageID"]
            if identity.startswith("315"):
                raise ValueError("Tutorial must never be a restoration target")
            layouts = []
            for path in stage["selectedPaths"]:
                blob = source.read(path)
                if sha(blob) != layout_index[path]["sha256"]:
                    raise ValueError("Preserved source layout changed: " + path)
                layouts.append(json.loads(blob))
            scenes = {layout["MapInfo"]["sceneName"] for layout in layouts}
            if len(scenes) != 1:
                raise ValueError("Ambiguous stage scene: " + identity)
            scene = next(iter(scenes))
            match = re.fullmatch(r"map_([0-9]+)_[a-z0-9_]+", scene)
            if match is None:
                raise ValueError("Not a supported source scene: " + scene)
            map_id = match.group(1)
            candidates = [row for row in rows[identity] if row["mapID"] == map_id]
            if not candidates:
                raise ValueError("Original preview has no matching scene: " + identity)
            # The source table has four duplicate chapter-12 IDs. Prefer the
            # candidate whose displayed enemy references match the chosen JSON.
            known_stats = set()
            for path in stage["selectedPaths"]:
                known_stats.update(layout_index[path]["statIDs"])
            def score(row):
                return sum("-".join((row.get("mob" + str(i), ""),
                                     row.get("mob" + str(i) + "_type", ""),
                                     row.get("mob" + str(i) + "_lv", ""))) in known_stats
                           for i in range(1, 6))
            expected = max(candidates, key=score)
            targets[identity] = expected
            evidence.append({"stageID": identity, "mode": stage["mode"],
                             "sceneName": scene, "mapID": map_id,
                             "selectedPaths": stage["selectedPaths"],
                             "sourcePreviewCandidates": len(candidates),
                             "sweepType": expected["instBonusType"],
                             "sweepParameter": expected["intstBonusParam"]})
    return header, targets, evidence


def patch_preview_text(text: str, source_header, targets) -> str:
    lines = text.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n").split(",")
    if header != source_header:
        raise ValueError("MobList field layout differs from reviewed source")
    seen, output = set(), []
    for line in lines:
        content = line.rstrip("\r\n")
        identity = content.split(",", 1)[0]
        if identity in targets:
            if identity in seen:
                raise ValueError("Active preview contains a duplicate target: " + identity)
            seen.add(identity)
            expected = ",".join(targets[identity][name] for name in header)
            line = expected + line[len(content):]
        output.append(line)
    if seen != set(targets):
        raise ValueError("Active preview missing preserved stage IDs")
    result = "".join(output)
    before = [line for line in lines if line.split(",", 1)[0] not in targets]
    after = [line for line in result.splitlines(keepends=True)
             if line.split(",", 1)[0] not in targets]
    if before != after:
        raise ValueError("An unrelated stage/guide/fallback changed")
    return result


def patch_bundle(raw: bytes, coverage_path: Path = COVERAGE):
    header, targets, evidence = prepare_rows(coverage_path)
    result = _patch(raw, "InstanceMobList", lambda text: patch_preview_text(text, header, targets))
    return result, evidence


def validate_instance(raw: bytes, coverage_path: Path = COVERAGE):
    """Prove current Instance config names/gates are retained; do not replace it."""
    _, _, _, text, _ = _csv_tree(raw, "Instance")
    _, rows = numeric_rows(text)
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    for stage in coverage["coverage"]:
        if not stage["selectedPaths"]:
            continue
        identity = stage["stageID"]
        if len(rows[identity]) != 1:
            raise ValueError("Active Instance ID is missing/ambiguous: " + identity)
        row = rows[identity][0]
        if row["instance_mob_config"] != stage["currentConfigName"]:
            raise ValueError("Instance routing is not the reviewed baseline: " + identity)
        if int(row["instance_enter_level"] or "0") > 1:
            raise ValueError("All-open entry gate would be lost: " + identity)
    return {"sha256": sha(raw), "changed": False, "verifiedStageCount": 247}
