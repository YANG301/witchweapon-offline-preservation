"""Build unsigned, local original-stage AB payloads from an explicit baseline.

No APK rebuild, installation, signing-key read, release mutation, or deployment.
Run with the installed APK and the exact signed release snapshot/blobs.  Output
patch-plan.json describes only the new overlays; compose them into a copy of
the chosen complete release before the separate reviewed signing step.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import json
from pathlib import Path
import re
import zipfile

import UnityPy
import patch_preserved_stage_tables as tables

PROJECT = tables.PROJECT
OUTPUT = PROJECT / "热更新测试/原始关卡候选"
MANIFEST_LOGICAL = "assetbundle/config/preserved_stage_manifest.ab"
LUA_LOGICAL = "assetbundle/lua/lua.ab"
MAPS = ("scene/map_1001_mallsunset.ab", "scene/map_1013_groofbroken.ab",
        "scene/map_1016_factorycrossing.ab", "scene/map_1019_wharfroad.ab",
        "scene/map_1027_spacewalk.ab")
SHARED_GOLD = "assets/resources/characters/effects/gold.ab"
LUA_SOURCE = PROJECT / "android-client/lua/init-preserved-stage-manifest.lua"
LUA_MARKER = "-- WWR preserved stage dependency manifest v1."
LUA_DLL = Path(r"D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets\Plugins\x86_64\tolua.dll")


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def check_lua(script):
    dll = ctypes.CDLL(str(LUA_DLL))
    dll.luaL_newstate.restype = ctypes.c_void_p
    dll.luaL_loadbuffer.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                  ctypes.c_size_t, ctypes.c_char_p]
    dll.luaL_loadbuffer.restype = ctypes.c_int
    dll.lua_close.argtypes = [ctypes.c_void_p]
    state = dll.luaL_newstate()
    try:
        raw = script.encode("utf-8")
        if dll.luaL_loadbuffer(state, raw, len(raw), b"init.lua") != 0:
            raise ValueError("Lua failed original ToLua parser validation")
    finally:
        dll.lua_close(state)


def manifest_tree(raw):
    env = UnityPy.load(raw)
    matches = [obj for obj in env.objects if obj.type.name == "AssetBundleManifest"]
    if len(matches) != 1:
        raise ValueError("Expected one central AssetBundleManifest")
    obj = matches[0]
    return env, obj, obj.read_typetree()


def bundle_serialized_files(raw):
    env = UnityPy.load(raw)
    names, externals = set(), []
    for container in env.files.values():
        if not hasattr(container, "files"):
            continue
        for name, item in container.files.items():
            names.add(name.lower())
            if hasattr(item, "externals"):
                externals.extend(ext.path.lower() for ext in item.externals)
    return names, externals


def shared_bundle_equivalent(left, right):
    # The gold prefab's 17 actual objects retain identical IDs/raw bytes; only
    # its dependency names/Unity bundle wrapper changed during 2020 packing.
    def objects(raw):
        return {o.path_id: (o.type.name, sha(o.get_raw_data()))
                for o in UnityPy.load(raw).objects if o.type.name != "AssetBundle"}
    return objects(left) == objects(right)


def patch_lua(raw):
    script = LUA_SOURCE.read_text(encoding="utf-8")
    env = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    targets = [o for o in env.objects if o.type.name == "TextAsset"
               and o.read_typetree().get("m_Name") == "init.lua"]
    if len(targets) != 1:
        raise ValueError("Expected one active init.lua")
    obj = targets[0]
    tree = obj.read_typetree()
    original = tree["m_Script"]
    as_bytes = isinstance(original, bytes)
    original = original.decode("utf-8") if as_bytes else original
    if LUA_MARKER in original:
        if original.count(LUA_MARKER) != 1 or not original.endswith(script):
            raise ValueError("Unreviewed preserved-stage Lua module already present")
        return raw
    combined = original + "\n\n" + script
    check_lua(combined)
    tree["m_Script"] = combined.encode("utf-8") if as_bytes else combined
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    after = UnityPy.load(result)
    hashes = {o.path_id: sha(o.get_raw_data()) for o in after.objects}
    if set(before) != set(hashes) or {p for p in before if before[p] != hashes[p]} != {obj.path_id}:
        raise ValueError("An unrelated Lua object changed")
    actual = next(o for o in after.objects if o.path_id == obj.path_id).read_typetree()["m_Script"]
    if isinstance(actual, bytes):
        actual = actual.decode("utf-8")
    if actual != combined or not actual.startswith(original):
        raise ValueError("An existing Lua repair was lost")
    return result


def prepare_maps(source, active_read):
    original_manifest_raw = source.read("assets/assetbundle/assetbundle")
    current_manifest_raw = active_read("assetbundle/assetbundle")
    _, _, old = manifest_tree(original_manifest_raw)
    env, target, current = manifest_tree(current_manifest_raw)
    before_objects = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    old_names, old_infos = dict(old["AssetBundleNames"]), dict(old["AssetBundleInfos"])
    names, infos = dict(current["AssetBundleNames"]), dict(current["AssetBundleInfos"])
    old_ids = {name: i for i, name in old_names.items()}
    ids = {name: i for i, name in names.items()}
    needed = set(MAPS)
    queue = list(MAPS)
    # Preserve the current shared gold prefab and current dependency closure.
    # All other 2019 dependencies have distinct debug/* names in this baseline.
    while queue:
        name = queue.pop()
        for old_index in old_infos[old_ids[name]]["AssetBundleDependencies"]:
            dependency = old_names[old_index]
            if dependency not in needed:
                needed.add(dependency)
                queue.append(dependency)
    # Old map files directly reference the old gold texture CAB even though it
    # was listed as a transitive dependency of gold in the 2019 manifest. Keep
    # that texture under its distinct old name and add it to these five maps.
    shared_extra = set()
    queue = [SHARED_GOLD]
    while queue:
        name = queue.pop()
        for index in old_infos[old_ids[name]]["AssetBundleDependencies"]:
            dependency = old_names[index]
            if dependency not in shared_extra:
                shared_extra.add(dependency)
                queue.append(dependency)
    needed.discard(SHARED_GOLD)
    old_gold = source.read("assets/assetbundle/" + SHARED_GOLD)
    current_gold = active_read("assetbundle/" + SHARED_GOLD)
    if not shared_bundle_equivalent(old_gold, current_gold):
        raise ValueError("Shared gold prefab objects changed; do not overwrite globally")
    payload, sources = {}, []
    source_names, source_externals = set(), []
    for name in sorted(needed):
        raw = source.read("assets/assetbundle/" + name)
        if name in ids and name not in MAPS:
            if raw != active_read("assetbundle/" + name):
                raise ValueError("An unrelated existing dependency would be overwritten: " + name)
            continue
        payload["assetbundle/" + name] = raw
        serialized, externals = bundle_serialized_files(raw)
        source_names.update(serialized)
        source_externals.extend(externals)
        sources.append({"path": "assetbundle/" + name, "bytes": len(raw),
                        "sha256": sha(raw), "archiveMember": "assets/assetbundle/" + name})
        if name not in ids:
            identity = max(names) + 1
            ids[name] = identity
            names[identity] = name
    current_dependencies = {SHARED_GOLD}
    queue = [SHARED_GOLD]
    while queue:
        name = queue.pop()
        for index in infos[ids[name]]["AssetBundleDependencies"]:
            dependency = names[index]
            if dependency not in current_dependencies:
                current_dependencies.add(dependency)
                queue.append(dependency)
    for name in sorted(current_dependencies):
        serialized, _ = bundle_serialized_files(active_read("assetbundle/" + name))
        source_names.update(serialized)
    unresolved = sorted({path for path in source_externals if path.startswith("archive:/")
                         and path.rsplit("/", 1)[-1] not in source_names})
    if unresolved:
        raise ValueError("Original map CAB dependencies unresolved: " + str(unresolved))
    proposed = copy.deepcopy(current)
    for name in sorted(needed):
        info = copy.deepcopy(old_infos[old_ids[name]])
        info["AssetBundleDependencies"] = [ids[old_names[i]]
                                          for i in info["AssetBundleDependencies"]]
        if name in MAPS:
            info["AssetBundleDependencies"] = sorted(set(info["AssetBundleDependencies"])
                                                     | {ids[n] for n in shared_extra})
        infos[ids[name]] = info
    proposed["AssetBundleNames"] = sorted(names.items())
    proposed["AssetBundleInfos"] = sorted(infos.items())
    target.save_typetree(proposed)
    # This manifest is loaded alongside the original one. Reusing its CAB name
    # would make Unity reject a second bundle containing the same serialized
    # file, even though the outer logical filename has an .ab suffix.
    wrappers = [o for o in env.objects if o.type.name == "AssetBundle"]
    if len(wrappers) != 1 or len(env.file.files) != 1:
        raise ValueError("Unexpected central manifest bundle wrapper")
    wrapper = wrappers[0]
    wrapper_tree = wrapper.read_typetree()
    wrapper_tree["m_Name"] = "config/preserved_stage_manifest.ab"
    wrapper_tree["m_AssetBundleName"] = "config/preserved_stage_manifest.ab"
    wrapper.save_typetree(wrapper_tree)
    old_cab, serialized = next(iter(env.file.files.items()))
    new_cab = "CAB-" + sha(json.dumps(proposed, sort_keys=True).encode("utf-8"))[:32]
    if old_cab.lower() == new_cab.lower():
        raise ValueError("Preserved manifest must have a unique serialized file")
    serialized.name = new_cab
    env.file.files = {new_cab: serialized}
    merged = env.file.save(packer="original")
    reopened, _, actual = manifest_tree(merged)
    if actual != proposed:
        raise ValueError("Merged dependency manifest round-trip mismatch")
    after_objects = {o.path_id: sha(o.get_raw_data()) for o in reopened.objects}
    if set(after_objects) != set(before_objects) or {
            p for p in before_objects if before_objects[p] != after_objects[p]} != {target.path_id, wrapper.path_id}:
        raise ValueError("An unrelated central manifest object changed")
    if set(reopened.file.files) != {new_cab}:
        raise ValueError("Preserved manifest serialized identity did not round-trip")
    before_names, before_infos = dict(current["AssetBundleNames"]), dict(current["AssetBundleInfos"])
    for identity, name in before_names.items():
        if names[identity] != name or (name not in MAPS and infos[identity] != before_infos[identity]):
            raise ValueError("An unrelated dependency entry changed: " + name)
    payload[MANIFEST_LOGICAL] = merged
    return payload, {"mapCount": len(MAPS), "oldMapBytes": sum(len(payload["assetbundle/" + n]) for n in MAPS),
                     "addedDependencyBundles": len(needed - set(MAPS)),
                     "addedDependencyBytes": sum(len(payload["assetbundle/" + n]) for n in needed - set(MAPS)),
                     "resolvedArchiveReferences": len(set(source_externals)),
                     "unresolvedArchiveReferences": unresolved, "currentGoldPreserved": True,
                     "centralManifestOnlySelectedMapsChanged": True,
                     "oldManifestSha256": sha(original_manifest_raw),
                     "baseManifestSha256": sha(current_manifest_raw), "sources": sources,
                     "baseCAB": old_cab, "candidateCAB": new_cab,
                     "runtimeActivation": "Lua sets only GLoader._manifest from preserved_stage_manifest.ab",
                     "runtimeValidated": False}


def build(base_apk: Path, base_manifest: Path, blobs: Path,
          output: Path = OUTPUT, restore_maps: bool = True):
    raw_manifest = base_manifest.read_bytes()
    snapshot = json.loads(raw_manifest)
    suffix = base_manifest.parent.name.split("-", 1)
    if len(suffix) == 2 and len(suffix[1]) == 64 and sha(raw_manifest) != suffix[1]:
        raise ValueError("Explicit baseline release hash differs from directory name")
    overlays = {entry["path"]: entry for entry in snapshot["assets"]}
    if len(overlays) != len(snapshot["assets"]):
        raise ValueError("Baseline signed release has duplicate paths")
    coverage = json.loads(tables.COVERAGE.read_text(encoding="utf-8"))
    with zipfile.ZipFile(base_apk) as apk, zipfile.ZipFile(coverage["sourceArchive"]) as source:
        used_baseline = {}
        def active_read(logical):
            entry = overlays.get(logical)
            if entry is None:
                raw = apk.read("assets/" + logical)
                used_baseline[logical] = {"source": "APK", "sha256": sha(raw), "bytes": len(raw)}
            else:
                raw = (blobs / entry["sha256"]).read_bytes()
                if sha(raw) != entry["sha256"] or len(raw) != entry["size"]:
                    raise ValueError("Signed baseline blob changed: " + logical)
                used_baseline[logical] = {"source": "signed-overlay", "sha256": sha(raw), "bytes": len(raw)}
            return raw
        preview_before = active_read(tables.LOGICAL)
        preview_after, stage_evidence = tables.patch_bundle(preview_before)
        instance_evidence = tables.validate_instance(active_read(tables.INSTANCE_LOGICAL))
        payload = {tables.LOGICAL: preview_after}
        map_report = None
        if restore_maps:
            map_payload, map_report = prepare_maps(source, active_read)
            payload.update(map_payload)
            payload[LUA_LOGICAL] = patch_lua(active_read(LUA_LOGICAL))
        report = {"status": "unsigned_local_payload_only", "baseAPK": str(base_apk),
                  "baseRelease": str(base_manifest), "baseReleaseSequence": snapshot["releaseSequence"],
                  "baseReleaseSha256": sha(raw_manifest), "sourceArchive": coverage["sourceArchive"],
                  "preservedStages": 247, "unchangedMissingStages": 50,
                  "unmodifiedInstance": instance_evidence, "preservedTutorials": True,
                  "preservedAllOpenGates": True, "preservedExistingLuaPrefix": restore_maps,
                  "maps": map_report, "baseMembers": used_baseline,
                  "stagePreviewEvidence": stage_evidence, "assets": []}
        for logical, data in sorted(payload.items()):
            report["assets"].append({"path": logical, "size": len(data), "sha256": sha(data),
                                     "candidatePath": str(output / logical)})
        report["payloadBytes"] = sum(len(data) for data in payload.values())
    output.mkdir(parents=True, exist_ok=True)
    for logical, data in sorted(payload.items()):
        path = output / logical
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Candidate output already has different content: " + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if path.read_bytes() != data:
            raise ValueError("Candidate write-back mismatch: " + logical)
    (output / "patch-plan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def apk_replacements(index_raw: bytes, candidate: Path = OUTPUT):
    """Return APK member replacements, adding the reviewed new index entries.

    This is the same payload consumed by the signed hot-update path.  The old
    ``assetbundle/assetbundle`` file is retained; the Lua module activates the
    independent manifest in both full APK and overlay installations.
    """
    report = json.loads((candidate / "patch-plan.json").read_text(encoding="utf-8"))
    replacements, expected = {}, {}
    for entry in report["assets"]:
        logical = entry["path"]
        data = (candidate / logical).read_bytes()
        if sha(data) != entry["sha256"] or len(data) != entry["size"]:
            raise ValueError("APK candidate asset changed: " + logical)
        replacements["assets/" + logical] = data
        resource = "/" + logical.removeprefix("assetbundle/")
        expected[resource] = hashlib.md5(data).hexdigest() + "=" + resource + ":" + str(len(data))
    lines = index_raw.decode("utf-8").splitlines()
    seen, updated = set(), []
    for line in lines:
        match = re.fullmatch(r"[0-9a-f]{32}=(/[^:]+):[0-9]+", line)
        if match is None:
            raise ValueError("Malformed APK asset index")
        resource = match.group(1)
        if resource in seen:
            raise ValueError("Duplicate APK asset index entry: " + resource)
        seen.add(resource)
        updated.append(expected.pop(resource, line))
    # Existing updater already appends added signed AB paths to its legacy
    # resource index. APK integration must do the equivalent for new bundles.
    updated.extend(expected[key] for key in sorted(expected))
    replacements["assets/m.assets_list.txt"] = ("\n".join(updated) + "\n").encode("utf-8")
    return replacements


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-apk", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--base-blobs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--tables-only", action="store_true")
    args = parser.parse_args()
    result = build(args.base_apk, args.base_manifest, args.base_blobs, args.output, not args.tables_only)
    print("PRESERVED_STAGE_ASSETS_READY", result["preservedStages"],
          len(result["assets"]), result["payloadBytes"], str(args.output), flush=True)
