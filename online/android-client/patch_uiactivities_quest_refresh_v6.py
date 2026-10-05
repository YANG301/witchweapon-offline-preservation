"""Refresh the original quest model on the activities task button."""

from __future__ import annotations

import hashlib

import UnityPy


ASSET_NAME = "UIActivities.lua"
ORIGINAL_RAW_SHA256 = "993d6d5bdcce38630b748de5c74630d268e2028de35a20c5d447fe9687998709"
ORIGINAL_SCRIPT_SHA256 = "51c27363f8ecbf66acd9017b563a69338e006814e5446678200fd9c652982cd0"
MARKER = "-- Online task refresh: request the original GetAllQuest message."
OLD = ("\t\t\t\tclose()\n"
       "\t\t\t\tUISceneManager.getInstance():GotoBackLua("
       "UISceneState.New(UISceneID.MAIN_SCENE_NEW:ToInt()),"
       "UISceneState.New(UISceneID.TASK_SCENE:ToInt()),'UIActivities.onBack')")
NEW = ("\t\t\t\t" + MARKER + "\n"
       "\t\t\t\tlocal refreshOK, refreshError = pcall(function()\n"
       "\t\t\t\t\trequire 'tolua.reflection'\n"
       "\t\t\t\t\ttolua.loadassembly('Assembly-CSharp')\n"
       "\t\t\t\t\tlocal taskType = typeof('WaterBell.ProjX.Data.NetIO.GetAllQuest')\n"
       "\t\t\t\t\tlocal taskMessage = tolua.createinstance(taskType)\n"
       "\t\t\t\t\tlocal send = tolua.gettypemethod("
       "typeof('WaterBell.ProjX.Data.NetIO.NetMsgBase'), 'SendMsg', 65535)\n"
       "\t\t\t\t\tsend:Call(taskMessage)\n"
       "\t\t\t\t\tsend:Destroy()\n"
       "\t\t\t\tend)\n"
       "\t\t\t\tif not refreshOK then\n"
       "\t\t\t\t\tUnityEngine.Debug.LogError('ONLINE_TASK_REFRESH ' .. tostring(refreshError))\n"
       "\t\t\t\tend\n" + OLD)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def patch(raw: bytes) -> bytes:
    bundle = UnityPy.load(raw)
    before = {obj.path_id: sha256(obj.get_raw_data()) for obj in bundle.objects}
    targets = []
    for obj in bundle.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        if tree.get("m_Name") == ASSET_NAME:
            targets.append((obj, tree))
    if len(targets) != 1:
        raise ValueError("Expected one original UIActivities.lua TextAsset")
    obj, tree = targets[0]
    script = tree["m_Script"]
    if not isinstance(script, str) or before[obj.path_id] != ORIGINAL_RAW_SHA256:
        raise ValueError("Unreviewed activities Unity object")
    if sha256(script.encode("utf-8")) != ORIGINAL_SCRIPT_SHA256:
        raise ValueError("Unreviewed activities script")
    if script.count(OLD) != 1 or MARKER in script:
        raise ValueError("Original daily task button not found exactly once")
    if script.count("新丰洲公告") != 1 or script.count("邮件信箱") != 1 or script.count("每日签到") != 1:
        raise ValueError("Original restored carousel captions changed")
    tree["m_Script"] = script.replace(OLD, NEW, 1)
    obj.save_typetree(tree)
    updated = bundle.file.save(packer="original")

    check = UnityPy.load(updated)
    changed = []
    found = 0
    for candidate in check.objects:
        if sha256(candidate.get_raw_data()) != before.get(candidate.path_id):
            changed.append(candidate.path_id)
        if candidate.path_id == obj.path_id:
            found += 1
            restored = candidate.read_typetree()
            text = restored.get("m_Script")
            if (restored.get("m_Name") != ASSET_NAME or
                    text != script.replace(OLD, NEW, 1) or
                    text.count(MARKER) != 1):
                raise ValueError("Daily task refresh did not round-trip")
    if found != 1 or changed != [obj.path_id]:
        raise ValueError("Other Unity objects changed in lua_projx_ui.ab")
    return updated
