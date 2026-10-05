"""Build campaign encounter fixtures from preserved client tables and navigation.

Only the identities, levels, resources and navigation are original evidence.
Server wave composition, stats and combat AI were absent from the APK; this
generator deliberately labels their runnable replacement as local reconstruction.
The 16th chapter has no InstanceMobList rows and remains unsupported.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, deque
import copy
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import struct
import sys
import zipfile

sys.path.insert(0, r"D:\Environment\UnityTools\ProtocolBuffers\python")
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

PROJECT = Path(__file__).resolve().parents[1]
RECOVERY = Path(r"D:\Project\魔女兵器工程恢复")
ASSETS = Path(r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets")
CONFIG = RECOVERY / "原版/可读脚本与配置/配置/clientexel"
DESCRIPTORS = RECOVERY / "原版/原生代码/协议描述符/game-descriptors-complete.pb"
BUNDLES = RECOVERY / "原版/Android工程/assets/assetbundle/scene"


def table(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in list(csv.DictReader(f))[2:]
                if (r.get("ID") or "").isdigit()]


def integer(value, default=0):
    return int(value) if value else default


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def distance(a, b):
    return math.hypot(a[0] - b[0], a[2] - b[2])


def basket_class(path):
    files = list(descriptor_pb2.FileDescriptorSet.FromString(path.read_bytes()).file)
    pool = descriptor_pool.DescriptorPool()
    while files:
        before = len(files)
        for fd in files[:]:
            try:
                pool.Add(fd)
            except Exception:
                continue
            files.remove(fd)
        if len(files) == before:
            raise ValueError("Unresolved descriptors: " + str([f.name for f in files]))
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("combatmod.Basket"))


def parse_navigation(path):
    """A* 3.5.1 GridNode = penalty,u32 flags,Int3 position,u16 gridFlags.

    Verify byte counts, dimensions, walkable bits and reciprocal cardinal
    connection bits. Cardinal-only traversal avoids inferring diagonal corner
    rules and gives conservative connected components on the original grid.
    """
    graphs = []
    with zipfile.ZipFile(path) as z:
        metadata = json.loads(z.read("meta.json"))
        if metadata["version"] != "3.5.1":
            raise ValueError("Unsupported A* version in " + path.name)
        for index, typename in enumerate(metadata["typeNames"]):
            if typename != "Pathfinding.GridGraph":
                raise ValueError("Unsupported graph type: " + typename)
            info = json.loads(z.read(f"graph{index}.json"))
            raw = z.read(f"graph{index}_extra.binary")
            count = struct.unpack_from("<i", raw)[0]
            if count <= 0 or len(raw) != 4 + count * 22:
                raise ValueError("GridNode format mismatch in " + path.name)
            width = round(info["unclampedSize"]["x"] / info["nodeSize"])
            depth = round(info["unclampedSize"]["y"] / info["nodeSize"])
            if width * depth != count:
                raise ValueError("Grid dimensions mismatch in " + path.name)
            records = [struct.unpack_from("<IIiiiH", raw, 4 + i * 22)
                       for i in range(count)]
            nodes = {i: dict(point=[v / 1000 for v in r[2:5]], bits=r[5], penalty=r[0])
                     for i, r in enumerate(records) if r[1] & 1}
            neighbors = {}
            for i, node in nodes.items():
                found = []
                for bit, dx, dz, reciprocal in [(0, 0, -1, 2), (1, 1, 0, 3),
                                                (2, 0, 1, 0), (3, -1, 0, 1)]:
                    x, y = i % width + dx, i // width + dz
                    j = y * width + x
                    if (0 <= x < width and 0 <= y < depth and j in nodes
                            and node["bits"] & (1 << bit)
                            and nodes[j]["bits"] & (1 << reciprocal)):
                        if distance(node["point"], nodes[j]["point"]) > info["nodeSize"] * 1.01:
                            raise ValueError("Grid connection geometry mismatch")
                        found.append(j)
                neighbors[i] = found
            runtime_neighbors = {}
            for i, node in nodes.items():
                edges = []
                for bit, dx, dz, reciprocal in [(0, 0, -1, 2), (1, 1, 0, 3), (2, 0, 1, 0), (3, -1, 0, 1),
                                                (4, 1, -1, 6), (5, 1, 1, 7), (6, -1, 1, 4), (7, -1, -1, 5)]:
                    x, y = i % width + dx, i // width + dz
                    other = y * width + x
                    if (0 <= x < width and 0 <= y < depth and other in nodes
                            and node["bits"] & (1 << bit) and nodes[other]["bits"] & (1 << reciprocal)):
                        cost = round(info["nodeSize"] * 1000 * (math.sqrt(2) if bit >= 4 else 1))
                        edges.append((other, cost + nodes[other]["penalty"]))
                runtime_neighbors[i] = edges
            graphs.append(dict(index=index, info=info, nodes=nodes, neighbors=neighbors,
                               runtimeNeighbors=runtime_neighbors))
    return graphs


def scene_catalog(assets):
    guid_paths = {}
    for meta in (assets / "TextAsset").glob("mapinfo*.bytes.meta"):
        match = re.search(r"guid: (\w+)", meta.read_text(encoding="utf-8"))
        if match:
            guid_paths[match[1]] = meta.with_suffix("")
    scenes = {}
    for path in sorted((assets / "resources-/scene/map").glob("map_*.unity")):
        if "4test" in path.name:
            continue
        mid = int(re.match(r"map_(\d+)_", path.name)[1])
        text = path.read_text(encoding="utf-8")
        birth = re.search(r"brithPoint: \{x: ([^,]+), y: ([^,]+), z: ([^}]+)\}", text)
        nav = re.search(r"astarTextData:.*?guid: (\w+)", text)
        if not birth or not nav or nav[1] not in guid_paths:
            continue
        nav_path = guid_paths[nav[1]]
        item = dict(sceneName=path.stem, birth=[float(v) for v in birth.groups()],
                    sceneFile=path.name, sceneSha256=digest(path),
                    navigationFile=nav_path.name, navigationSha256=digest(nav_path),
                    graphs=parse_navigation(nav_path))
        if mid in scenes:
            raise ValueError("Ambiguous source map " + str(mid))
        scenes[mid] = item
    return scenes


def prepare_scene_geometry(scene, bundle):
    """Intersect original navigation with the actual scene floor and safe edges.

    A* heightCheck=false on preserved maps means Walkable alone does not prove
    that artwork contains floor at that coordinate (notably map 1027's void).
    Keep source graph positions intact, rather than inventing a map transform.
    """
    from audit_stage_geometry import FloorSurface, floor_triangles
    floor = FloorSurface(floor_triangles(bundle))
    if not floor.triangles:
        raise ValueError("Original scene has no readable rendered floor")
    graphs = []
    for original in scene["graphs"]:
        nodes = {i: n for i, n in original["nodes"].items()
                 if floor.footprint_height(n["point"]) is not None}
        neighbors = {i: [j for j in original["neighbors"][i]
                        if j in nodes and floor.segment_supported(n["point"], nodes[j]["point"])]
                     for i, n in nodes.items()}
        graph = {**original, "nodes": nodes, "neighbors": neighbors}
        graph["runtimeRoutes"] = RuntimeRoutes(original, graph, floor)
        graphs.append(graph)
    scene["geometryGraphs"] = graphs
    scene["floorSurface"] = floor
    scene["geometry"] = dict(bundleFile=bundle.name, bundleSha256=digest(bundle),
        method="original-scene-world-mesh-and-navigation-intersection",
        floorTriangles=len(floor.triangles), footprintRadius=floor.FOOTPRINT_RADIUS,
        footprintDirections=8, maxFloorHeightDelta=floor.MAX_HEIGHT_DELTA,
        maxFootprintHeightDelta=floor.FOOTPRINT_HEIGHT_DELTA, edgeSampleStep=.5,
        originalWalkableNodes=sum(len(g["nodes"]) for g in scene["graphs"]),
        floorSafeNodes=sum(len(g["nodes"]) for g in graphs),
        safeDirectedEdges=sum(sum(map(len, g["neighbors"].values())) for g in graphs))


class RuntimeRoutes:
    """Reject shortcuts in the original eight-neighbour graph, not just our filter.

    All equally shortest original routes must keep the floor footprint. This
    prevents a proof on the filtered graph hiding a shorter runtime void route.
    Costs use the preserved GridGraph node-size/diagonal costs and penalties.
    """
    def __init__(self, original, safe, floor):
        self.original, self.safe, self.floor = original, safe, floor
        self.edges = original["runtimeNeighbors"]
        self.reverse = {i: [] for i in self.edges}
        for i, edges in self.edges.items():
            for j, cost in edges:
                self.reverse[j].append((i, cost))
        self.distances, self.checked = {}, {}

    def distances_from(self, start, backwards=False):
        key = start, backwards
        if key not in self.distances:
            edges = self.reverse if backwards else self.edges
            distance_to, heap = {start: 0}, [(0, start)]
            while heap:
                current, i = heapq.heappop(heap)
                if distance_to[i] != current:
                    continue
                for j, cost in edges[i]:
                    if current + cost < distance_to.get(j, math.inf):
                        distance_to[j] = current + cost
                        heapq.heappush(heap, (current + cost, j))
            self.distances[key] = distance_to
        return self.distances[key]

    def supports(self, start, end):
        key = start, end
        if key in self.checked:
            return self.checked[key]
        forward, backward = self.distances_from(start), self.distances_from(end, True)
        total = forward.get(end)
        if total is None:
            self.checked[key] = False
            return False
        for i, distance_from_start in forward.items():
            if distance_from_start + backward.get(i, math.inf) != total:
                continue
            if i not in self.safe["nodes"]:
                self.checked[key] = False
                return False
            for j, cost in self.edges[i]:
                if distance_from_start + cost + backward.get(j, math.inf) == total:
                    if j not in self.safe["nodes"] or not self.floor.segment_supported(
                            self.original["nodes"][i]["point"], self.original["nodes"][j]["point"]):
                        self.checked[key] = False
                        return False
        self.checked[key] = True
        return True


def placements(scene, zone_counts):
    key = tuple(zone_counts)
    if key in scene.setdefault("placementCache", {}):
        return copy.deepcopy(scene["placementCache"][key])
    count = sum(zone_counts)
    candidates = []
    for g in scene["geometryGraphs"]:
        remaining = set(g["nodes"])
        while remaining:
            first = min(remaining)
            component = {first}
            pending = [first]
            remaining.remove(first)
            while pending:
                for j in g["neighbors"][pending.pop()]:
                    if j in remaining:
                        remaining.remove(j)
                        component.add(j)
                        pending.append(j)
            # Isolated decorative navigation islands cannot hold an encounter.
            if len(component) >= max(12, count * 3):
                candidates.extend((distance(g["nodes"][i]["point"], scene["birth"]),
                                   g["index"], i, g) for i in component)
    if not candidates:
        raise ValueError("No sufficiently large connected floor: " + scene["sceneName"])
    # A safe point can still be too close to a narrow bridge for five enemies
    # whose original runtime routes are all safe. Try the next source-nearest
    # safe entrance rather than disabling a map after one greedy failure.
    last_error = None
    for near, _, start, graph in sorted(candidates, key=lambda x: x[:3]):
        try:
            result = placements_from_start(scene, zone_counts, near, start, graph)
            scene["placementCache"][key] = result
            return copy.deepcopy(result)
        except ValueError as exc:
            last_error = exc
    raise ValueError("No reliable encounter layout after all floor candidates: " + str(last_error))


def placements_from_start(scene, zone_counts, near, start, graph):
    def traverse(begin):
        paths = {begin: 0}
        queue = deque([begin])
        while queue:
            i = queue.popleft()
            for j in graph["neighbors"][i]:
                if j not in paths:
                    paths[j] = paths[i] + 1
                    queue.append(j)
        return paths
    paths = traverse(start)
    # Source MapNode points are references, not proof of safe spawn placement.
    # Select only the scene-floor/navigation intersection, retaining the source
    # point and displacement as evidence rather than rewriting original assets.
    birth = graph["nodes"][start]["point"][:]
    birth[1] = round(birth[1] + 0.17, 3)
    anchors = [start]
    for zone in range(1, len(zone_counts)):
        previous = graph["nodes"][anchors[-1]]["point"]
        choices = [i for i in paths if len(graph["neighbors"][i]) >= 2
                   and all(distance(graph["nodes"][i]["point"], graph["nodes"][a]["point"]) >= 9
                           and graph["runtimeRoutes"].supports(a, i) for a in anchors)]
        if not choices:
            raise ValueError("No separate connected guide zone: " + scene["sceneName"])
        anchors.append(min(choices, key=lambda i: (abs(distance(graph["nodes"][i]["point"], previous) - 10),
                                                 -len(graph["neighbors"][i]), i)))
    entries = []
    for anchor in anchors:
        p = graph["nodes"][anchor]["point"][:]
        p[1] = round(p[1] + 0.17, 3)
        entries.append(p)
    chosen = []
    enemy_zones = []
    for zone, needed in enumerate(zone_counts):
        local_paths = traverse(anchors[zone])
        taken = 0
        for maximum_steps in (12, 20, 10000):
            available = [i for i in local_paths if local_paths[i] <= maximum_steps
                         and distance(graph["nodes"][i]["point"], birth) >= 3.0
                         and distance(graph["nodes"][i]["point"], entries[zone]) >= 3.0]
            available.sort(key=lambda i: (abs(distance(graph["nodes"][i]["point"], entries[zone]) - 6),
                                          -len(graph["neighbors"][i]), i))
            for i in available:
                p = graph["nodes"][i]["point"]
                if i not in chosen and all(distance(p, graph["nodes"][j]["point"]) >= 1.4
                                           for j in chosen) and all(graph["runtimeRoutes"].supports(j, i)
                                                                   for j in anchors + chosen):
                    chosen.append(i)
                    enemy_zones.append(zone)
                    taken += 1
                    if taken == needed:
                        break
            if taken == needed:
                break
        if taken != needed:
            raise ValueError("Not enough separated reachable spawn nodes: " + scene["sceneName"])
    points = [graph["nodes"][j]["point"] for j in chosen]
    return entries, points, dict(graphIndex=graph["index"],
                        entryNearestNode=start, entryDistance=round(near, 3),
                        originalMapNodeBirth=scene["birth"],
                        entryPolicy="nearest-connected-scene-floor-and-navigation-node-plus-0.17m",
                        geometry={**scene["geometry"],
                            "entryFloorHeights": [scene["floorSurface"].footprint_height(graph["nodes"][i]["point"]) for i in anchors],
                            "enemyFloorHeights": [scene["floorSurface"].footprint_height(p) for p in points]},
                        runtimeRoutePolicy="all-pairs-all-shortest-original-eight-neighbour-paths-have-floor-clearance",
                        runtimeRoutePairs=(len(anchors) + len(chosen)) * (len(anchors) + len(chosen) - 1) // 2,
                        zoneEntryNodeIndices=anchors, zoneEntryPoints=entries,
                        enemyZones=enemy_zones,
                        connectedWalkableNodes=len(paths), enemyNodeIndices=chosen,
                        enemyPathSteps=[paths[j] for j in chosen],
                        minimumPlayerDistance=round(min(distance(birth, p) for p in points), 3),
                        minimumEnemyDistance=round(min((distance(a, b) for k, a in enumerate(points)
                            for b in points[k + 1:]), default=0), 3))


def guide_requirements(config, assets, instances):
    """Read actual serialized lesson graphs, including original trigger-table hooks."""
    main_ids = {r["ID"] for r in instances}
    sources = {}
    # Current original table has no explicit guide references in these fields.
    # Fail on future unfamiliar references rather than silently generating a
    # single wave whose guide cannot finish.
    for row in instances:
        if row["instance_guide"] or row["battle_guide"]:
            raise ValueError("Explicit guide reference requires review: " + row["ID"])
    with (config / "lessontrigger.txt").open(encoding="utf-8-sig", newline="") as f:
        triggers = list(csv.DictReader(f))[2:]
    for row in triggers:
        sid = row.get("uiEvtParam")
        if row.get("uiEvtType") != "PreCombatBegin" or sid not in main_ids:
            continue
        path = assets / "resources-/guide/lesson" / ("lesson" + row["fileSuffixName"] + ".asset")
        text = path.read_text(encoding="utf-8")
        line = next(l for l in text.splitlines() if l.startswith("  _serializedGraph:"))
        raw = line.split(": ", 1)[1]
        if not raw.startswith("'") or not raw.endswith("'"):
            raise ValueError("Unsupported lesson serialization: " + path.name)
        graph = json.loads(raw[1:-1].replace("''", "'"))
        requirements, interactions, actions = [], [], []
        for node in graph["nodes"]:
            info = node.get("_roundInfo", {})
            if info.get("evtType") == "oncombatfield":
                event = int(info["triggerTypeKey"])
                if event // 1000 != 1 or not (1 <= event // 100 % 10 <= 9) or not (1 <= event % 100 <= 99):
                    raise ValueError("Unsupported guide combat event: " + str(event))
                requirements.append(event)
            elif info.get("triggerType") not in (None, "Empty"):
                interactions.append({k: info[k] for k in ("evtType", "triggerType", "triggerTypeKey") if k in info})
            for part in ("_b4cmdActionList", "_a4cmdActionList"):
                actions.extend(a for a in info.get(part, {}).get("actions", []) if not a.get("_isDisabled"))
        named_mobs = [a for a in actions if any(token in a.get("$type", "")
                      for token in ("MobTap", "CreateMob", "KillMob", "SetMob", "MoveMob"))]
        if named_mobs:
            raise ValueError("Named/interactive guide enemy requires explicit reconstruction: " + path.name)
        zones = [1] * max([event // 100 % 10 for event in requirements] or [1])
        for event in requirements:
            zone = event // 100 % 10 - 1
            zones[zone] = max(zones[zone], event % 100)
        sources[sid] = dict(lesson=path.name, sha256=digest(path), triggerRecId=int(row["recID"]),
            requiredCombatEvents=requirements, zoneWaveCounts=zones, interactions=interactions,
            namedMobRequirements=named_mobs,
            activeActionTypes=sorted({a.get("$type", "").split(".")[-1] for a in actions}),
            note="原教程拓扑约束；区域位置与怪物槽位分波为本地重建，未删改原教程交互。")
    return sources


def distribute_enemies(enemies, zone_wave_counts):
    total = sum(zone_wave_counts)
    if len(enemies) < total:
        raise ValueError("Not enough preserved enemy slots for guide waves")
    groups = [enemies[i * len(enemies) // total:(i + 1) * len(enemies) // total]
              for i in range(total)]
    zones, offset = [], 0
    for count in zone_wave_counts:
        zones.append(groups[offset:offset + count])
        offset += count
    return zones


def combat_info(base, enemies, health_floors=None):
    result = type(base)()
    result.CopyFrom(base)
    result.ClearField("MobInfos")
    result.ClearField("MobTypeInfos")
    used = set()
    for enemy in enemies:
        key = enemy["id"], enemy["rank"], enemy["level"]
        if key in used:
            continue
        used.add(key)
        template = 0 if enemy["rank"] >= 2 else min(1, len(base.MobInfos) - 1)
        mob = result.MobInfos.add()
        mob.CopyFrom(base.MobInfos[template])
        mob.ID, mob.CurType, mob.Level, mob.Model = key[0], key[1], key[2], enemy["model"]
        mob.MobTypeInfoNormal = mob.MobTypeInfoElite = mob.MobTypeInfoBoss = enemy["id"]
        # Local balance, not recovered server values. Use original mob levels
        # and a modest deterministic curve so later chapters differ in strength.
        multiplier = {1: 1, 2: 1.5, 3: 3}.get(enemy["rank"], 1)
        mob.Hp = int((500 + 120 * enemy["level"]) * multiplier)
        if health_floors and enemy["id"] in health_floors:
            mob.Hp = max(mob.Hp, health_floors[enemy["id"]])
        mob.PhysicalAttack = mob.MagicalAttack = 20 + 4 * enemy["level"]
        mob.PhysicalDefense = mob.MagicalDefense = 10 + enemy["level"]
        typ = result.MobTypeInfos.add()
        typ.CopyFrom(base.MobTypeInfos[template])
        typ.ID = enemy["id"]
    return result


def combat_json(base, instance, mob_row, scene, enemies, entries, points, grouped):
    level = copy.deepcopy(base)
    seconds = integer(mob_row["time"], 300)
    triggers = [dict(type="AllZoneClear", param=[]), dict(type="HeroPerish", param=[])]
    lose = [1, -1, -1, -1, -1, -1, -1, -1, -1]
    if seconds > 0:
        triggers.append(dict(type="TimeLimit", param=[str(seconds)]))
        lose[3] = 2
    level["QuestInfo"] = dict(code=0, optStr="", sec=seconds, Triggers=triggers,
        WinJudgement=[0, -1, -1, -1, -1, -1, -1, -1, -1], LoseJudgement=lose,
        BonusType=integer(mob_row["instBonusType"]),
        BonusParam=float(mob_row["intstBonusParam"] or 0),
        LevelObjectiveType=integer(mob_row["instObjectiveType"]))
    level["MapInfo"].update(sceneName=scene["sceneName"], isForceGuideMap=False,
        globalBuff=integer(mob_row["globalbuff"]), servantInitialEnergyRate=10000)
    monsters = []
    for i, (enemy, p) in enumerate(zip(enemies, points)):
        monsters.append(dict(name=f"Enemy_{i + 1}", opName=enemy["model"], givenName="",
            statID=f"{enemy['id']}-{enemy['rank']}-{enemy['level']}", appearType=0,
            PRS=[p[0], p[2], 180, 1], groupID=101,
            ai_config=dict(taunt_list_index=0, can_be_taunt=True, follow_target=""), tag=""))
    # Original guide graphs wait for concrete combat-field event IDs. Retain
    # those zone/wave indices and divide the original mob slots between them;
    # never invent additional mob types to fill a missing layout.
    zones, offset = [], 0
    for zi, wave_groups in enumerate(grouped):
        waves = []
        for wi, group in enumerate(wave_groups):
            wave_monsters = monsters[offset:offset + len(group)]
            offset += len(group)
            waves.append(dict(name=f"Wave_{wi}", showMode=0, spawnDelay=0 if wi == 0 else .6,
                sec=0, kill=999, NextWaveTriggers=[dict(type="WaveClear", param="")],
                SubWaves=[], monsters=wave_monsters))
        entry = entries[zi]
        # Native NextZoneArrow.GetNavPoint points players toward navP. The
        # original ColliderTrigger is a 10 x 1.5 x 1 box, not a radial trigger;
        # pointing at an enemy six metres from its centre can miss the band.
        zones.append(dict(name=f"Zone_{zi}", entryPR=entry + [0, 0, 0], navP=entry[:], walls=[],
            triggers=[dict(name="Start", opName="ColliderTrigger", PRS=[entry[0], entry[2], 0, 3],
                allowSkillPenetration=True, triggerCameraFocusOnFirstMob=False)], waves=waves))
    level["EnemyLayer"] = dict(levelID=instance["ID"],
        lvMin=min(e["level"] for e in enemies), lvMax=max(e["level"] for e in enemies),
        areas=[dict(name="Area_0", zones=zones)])
    level["ItemLayer"], level["NPCLayer"], level["InteractiveObjLayer"] = [], [], []
    return level


def generate(args):
    instances = [r for r in table(args.config / "instance.txt") if r["instance_type"] in ("2", "3")]
    mob_lists = {r["ID"]: r for r in table(args.config / "instancemoblist.txt")}
    mobs = {r["ID"]: r for r in table(args.config / "mob.txt")}
    guides = guide_requirements(args.config, args.assets, instances)
    map_points = {}
    for row in table(args.config / "mappoint.txt"):
        for part in row["point"].split("#"):
            values = part.split("|")
            if len(values) >= 2 and values[0].isdigit():
                map_points[values[0]] = dict(recordId=int(row["ID"]), fields=values,
                    predecessors=[int(p) for p in values[1].split(";") if p.isdigit() and int(p) > 0])
    scenes = scene_catalog(args.assets)
    for mid in sorted({integer(r["mapID"]) for sid, r in mob_lists.items()
                       if sid in {i["ID"] for i in instances}}):
        if mid not in scenes:
            continue
        try:
            prepare_scene_geometry(scenes[mid], args.bundles / (scenes[mid]["sceneName"] + ".ab"))
        except (ValueError, FileNotFoundError) as exc:
            scenes[mid]["geometryError"] = str(exc)
    responses = json.loads(args.responses.read_text(encoding="utf-8"))
    cls = basket_class(args.descriptors)
    base_info = cls.FromString(base64.b64decode(responses["/combat/mob/info"]["base64"]))
    base_json = json.loads(responses["/combat/mob/json"]["body"])
    stages = {}
    for instance in sorted(instances, key=lambda r: int(r["ID"])):
        sid = instance["ID"]
        row = mob_lists.get(sid)
        rewards = [dict(type=integer(instance[f"reward_type{i}"]),
                        id=integer(instance[f"reward_id{i}"]),
                        value=integer(instance[f"reward_value{i}"]),
                        count=integer(instance[f"reward_num{i}"]))
                   for i in range(1, 6) if integer(instance[f"reward_type{i}"]) > 0]
        item = dict(id=int(sid), chapterId=integer(instance["instance_set_attached"]),
            type=integer(instance["instance_type"]), supported=False, reason="",
            source=dict(instance=instance, mobList=row, mapPoint=map_points.get(sid)),
            rewards=rewards, staminaVictory=integer(instance["instance_stamina_victory"]),
            staminaEnter=integer(instance["instance_stamina_enter"]),
            recommendedLevel=integer(instance["instance_enter_level"]),
            order=integer(instance["instance_number"]),
            predecessorIds=map_points.get(sid, {}).get("predecessors", []),
            unlockStoryId=integer(instance["unlock_story"]), needStoryId=integer(instance["need_story"]))
        stages[sid] = item
        if row is None:
            item["reason"] = "原始 InstanceMobList 缺失；无法可靠确定敌人和地图，未伪造战斗数据。"
            continue
        mid = integer(row["mapID"])
        item["mapId"] = mid
        if mid not in scenes:
            item["reason"] = "原始地图出生点或导航资源缺失。"
            continue
        scene = scenes[mid]
        if scene.get("geometryError"):
            item["reason"] = "原地图地面数据无法可靠验证：" + scene["geometryError"]
            continue
        enemies = []
        for i in range(1, 6):
            mob_id = row.get(f"mob{i}")
            if not mob_id:
                continue
            if mob_id not in mobs or not mobs[mob_id]["model"]:
                raise ValueError("Mob identity/model missing: " + str(mob_id))
            enemies.append(dict(id=int(mob_id), rank=integer(row[f"mob{i}_type"]),
                                level=integer(row[f"mob{i}_lv"]), model=mobs[mob_id]["model"]))
        if not enemies:
            item["reason"] = "原始关卡未提供敌人。"
            continue
        guide = guides.get(sid)
        grouped = distribute_enemies(enemies, guide["zoneWaveCounts"] if guide else [1])
        try:
            entries, points, evidence = placements(scene, [sum(map(len, waves)) for waves in grouped])
        except ValueError as exc:
            item["reason"] = "原地图地面与导航交集不足以容纳战斗：" + str(exc)
            continue
        health_floors = {}
        if sid == "3110001002":
            # lesson00101 needs two skill interactions in its second zone.
            # Do not weaken its existing author-template target to the generic
            # 620 HP curve while upgrading wave support. This is a local
            # preservation floor, not a claim of original-server HP or immunity.
            target = grouped[1][0][0]
            original = next((m for m in base_info.MobInfos if m.ID == target["id"]), None)
            if original is None or original.Hp != 4000:
                raise ValueError("Preserved 1-2 tutorial-health evidence changed")
            health_floors[target["id"]] = original.Hp
            item["tutorialHealthFloor"] = dict(mobId=target["id"], minimumHp=original.Hp,
                source="author-original-stage-1-2-combat-mob-template",
                note="保留作者已运行模板的4000HP下限，防止通用生成降为620HP；不保证两次技能必然完成，仍需实机验证。")
        payload = combat_info(base_info, enemies, health_floors)
        item.update(supported=True, sceneName=scene["sceneName"],
            layoutSource="local-reconstruction-from-original-scene-and-navigation",
            localReconstruction=["按原教程事件分区分波或单区清敌波次", "敌人出生位置", "敌人属性曲线", "通用近战AI"],
            originalEvidence=["关卡编号与章节", "敌人种类与模型、等级、位阶", "地图与原MapNode参考点", "真实场景地面与导航交集及边缘余量", "原配置奖励与体力"],
            navigation={**{k: scene[k] for k in ("sceneFile", "sceneSha256", "navigationFile", "navigationSha256")},
                        **evidence, "entryPoint": entries[0], "enemyPoints": points},
            guide=guide, enemies=enemies, combatJson=combat_json(base_json, instance, row, scene, enemies, entries, points, grouped),
            combatMobInfo=dict(type="application/octet-stream", base64=base64.b64encode(payload.SerializeToString()).decode("ascii")))
        if health_floors:
            item["localReconstruction"].append("原1-2教程目标采用作者旧模板耐久下限")
        # Independent schema round-trip ensures every statID has its exact
        # protobuf monster (including original rank and configured level).
        check = cls.FromString(base64.b64decode(item["combatMobInfo"]["base64"]))
        keys = {(m.ID, m.CurType, m.Level) for m in check.MobInfos}
        if any((e["id"], e["rank"], e["level"]) not in keys for e in enemies):
            raise ValueError("Monster JSON/protobuf mismatch: " + sid)
    supported = [s for s in stages.values() if s["supported"]]
    summary = dict(total=len(stages), supported=len(supported), unsupported=len(stages) - len(supported),
                   normal=sum(s["type"] == 2 for s in supported),
                   elite=sum(s["type"] == 3 for s in supported),
                   maps=len({s["mapId"] for s in supported}),
                   guideStages=len(guides), guideCombatEvents=sum(len(g["requiredCombatEvents"]) for g in guides.values()),
                   zones=sum(len(s["combatJson"]["EnemyLayer"]["areas"][0]["zones"]) for s in supported),
                   waves=sum(len(z["waves"]) for s in supported for z in s["combatJson"]["EnemyLayer"]["areas"][0]["zones"]),
                   unsupportedIds=[s["id"] for s in stages.values() if not s["supported"]])
    catalog = dict(schemaVersion=1, description="基于原版资源的主线战斗本地重建；不声称恢复关服前服务端原始波次与数值。",
        inputs={p.name: digest(p) for p in [args.config / "instance.txt", args.config / "instancemoblist.txt", args.config / "mappoint.txt", args.config / "lessontrigger.txt",
                                           args.config / "mob.txt", args.descriptors, args.responses]},
        summary=summary, stages=stages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    # Read back to catch Windows encoding/path issues and output corruption.
    if json.loads(args.output.read_text(encoding="utf-8"))["summary"] != summary:
        raise ValueError("Catalog readback failed")
    print(json.dumps(summary, ensure_ascii=True))
    print("sha256=" + digest(args.output))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument("--assets", type=Path, default=ASSETS)
    parser.add_argument("--descriptors", type=Path, default=DESCRIPTORS)
    parser.add_argument("--bundles", type=Path, default=BUNDLES)
    parser.add_argument("--responses", type=Path, default=PROJECT / "resources/offline_responses.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "resources/stage_catalog.json")
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
