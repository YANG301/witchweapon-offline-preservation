"""Prepare the preserved 2020 Stardust 19-21 bundles without altering production.

The source is the user's E:/Desktop/files directory.  Original lesson,
sentence, portrait and background bundles are copied byte-for-byte into the
content-addressed candidate store.  Only the existing APK's Story/Sound CSV
tables and asset index are patched, so unrelated game configuration remains.
"""

from __future__ import annotations

import hashlib
import json
import copy
from pathlib import Path
import zipfile

import UnityPy

import restore_stardust_20_21 as helpers


PROJECT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"E:\Desktop\files\assetbundle")
APK = PROJECT / "android-client/build/witchweapon-stardust-story-v104-test.apk"
APK_SHA256 = "ab79f49e33df8a12ae9b87ed8955b431001f471bb7724d5bef24606e011b9367"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
REPORT = PROJECT / "docs/星尘降临原版19-21资源候选.json"
SOURCE_VERSION = "2.0.1.20092956"
SOURCE_HASHES = {
    "assets/resources/guide/lesson/lesson30320.ab":
        "2d7f6dc30f85a6415a5610255cebe794fb297f601356753172e485015067d29b",
    "assets/resources/guide/lesson/lesson30321.ab":
        "90ec1a8522384f677315b2c74e98e6010f3464b1e2d5391e16c306430deeb652",
    "config/lesson/sentence_30320.ab":
        "e96874c76cda7f8bee5efacdf1a5d56787fc109a7df5a1b77db146cf03956f95",
    "config/lesson/sentence_30321.ab":
        "0cdcdada73615acbd011ffc377b190493e35619bd23b4b6ca47f55e5e9c82cc3",
}
PREFIX = "assets/assetbundle/"
STORY = "config/clientexel/story.ab"
SOUND = "config/clientexel/sound.ab"
DICT = "config/clientexel/dictionary.ab"
MISSING_ORIGINAL_BACKGROUND = "assets/resources/ui/uiimage/guide/bg_stardust_haredi.ab"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def mono(raw: bytes) -> dict:
    return next(obj.read_typetree() for obj in UnityPy.load(raw).objects
                if obj.type.name == "MonoBehaviour")


def csv(raw: bytes) -> str:
    return bytes(value ^ 255 for value in mono(raw)["bytes"]).decode("utf-8-sig")


def source_rows(raw: bytes, ids: set[str], separator: str) -> dict[tuple[str, str], str]:
    rows = {}
    for line in csv(raw).splitlines()[1:]:
        cells = line.split(separator)
        if cells[0] in ids:
            key = (cells[0], cells[1] if separator == "," else "")
            if key in rows:
                raise ValueError("Duplicate original table row: " + str(key))
            rows[key] = line
    return rows


def patch_story(text: str, originals: dict[tuple[str, str], str]) -> str:
    result = []
    seen = set()
    for line in text.splitlines(keepends=True):
        fields = line.rstrip("\r\n").split(",")
        key = (fields[0], fields[1]) if len(fields) > 1 else None
        if key in originals:
            seen.add(key)
            line = originals[key] + line[len(line.rstrip("\r\n")):]
        result.append(line)
    if seen != set(originals) or len(seen) != 9:
        raise ValueError("Current APK Story table does not have all original channel rows")
    return "".join(result)


def patch_sound(text: str, original: str) -> str:
    lines = text.splitlines(keepends=True)
    if not lines[0].startswith("ID,sound_name,") or any(
            line.startswith("99120110021,") for line in lines):
        raise ValueError("Unexpected current Sound table")
    if not original.startswith("99120110021,Sounds/bgm/login,"):
        raise ValueError("Unexpected original Sound mapping")
    ending = "\r\n" if "\r\n" in lines[0] else "\n"
    return "".join(lines) + original + ending


