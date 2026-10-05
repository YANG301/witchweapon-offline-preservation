"""Prepare a minimal scene-transition correction for the preserved chapter 20.

The unavailable Haredi background remains covered by the game's black layer.
The next background must finish changing before that layer is removed.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import zipfile

import UnityPy

import prepare_original_stardust_19_21 as original
import restore_stardust_20_21 as helpers


PROJECT = Path(__file__).resolve().parents[1]
BASE_REPORT = PROJECT / "docs/星尘降临原版19-21资源候选.json"
REPORT = PROJECT / "docs/星尘降临第20节遮罩切换修复候选.json"
APK = PROJECT / "android-client/build/witchweapon-original-stardust-v105-test.apk"
APK_SHA256 = "1a61cbd6bbd71c51906a6f56c7eb44c9de8b93fb333e6390038cadc207cc98e2"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
LESSON = "assetbundle/assets/resources/guide/lesson/lesson30320.ab"
OLD_SHA256 = "5ff406f3a0dbd7c336c9b48425804be0544e96527b74bcf6ad011209c7c32de3"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build() -> dict:
    baseline = json.loads(BASE_REPORT.read_text(encoding="utf-8"))
    if (len(baseline["assets"]) != 65 or baseline["assets"][LESSON]["sha256"] != OLD_SHA256
            or baseline["blackScreenAdaptation"]["coverNode"] != 105
            or baseline["blackScreenAdaptation"]["revealNode"] != 108):
        raise ValueError("Reviewed original-story candidate changed")
    if sha(APK.read_bytes()) != APK_SHA256:
        raise ValueError("Reviewed v105 APK changed")
    with zipfile.ZipFile(APK) as source:
        old = source.read("assets/" + LESSON)
        if sha(old) != OLD_SHA256:
            raise ValueError("v105 chapter 20 is not the reviewed first adaptation")
        env = UnityPy.load(old)
        obj = next(item for item in env.objects if item.type.name == "MonoBehaviour")
        tree = obj.read_typetree()
        graph = json.loads(tree["_serializedGraph"])
        cover = graph["nodes"][105]["_roundInfo"]
        reveal = graph["nodes"][108]["_roundInfo"]
        change = {"picName": "BG_Stardust_MasadSways",
                  "$type": "NodeCanvas.Tasks.Actions.C_changeBG"}
        hide = {"$type": "NodeCanvas.Tasks.Actions.HideColor"}
        if (cover["_b4cmdActionList"]["actions"] != [
                {"layerType": "C", "$type": "NodeCanvas.Tasks.Actions.FillColor"}]
                or reveal["_b4cmdActionList"]["actions"] != [change, hide]
                or reveal["_a4cmdActionList"]["actions"]):
            raise ValueError("The reviewed black-screen action sequence changed")
        graph = copy.deepcopy(graph)
        graph["nodes"][108]["_roundInfo"]["_b4cmdActionList"]["actions"] = [change]
        graph["nodes"][108]["_roundInfo"]["_a4cmdActionList"]["actions"] = [hide]
        tree["_serializedGraph"] = json.dumps(graph, ensure_ascii=False,
                                                separators=(",", ":"))
        obj.save_typetree(tree)
        fixed = env.file.save(packer="original")
        verify = original.mono(fixed)
        if json.loads(verify["_serializedGraph"]) != graph:
            raise ValueError("Chapter 20 transition correction did not round-trip")
        index = helpers.patch_index(source.read("assets/m.assets_list.txt"),
                                    {"assets/" + LESSON: fixed})
    BLOBS.mkdir(parents=True, exist_ok=True)
    digest = sha(fixed)
    blob = BLOBS / digest
    if blob.exists():
        if blob.read_bytes() != fixed:
            raise ValueError("Content-addressed chapter candidate changed")
    else:
        blob.write_bytes(fixed)
    index_digest = sha(index)
    index_blob = BLOBS / index_digest
    if index_blob.exists():
        if index_blob.read_bytes() != index:
            raise ValueError("Content-addressed index candidate changed")
    else:
        index_blob.write_bytes(index)
    result = copy.deepcopy(baseline)
    result["assets"][LESSON] = {"sha256": digest, "bytes": len(fixed)}
    result["apkAssetIndex"] = {"sha256": index_digest, "bytes": len(index)}
    result["blackScreenAdaptation"]["clientActions"] = [
        "FillColor at node 105", "C_changeBG before command at node 108",
        "HideColor after command at node 108"]
    result["previousCandidateSha256"] = sha(BASE_REPORT.read_bytes())
    result["sourceFullApkSha256"] = APK_SHA256
    result["productionDeployed"] = False
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != result:
        raise ValueError("Chapter 20 correction report did not round-trip")
    print("STARDUST20_REVEAL_CANDIDATE_READY", digest)
    return result


if __name__ == "__main__":
    build()
