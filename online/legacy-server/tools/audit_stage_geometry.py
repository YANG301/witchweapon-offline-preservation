"""Read-only cross-check of generated coordinates against original scene geometry.

Run using the existing UnityTools virtualenv. This never changes catalog or APKs.
The test establishes projected rendered floor coverage, not full gameplay safety:
it cannot prove camera visibility, dynamic collision, or native guide completion.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path

def floor_triangles(bundle):
    import UnityPy
    from UnityPy.helpers.MeshHelper import MeshHandler
    env = UnityPy.load(str(bundle))
    triangles = []
    transforms = {o.path_id: o.read_typetree() for o in env.objects if o.type.name == "Transform"}
    game_objects = {o.path_id: o.read_typetree() for o in env.objects if o.type.name == "GameObject"}
    renderers = {d["m_GameObject"]["m_PathID"]: d for o in env.objects if o.type.name == "MeshRenderer"
                 for d in [o.read_typetree()]}
    game_to_transform = {t["m_GameObject"]["m_PathID"]: i for i, t in transforms.items()}

    def active(transform):
        t = transforms[transform]
        if not game_objects[t["m_GameObject"]["m_PathID"]]["m_IsActive"]:
            return False
        parent = t["m_Father"]["m_PathID"]
        return active(parent) if parent else True

    def world_point(transform, point):
        t = transforms[transform]
        q = t["m_LocalRotation"]
        x, y, z, w = [q[k] for k in ("x", "y", "z", "w")]
        a, b, c = [point[i] * t["m_LocalScale"][k] for i, k in enumerate(("x", "y", "z"))]
        rotated = [(1 - 2*y*y - 2*z*z)*a + (2*x*y - 2*z*w)*b + (2*x*z + 2*y*w)*c,
                   (2*x*y + 2*z*w)*a + (1 - 2*x*x - 2*z*z)*b + (2*y*z - 2*x*w)*c,
                   (2*x*z - 2*y*w)*a + (2*y*z + 2*x*w)*b + (1 - 2*x*x - 2*y*y)*c]
        point = [rotated[i] + t["m_LocalPosition"][k] for i, k in enumerate(("x", "y", "z"))]
        parent = t["m_Father"]["m_PathID"]
        return world_point(parent, point) if parent else point

    meshes, mesh_cache = [], {}
    for obj in env.objects:
        if obj.type.name != "MeshFilter":
            continue
        filt = obj.read()
        go_id = filt.m_GameObject.m_PathID
        transform = game_to_transform[go_id]
        renderer = renderers.get(go_id)
        if not renderer or not renderer["m_Enabled"] or not active(transform):
            continue
        key = (filt.m_Mesh.m_FileID, filt.m_Mesh.m_PathID)
        if not key[1] or key[1] in (10202, 10206, 10207, 10208, 10209, 10210):
            continue
        try:
            if key not in mesh_cache:
                mesh_cache[key] = filt.m_Mesh.read()
            mesh = mesh_cache[key]
        except (FileNotFoundError, KeyError, ValueError):
            continue  # Unity built-in helper plane, not scene art.
        if mesh.m_Name.startswith("Combined Mesh (root: scene)"):
            # Static batching bakes scene-world coordinates. Read only the
            # submeshes referenced by enabled renderers; don't apply the model
            # transform twice, or count hidden objects as supporting ground.
            batch = renderer["m_StaticBatchInfo"]
            if renderer["m_StaticBatchRoot"]["m_PathID"] or not batch["subMeshCount"]:
                raise ValueError("Unreviewed static mesh root/submesh layout")
            submeshes = range(batch["firstSubMesh"], batch["firstSubMesh"] + batch["subMeshCount"])
            transform = None
        else:
            submeshes = range(len(mesh.m_SubMeshes))
        meshes.append((key, mesh, transform, submeshes))
    processed, seen = {}, set()
    for key, mesh, transform, submeshes in meshes:
        if key not in processed:
            data = MeshHandler(mesh)
            data.process()
            processed[key] = data
        data = processed[key]
        vertices = [world_point(transform, p) for p in data.m_Vertices] if transform else data.m_Vertices
        for submesh_index in submeshes:
            identity = key, transform, submesh_index
            if identity in seen:
                continue
            seen.add(identity)
            submesh = mesh.m_SubMeshes[submesh_index]
            if int(submesh.topology) != 0:
                continue
            first = submesh.firstByte // (2 if data.m_Use16BitIndices else 4)
            for offset in range(first, first + submesh.indexCount, 3):
                a, b, c = [vertices[i] for i in data.m_IndexBuffer[offset:offset + 3]]
                ux, uy, uz = [b[i] - a[i] for i in range(3)]
                vx, vy, vz = [c[i] - a[i] for i in range(3)]
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                norm = math.sqrt(nx * nx + ny * ny + nz * nz)
                if norm < 1e-9 or abs(ny) / norm < 0.9:
                    continue
                denominator = (b[2] - c[2]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[2] - c[2])
                if abs(denominator) > 1e-7:
                    triangles.append((a, b, c, denominator))
    return triangles


class FloorSurface:
    """Spatially indexed rendered floor; native navigation remains authoritative too."""
    MAX_HEIGHT_DELTA = .75
    FOOTPRINT_RADIUS = .6
    FOOTPRINT_HEIGHT_DELTA = .4
    CELL_SIZE = 4.0

    def __init__(self, triangles):
        self.triangles = triangles
        self.bins = defaultdict(list)
        self._footprints = {}
        for triangle in triangles:
            a, b, c, _ = triangle
            lo_x = math.floor(min(a[0], b[0], c[0]) / self.CELL_SIZE)
            hi_x = math.floor(max(a[0], b[0], c[0]) / self.CELL_SIZE)
            lo_z = math.floor(min(a[2], b[2], c[2]) / self.CELL_SIZE)
            hi_z = math.floor(max(a[2], b[2], c[2]) / self.CELL_SIZE)
            for x in range(lo_x, hi_x + 1):
                for z in range(lo_z, hi_z + 1):
                    self.bins[x, z].append(triangle)

    def heights(self, point):
        key = math.floor(point[0] / self.CELL_SIZE), math.floor(point[2] / self.CELL_SIZE)
        return ground_heights(self.bins.get(key, ()), point)

    def footprint_height(self, point):
        """Require a 0.6 m eight-direction footprint on the same rendered floor."""
        key = tuple(round(v, 4) for v in point)
        if key in self._footprints:
            return self._footprints[key]
        heights = [h for h in self.heights(point) if abs(point[1] - h) <= self.MAX_HEIGHT_DELTA]
        for height in sorted(heights, key=lambda h: abs(h - point[1])):
            for i in range(8):
                angle = i * math.pi / 4
                probe = [point[0] + self.FOOTPRINT_RADIUS * math.cos(angle), point[1],
                         point[2] + self.FOOTPRINT_RADIUS * math.sin(angle)]
                if not any(abs(h - point[1]) <= self.MAX_HEIGHT_DELTA and
                           abs(h - height) <= self.FOOTPRINT_HEIGHT_DELTA for h in self.heights(probe)):
                    break
            else:
                self._footprints[key] = height
                return height
        self._footprints[key] = None
        return None

    def segment_supported(self, first, second):
        if abs(first[1] - second[1]) > .25:
            return False
        steps = max(1, math.ceil(math.hypot(first[0] - second[0], first[2] - second[2]) / .5))
        return all(self.footprint_height([a + (b - a) * i / steps for a, b in zip(first, second)])
                   is not None for i in range(steps + 1))


def ground_heights(triangles, point):
    x, _, z = point
    heights = set()
    for a, b, c, den in triangles:
        u = ((b[2] - c[2]) * (x - c[0]) + (c[0] - b[0]) * (z - c[2])) / den
        v = ((c[2] - a[2]) * (x - c[0]) + (a[0] - c[0]) * (z - c[2])) / den
        if u >= -1e-5 and v >= -1e-5 and u + v <= 1.00001:
            heights.add(round(u * a[1] + v * b[1] + (1 - u - v) * c[1], 3))
    return sorted(heights)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path(__file__).resolve().parents[1] / "resources/stage_catalog.json")
    parser.add_argument("--bundles", type=Path, default=Path(r"D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\scene"))
    parser.add_argument("--map", type=int)
    args = parser.parse_args()
    catalog = json.loads(args.catalog.read_text("utf-8"))
    grouped = defaultdict(list)
    for stage in catalog["stages"].values():
        if stage["supported"] and (args.map is None or stage["mapId"] == args.map):
            grouped[stage["sceneName"]].append(stage)
    for scene, stages in grouped.items():
        triangles = floor_triangles(args.bundles / (scene + ".ab"))
        points = {}
        for stage in stages:
            nav = stage["navigation"]
            for role, values in (("entry", nav["zoneEntryPoints"]), ("enemy", nav["enemyPoints"])):
                for point in values:
                    key = tuple(point)
                    points.setdefault(key, []).append([stage["id"], role])
        failures = []
        clearances = []
        for point, uses in points.items():
            heights = ground_heights(triangles, point)
            near = [y for y in heights if -1.0 <= point[1] - y <= 1.0]
            if not near:
                failures.append(dict(point=point, renderedHeights=heights, usedBy=uses))
            else:
                clearances.append(round(min(abs(point[1] - y) for y in near), 3))
        print(json.dumps(dict(scene=scene, stages=len(stages), uniquePoints=len(points),
            projectedFloorTriangles=len(triangles), maxVerticalDistance=max(clearances, default=None),
            failures=failures), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