def black_out_removed_background(raw: bytes) -> bytes:
    """Use the game's own black overlay for the removed religious image."""
    env = UnityPy.load(raw)
    obj = next(item for item in env.objects if item.type.name == "MonoBehaviour")
    tree = obj.read_typetree()
    graph = json.loads(tree["_serializedGraph"])
    hidden = graph["nodes"][105]["_roundInfo"]["_b4cmdActionList"]["actions"]
    reveal = graph["nodes"][108]["_roundInfo"]["_b4cmdActionList"]["actions"]
    if hidden != [{"picName": "BG_Stardust_Haredi",
                   "$type": "NodeCanvas.Tasks.Actions.C_changeBG"}] or reveal != [
                   {"picName": "BG_Stardust_MasadSways",
                    "$type": "NodeCanvas.Tasks.Actions.C_changeBG"}]:
        raise ValueError("Reviewed black-screen scene has changed")
    graph = copy.deepcopy(graph)
    graph["nodes"][105]["_roundInfo"]["_b4cmdActionList"]["actions"] = [
        {"layerType": "C", "$type": "NodeCanvas.Tasks.Actions.FillColor"}]
    graph["nodes"][108]["_roundInfo"]["_b4cmdActionList"]["actions"].append(
        {"$type": "NodeCanvas.Tasks.Actions.HideColor"})
    tree["_serializedGraph"] = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    obj.save_typetree(tree)
    patched = env.file.save(packer="original")
    check = json.loads(mono(patched)["_serializedGraph"])
    if check != graph:
        raise ValueError("Black-screen adaptation did not round-trip")
    return patched


def chapter_assets(apk: zipfile.ZipFile) -> tuple[dict[str, bytes], dict]:
    assets = {}
    chapter_report = {}
    missing = set()
    for episode in (19, 20, 21):
        lesson = f"assets/resources/guide/lesson/lesson303{episode}.ab"
        sentence = f"config/lesson/sentence_303{episode}.ab"
        lesson_raw = (SOURCE / lesson).read_bytes()
        if episode == 20:
            lesson_raw = black_out_removed_background(lesson_raw)
        sentence_raw = (SOURCE / sentence).read_bytes()
        lesson_tree = mono(lesson_raw)
        sentence_tree = mono(sentence_raw)
        graph = json.loads(lesson_tree["_serializedGraph"])
        lines = bytes(x ^ 255 for x in sentence_tree["bytes"]).decode("utf-8-sig").splitlines()
        if (lesson_tree["m_Name"] != f"lesson303{episode}" or
                lesson_tree["sentenceFileName"] != f"sentence_303{episode}.txt" or
                sentence_tree["m_Name"] != f"sentence_303{episode}" or
                len(graph["connections"]) != len(graph["nodes"]) - 1):
            raise ValueError("Original lesson structure does not match chapter " + str(episode))
        actions = [action for node in graph["nodes"]
                   for phase in ("_b4cmdActionList", "_a4cmdActionList")
                   for action in node["_roundInfo"][phase]["actions"]]
        references = [action["sentenceIdx"] for action in actions
                      if "sentenceIdx" in action]
        if (sorted(references) != list(range(len(lines))) or
                sum(a["$type"].endswith("EndLesson") for a in actions) != 1):
            raise ValueError("Original dialogue mapping or ending is incomplete")
        assets[lesson] = lesson_raw
        assets[sentence] = sentence_raw
        wanted = set()
        for role in graph["derivedData"]["claimInfo"]["role"]:
            wanted.add("assets/resources/ui/prefab/guide/role" +
                       role["roleSN"] + ".ab")
        for action in actions:
            for name in (action.get("bgPicStr"), action.get("picName")):
                if name:
                    wanted.add("assets/resources/ui/uiimage/guide/" +
                               name.lower() + ".ab")
        for relative in wanted:
            if (SOURCE / relative).is_file():
                assets[relative] = (SOURCE / relative).read_bytes()
            elif PREFIX + relative not in apk.namelist():
                missing.add(relative)
        chapter_report[str(episode)] = {
            "nodes": len(graph["nodes"]), "connections": len(graph["connections"]),
            "sentences": len(lines), "actionCount": len(actions),
            "backgroundReferences": sum(
                a["$type"].endswith("C_changeBG") for a in actions),
        }
    if missing:
        raise ValueError("Unexpected missing original assets: " + repr(sorted(missing)))
    return assets, {"chapters": chapter_report,
                    "missingOriginalAssets": sorted(missing),
                    "blackScreenAdaptation": {
                        "sourceMissingBackground": MISSING_ORIGINAL_BACKGROUND,
                        "episode": 20, "coverNode": 105, "revealNode": 108,
                        "clientActions": ["FillColor", "HideColor"],
                    }}


