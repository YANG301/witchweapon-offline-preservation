"""Pinned, bundle-only patch for the original daily-task controls.

This module intentionally does not build, sign, install, or deploy an APK.
Call ``patch_bundles`` with the two members read from EXPECTED_APK; any
different APK/bundle/TextAsset fails closed. The caller must update the APK's
bundle index after replacing members.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

import UnityPy


EXPECTED_APK = Path(__file__).resolve().parent / "build" / "witchweapon-online.apk"
EXPECTED_APK_SHA256 = "480f25027c01036d528248858cc5e17a969148e31c4920d5921571ffd8453a4e"
UI_MEMBER = "assets/assetbundle/lua/lua_projx_ui.ab"
PATCH_MEMBER = "assets/assetbundle/lua/lua_projx_patch.ab"
EXPECTED_BUNDLE_SHA256 = {
    UI_MEMBER: "937e345c98a2c180fa4c9b641b8c127f97286537341e6f2489dce0d442074b32",
    PATCH_MEMBER: "1227baa397db501d042f6af568de0e068dc898061df0c80b18c9b227712ba15a",
}
EXPECTED_ASSETS = {
    "ActivityView.lua": (
        "a895036d172466e557c6f4648420b8e6b6a5fe5c582e4ba91606dadf2b71202a",
        "71e72e05a8c12901e3d23ac3d997ef9a02369f96433be14d6ab08cfa26a2fd00",
    ),
    "UIActivities.lua": (
        "ffa709331a3ed0be3a43af59d87e71473012c209bed2869c6fd8711ec5809f08",
        "fab891c24e1a985acf4c5316f5c0caf6c7bf7ee7d296cceedd3e64ba67b8d661",
    ),
    "UIActivitiesFormat60.lua": (
        "dc1a7ccfc06bbb710cda32e93e553ed7ecfd55077c011e9e9722eab04a4f43fa",
        "01fef454ea0bf92a08db02427ee60b13917d8ebf259f4015cfb35bea6718e094",
    ),
    "TaskItemPatch.lua": (
        "34f51e08b8dd64daf75ca9ba05025217e337044904298ecc0d427b085921b631",
        "869260ea7d0a44c4eb91cec7649d65ec26c5f6c64a9d64edd757bc0087d08672",
    ),
}
TARGET_PATHS = {
    "ActivityView.lua": "\t\t\t\t\tUIFrame.UISceneManager.getInstance():Goto(UIFrame.UISceneState.New(UIFrame.UISceneID.MAIN_SCENE_NEW:ToInt()),UIFrame.UISceneState.New(UIFrame.UISceneID.TASK_SCENE:ToInt()))",
    "UIActivitiesFormat60.lua": "\t\tUIFrame.UISceneManager.getInstance():GotoBackLua(UIFrame.UISceneState.New(UIFrame.UISceneID.MAIN_SCENE_NEW:ToInt()),UIFrame.UISceneState.New(UIFrame.UISceneID.TASK_SCENE:ToInt()),'UIActivitiesFormat60.onBack')",
}
REFRESH_MARKER = "-- Online task refresh: request the original GetAllQuest message."
NEW_MARKER = "-- Online task refresh: cover this original task entry."
TASK_ROW_FILE = Path(__file__).resolve().parent / "lua" / "TaskItemPatch-online-v5.lua"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_pinned_apk(path: Path = EXPECTED_APK) -> dict[str, bytes]:
    if sha256_file(path) != EXPECTED_APK_SHA256:
        raise ValueError("Not the reviewed daily-task APK")
    with zipfile.ZipFile(path) as source:
        if len(source.namelist()) != len(set(source.namelist())):
            raise ValueError("Duplicate APK members")
        return {name: source.read(name) for name in EXPECTED_BUNDLE_SHA256}


def _refresh(indent: str) -> str:
    # The original GetAllQuest parser updates the native QuestSystemManager;
    # TaskItemPatch subsequently repaints original row buttons from that model.
    return "\n".join((
        indent + NEW_MARKER,
        indent + "local refreshOK, refreshError = pcall(function()",
        indent + "\trequire 'tolua.reflection'",
        indent + "\ttolua.loadassembly('Assembly-CSharp')",
        indent + "\tlocal taskType = typeof('WaterBell.ProjX.Data.NetIO.GetAllQuest')",
        indent + "\tlocal taskMessage = tolua.createinstance(taskType)",
        indent + "\tlocal send = tolua.gettypemethod(typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)",
        indent + "\tsend:Call(taskMessage)",
        indent + "\tsend:Destroy()",
        indent + "end)",
        indent + "if not refreshOK then",
        indent + "\tUnityEngine.Debug.LogError('ONLINE_TASK_REFRESH ' .. tostring(refreshError))",
        indent + "end",
    )) + "\n"


def _patch_ui(name: str, script: str) -> str:
    if name == "UIActivities.lua":
        # Current v3 already issues GetAllQuest from this carousel entry.
        if (script.count(REFRESH_MARKER) != 1 or
                script.find("GetAllQuest", script.index(REFRESH_MARKER)) < 0 or
                script.find("TASK_SCENE", script.index(REFRESH_MARKER)) < 0 or
                script.index("GetAllQuest", script.index(REFRESH_MARKER)) >
                script.index("TASK_SCENE", script.index(REFRESH_MARKER))):
            raise ValueError("Existing activities refresh changed")
        return script
    target = TARGET_PATHS[name]
    if script.count(target) != 1 or NEW_MARKER in script:
        raise ValueError("Unexpected original task entry: " + name)
    indent = target[:len(target) - len(target.lstrip("\t"))]
    return script.replace(target, _refresh(indent) + target, 1)


def _patch_bundle(raw: bytes, member: str) -> tuple[bytes, list[str]]:
    if sha256(raw) != EXPECTED_BUNDLE_SHA256[member]:
        raise ValueError("Unreviewed Lua bundle: " + member)
    names = (("ActivityView.lua", "UIActivities.lua", "UIActivitiesFormat60.lua")
             if member == UI_MEMBER else ("TaskItemPatch.lua",))
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha256(obj.get_raw_data()) for obj in bundle.objects}
    found: dict[str, object] = {}
    expected_text: dict[int, str] = {}
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        name = tree.get("m_Name")
        if name not in names:
            continue
        if name in found or not isinstance(tree.get("m_Script"), str):
            raise ValueError("Duplicate/non-text Lua asset: " + name)
        raw_hash, text_hash = EXPECTED_ASSETS[name]
        script = tree["m_Script"]
        if before[obj.path_id] != raw_hash or sha256(script.encode("utf-8")) != text_hash:
            raise ValueError("Unreviewed Lua asset: " + name)
        found[name] = obj
        if name == "TaskItemPatch.lua":
            updated = TASK_ROW_FILE.read_text(encoding="utf-8")
            if ("StatusChanged" not in updated or "MetaChanged" not in updated or
                    "conditionCount" not in updated):
                raise ValueError("Task row repaint source changed")
        else:
            updated = _patch_ui(name, script)
        expected_text[obj.path_id] = updated
        if updated != script:
            tree["m_Script"] = updated
            obj.save_typetree(tree)
    if set(found) != set(names):
        raise ValueError("Missing reviewed Lua asset")
    saved = bundle.file.save(packer="original")
    check = UnityPy.load(saved)
    changed: list[int] = []
    for obj in check.objects:
        if sha256(obj.get_raw_data()) != before[obj.path_id]:
            changed.append(obj.path_id)
        if obj.path_id in expected_text and obj.read_typetree().get("m_Script") != expected_text[obj.path_id]:
            raise ValueError("Patched Lua failed round-trip")
    # UnityPy's object handles may reflect the edited tree, so use the pinned
    # baseline hash to check the exact set of changed Unity objects instead.
    expected_changed = ({found["ActivityView.lua"].path_id,
                         found["UIActivitiesFormat60.lua"].path_id}
                        if member == UI_MEMBER else {found["TaskItemPatch.lua"].path_id})
    if set(changed) != expected_changed:
        raise ValueError("Unrelated Unity objects changed")
    return saved, [name for name in names if found[name].path_id in expected_changed]


def patch_bundles(bundles: dict[str, bytes]) -> tuple[dict[str, bytes], dict[str, list[str]]]:
    if set(bundles) != set(EXPECTED_BUNDLE_SHA256):
        raise ValueError("Both reviewed Lua bundles are required")
    results: dict[str, bytes] = {}
    changed: dict[str, list[str]] = {}
    for name, raw in bundles.items():
        results[name], changed[name] = _patch_bundle(raw, name)
    return results, changed
