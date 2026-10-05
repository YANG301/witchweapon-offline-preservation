"""Build an isolated guild-refresh APK against the local test server."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import zipfile

import build_original_ui_quest_refresh_v6_apk as signer
from build_online_apk import patch_index
from patch_guild_refresh_lua import SOURCE as LUA_SOURCE, sha
import patch_manifest as axml
import UnityPy


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "build/witchweapon-online-local-staging-shop-runtime-v21.apk"
SOURCE_SHA256 = "d5716d7f7ca5902710f7809d64121ce45de18632edf521ccc240aa929a237625"
RESULT = HERE / "build/witchweapon-online-local-guild-refresh-v23.apk"
REPORT = HERE / "build/本地集会所刷新验收-v23.json"
TEMP = Path(r"D:\Environment\Android\temp\witch-guild-refresh-local-v23")
BUNDLE = "assets/assetbundle/lua/lua_projx_patch.ab"
INIT_BUNDLE = "assets/assetbundle/lua/lua.ab"
INDEX = "assets/m.assets_list.txt"
MANIFEST = "AndroidManifest.xml"
RESOURCES = "resources.arsc"
ORIGINAL_PACKAGE = "com.codex.witchweapon.online.originalui.test"
TEST_PACKAGE = "com.codex.witchweapon.online.guildtest"
BASE_BUNDLE = "e22a201278657e66495f1cf9b6db8103418ac7f0f0c305a205589f83f31918de"
BASE_OBJECT = "fae61d1b2969ba26a43b4fd98b93ad0e88184dbde35187c3823949d6e59153e9"
BASE_SCRIPT = "48c007c740acd1c2d0a88db023600ea489d2d6250da264529c03482df7b82c58"
BASE_INIT_BUNDLE = "edc4d4831829ee0fa844e095e62dc66b53116edb67793ca133ff4229356cd4cb"


def isolate_manifest(raw: bytes) -> bytes:
    chunks = axml.split_chunks(raw)
    strings, pool_info = axml.string_pool(chunks[0])
    changed = 0
    for chunk in chunks:
        tag = axml.start_tag(chunk, strings)
        if tag == "manifest":
            attr = axml.attributes(chunk, strings)["package"]
            if axml.attribute_value(chunk, attr, strings) != ORIGINAL_PACKAGE:
                raise ValueError("Unexpected source package")
            axml.assign_string(chunk, attr, TEST_PACKAGE, strings)
            changed += 1
        elif tag == "application":
            attrs = axml.attributes(chunk, strings)
            if "label" in attrs:
                axml.assign_string(chunk, attrs["label"], "魔女兵器·集会所测试", strings)
        elif tag == "activity":
            attrs = axml.attributes(chunk, strings)
            if "label" in attrs:
                axml.assign_string(chunk, attrs["label"], "魔女兵器·集会所测试", strings)
    if changed != 1:
        raise ValueError("Expected one package declaration")
    body = axml.serialize_pool(chunks[0], strings, pool_info) + b"".join(
        bytes(chunk) for chunk in chunks[1:])
    result = struct.pack("<HHI", 3, 8, len(body) + 8) + body
    verify = axml.split_chunks(result)
    values, _ = axml.string_pool(verify[0])
    declarations = [axml.attribute_value(c, axml.attributes(c, values)["package"], values)
                    for c in verify if axml.start_tag(c, values) == "manifest"]
    if declarations != [TEST_PACKAGE]:
        raise ValueError("Isolated package did not round-trip")
    return result


def isolate_resources(raw: bytes) -> bytes:
    result = bytearray(raw)
    position = struct.unpack_from("<H", result, 2)[0]
    changed = 0
    while position < len(result):
        kind, header, size = struct.unpack_from("<HHI", result, position)
        if size < header or position + size > len(result):
            raise ValueError("Invalid resource table chunk")
        if kind == 0x0200:
            name = bytes(result[position + 12:position + 268]).decode("utf-16le").split("\0", 1)[0]
            if name != ORIGINAL_PACKAGE:
                raise ValueError("Unexpected resource package: " + name)
            result[position + 12:position + 268] = TEST_PACKAGE.encode("utf-16le").ljust(256, b"\0")
            changed += 1
        position += size
    if changed != 1:
        raise ValueError("Expected one compiled resource package")
    return bytes(result)


def isolate_lua_paths(raw: bytes) -> bytes:
    if sha(raw) != BASE_INIT_BUNDLE:
        raise ValueError("Local init.lua bundle changed")
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha(obj.get_raw_data()) for obj in bundle.objects}
    matches = [obj for obj in bundle.objects if obj.type.name == "TextAsset"
               and obj.read_typetree().get("m_Name") == "init.lua"]
    if len(matches) != 1:
        raise ValueError("Expected one init.lua")
    target = matches[0]
    tree = target.read_typetree()
    script = tree["m_Script"]
    if not isinstance(script, str) or script.count(ORIGINAL_PACKAGE) != 2:
        raise ValueError("Unexpected private storage paths")
    updated = script.replace(ORIGINAL_PACKAGE, TEST_PACKAGE)
    tree["m_Script"] = updated
    target.save_typetree(tree)
    result = bundle.file.save(packer="original")
    restored = UnityPy.load(result)
    after = {obj.path_id: sha(obj.get_raw_data()) for obj in restored.objects}
    if {key for key in before if before[key] != after[key]} != {target.path_id}:
        raise ValueError("Isolating app storage changed unrelated Unity objects")
    if next(obj for obj in restored.objects if obj.path_id == target.path_id).read_typetree()["m_Script"] != updated:
        raise ValueError("Isolated app storage did not round-trip")
    return result


def prepare() -> dict[str, bytes]:
    if signer.sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError("Local test APK differs from reviewed v21")
    with zipfile.ZipFile(SOURCE) as apk:
        if apk.read("assets/online_endpoint.txt") != b"https://127.0.0.1:19443\n":
            raise ValueError("APK does not target the isolated test service")
        original = apk.read(BUNDLE)
        if sha(original) != BASE_BUNDLE:
            raise ValueError("Local Lua AssetBundle changed")
        source = UnityPy.load(original)
        before = {obj.path_id: sha(obj.get_raw_data()) for obj in source.objects}
        targets = [obj for obj in source.objects if obj.type.name == "TextAsset"
                   and obj.read_typetree().get("m_Name") == "MainScenePanelPatch.lua"]
        if len(targets) != 1 or before[targets[0].path_id] != BASE_OBJECT:
            raise ValueError("Main scene patch object differs")
        target = targets[0]
        tree = target.read_typetree()
        if sha(tree["m_Script"].encode()) != BASE_SCRIPT:
            raise ValueError("Main scene Lua script differs")
        script = LUA_SOURCE.read_text(encoding="utf-8")
        tree["m_Script"] = script
        target.save_typetree(tree)
        patched = source.file.save(packer="original")
        result = UnityPy.load(patched)
        after = {obj.path_id: sha(obj.get_raw_data()) for obj in result.objects}
        if set(before) != set(after) or {key for key in before if before[key] != after[key]} != {target.path_id}:
            raise ValueError("Unrelated Unity object changed")
        restored = [obj.read_typetree()["m_Script"] for obj in result.objects
                    if obj.path_id == target.path_id]
        if restored != [script]:
            raise ValueError("Guild Lua did not round-trip")
        isolated_init = isolate_lua_paths(apk.read(INIT_BUNDLE))
        index = patch_index(apk.read(INDEX), {
            "/lua/lua_projx_patch.ab": patched, "/lua/lua.ab": isolated_init})
        return {BUNDLE: patched, INIT_BUNDLE: isolated_init, INDEX: index,
                MANIFEST: isolate_manifest(apk.read(MANIFEST)),
                RESOURCES: isolate_resources(apk.read(RESOURCES))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    replacements = prepare()
    if not args.build:
        print("GUILD_LOCAL_STATIC_OK", sha(replacements[BUNDLE]))
        return
    if TEMP.exists() or RESULT.exists() or REPORT.exists():
        raise FileExistsError("Local guild APK or build intermediate already exists")
    signer.SOURCE = SOURCE
    signer.SOURCE_SHA256 = SOURCE_SHA256
    signer.TEMP = TEMP
    report = signer.build(replacements, RESULT, REPORT)
    print("GUILD_LOCAL_APK_READY", report["testApk"]["sha256"])


if __name__ == "__main__":
    main()