def build() -> dict:
    if SOURCE.joinpath("m.version").read_text(encoding="utf-8").strip() != SOURCE_VERSION:
        raise ValueError("Original source version changed")
    for relative, expected in SOURCE_HASHES.items():
        if sha((SOURCE / relative).read_bytes()) != expected:
            raise ValueError("Original source bundle changed: " + relative)
    with APK.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != APK_SHA256:
            raise ValueError("Reviewed v104 APK changed")
    with zipfile.ZipFile(APK) as apk:
        assets, summary = chapter_assets(apk)
        story_ids = {"61300041019", "61300041020", "61300041021"}
        rows = source_rows((SOURCE / STORY).read_bytes(), story_ids, ",")
        if len(rows) != 9 or {channel for _, channel in rows} != {"22", "25", "70"}:
            raise ValueError("Original Story rows incomplete")
        assets[STORY] = helpers.csv_bundle(
            apk.read(PREFIX + STORY), lambda text: patch_story(text, rows))
        sound_rows = source_rows((SOURCE / SOUND).read_bytes(), {"99120110021"}, ",")
        if len(sound_rows) != 1 or PREFIX + "assets/resources/sounds/bgm/login.ab" not in apk.namelist():
            raise ValueError("Original music mapping or audio missing")
        assets[SOUND] = helpers.csv_bundle(
            apk.read(PREFIX + SOUND),
            lambda text: patch_sound(text, next(iter(sound_rows.values()))))
        title_ids = {"16130004101901", "16130004102001", "16130004102101"}
        original_titles = source_rows((SOURCE / DICT).read_bytes(), title_ids, "\t")
        current_titles = source_rows(apk.read(PREFIX + DICT), title_ids, "\t")
        if original_titles != current_titles or len(original_titles) != 3:
            raise ValueError("Current chapter titles differ from preserved original")
        indexed = {PREFIX + relative: raw for relative, raw in assets.items()}
        index = helpers.patch_index(apk.read("assets/m.assets_list.txt"), indexed)
    BLOBS.mkdir(parents=True, exist_ok=True)
    records = {}
    for relative, raw in sorted(assets.items()):
        digest = sha(raw)
        target = BLOBS / digest
        if target.exists() and target.read_bytes() != raw:
            raise ValueError("Content-addressed candidate blob changed")
        if not target.exists():
            target.write_bytes(raw)
        records["assetbundle/" + relative] = {"sha256": digest, "bytes": len(raw)}
    index_sha = sha(index)
    index_target = BLOBS / index_sha
    if not index_target.exists():
        index_target.write_bytes(index)
    elif index_target.read_bytes() != index:
        raise ValueError("Candidate index blob changed")
    summary.update({
        "sourceDirectory": str(SOURCE), "sourceVersion": SOURCE_VERSION,
        "sourcePrimarySha256": SOURCE_HASHES,
        "sourceApkSha256": APK_SHA256,
        "assets": records,
        "apkAssetIndex": {"sha256": index_sha, "bytes": len(index)},
        "productionDeployed": False,
    })
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != summary:
        raise ValueError("Original-story candidate report did not round-trip")
    print("ORIGINAL_STARDUST_CANDIDATE_READY", len(records),
          "bundles; unresolved backgrounds", len(summary["missingOriginalAssets"]))
    return summary


if __name__ == "__main__":
    build()
