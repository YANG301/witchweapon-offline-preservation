"""Build Stardust episodes 20/21 for the recovered Unity 2017 client.

The editor scripts are the chosen dialogue source.  Keep the original game's
lesson graph, sentence table, background bundle, and story-index formats so the
existing story player and update loader can consume these assets directly.
This script never changes the source APK or a running server.
"""

from __future__ import annotations

import ast
import codecs
import copy
import hashlib
import json
from pathlib import Path
import re
import zipfile

from PIL import Image
import UnityPy


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
GODOT = Path(r"D:\Project\Witch-Weapon-Godot-")
APK = HERE / "build/witchweapon-unlimited-stock-v102-test.apk"
APK_SHA256 = "9b2cba23a8f8130015ffe4502cce00f705b927ad81bd4de865520cb9ff596e31"
SCRIPT_HASHES = {
    20: "615166f4c3a321a5c0cd2c387d2fa4c3a02f5d1f245ee6aefc82d493b1b24c32",
    21: "28e7a383fc370b9b27f79abeaa72e9d545f466d1657c6aaccaebb99e1a23abac",
}
SCRIPT = GODOT / "scripts/story/stardustdescends"
BLOBS = PROJECT / "热更新测试/主线热更候选/blobs"
REPORT = PROJECT / "docs/星尘降临20-21资源构建.json"
PREFIX = "assets/assetbundle/"
LESSON_TEMPLATE = PREFIX + "assets/resources/guide/lesson/lesson303190.ab"
SENTENCE_TEMPLATE = PREFIX + "config/lesson/sentence_303190.ab"
BACKGROUND_TEMPLATE = PREFIX + "assets/resources/ui/uiimage/guide/bg_stardust_recording.ab"
STORY_TABLE = PREFIX + "config/clientexel/story.ab"
DICTIONARY_TABLE = PREFIX + "config/clientexel/dictionary.ab"
INDEX = "assets/m.assets_list.txt"

EVENT = re.compile(r"^\s*(?:await\s+)?novel_interface\.([A-Za-z_][A-Za-z_0-9]*)\((.*)\)\s*$")
SPEAK = "NodeCanvas.Tasks.Actions.C_roleSpeak"
ASIDE = "NodeCanvas.Tasks.Actions.C_speakAside"
ACTION = "NodeCanvas.Tasks.Actions."
BG_PREFIX = "assets/resources/ui/uiimage/guide/"
ROLE_SN = {
    "小怜": "15", "莉琉": "11", "爱衣": "28", "秋子": "84",
    "哈蒙": "106", "安妮": "20", "倪克斯": "43", "小星尘": "92",
}
CHARACTER_NAME = {
    "ai": "爱衣", "anne": "安妮", "liliu": "莉琉", "ren": "小怜",
    "nyx": "倪克斯", "stardust": "小星尘",
}
# Face names confirmed in the 221 available original lesson bundles.  The
# editor script uses a few expression aliases that the original lessons never
# request; map those to the nearest confirmed face for each role.
SUPPORTED_FACES = {
    "15": {"pc_gratified", "pc_normal2", "pc_panic", "pc_smile", "pc_solemn",
           "pc_stare", "pc_uneasy", "pc_wail", "pc_wry_smile"},
    "11": {"pc_angry", "pc_jest", "pc_normal1", "pc_serious"},
    "28": {"pc_blush", "pc_blush_dizzy", "pc_blush_stare", "pc_dizzy",
           "pc_normal", "pc_stare", "pc_think", "pc_wink"},
    "84": {"pc_normal", "pc_shock"},
    "106": {"pc_normal1", "pc_serious", "pc_shout", "pc_speak", "pc_unhappy"},
    "20": {"pc_frustrate", "pc_panic", "pc_smile", "pc_stare",
           "pc_unhappy", "pc_upset", "pc_worry"},
    "43": {"01"}, "92": {"01"},
}
FACE_DEFAULT = {
    "15": "pc_normal2", "11": "pc_normal1", "28": "pc_normal",
    "84": "pc_normal", "106": "pc_normal1", "20": "pc_stare",
    "43": "01", "92": "01",
}
FACE_ALIASES = {
    "15": {"pc_awkward": "pc_wry_smile", "pc_happy": "pc_smile",
           "pc_perspire1": "pc_uneasy", "pc_serious": "pc_solemn",
           "pc_shout": "pc_wail", "pc_sob": "pc_wail",
           "pc_upset": "pc_uneasy", "pc_worry": "pc_uneasy"},
    "11": {"pc_happy": "pc_jest", "pc_shock": "pc_serious",
           "pc_smile": "pc_jest"},
    "28": {"pc_blush_think": "pc_think"},
    "20": {"pc_happy": "pc_smile"},
}
# Matches are taken from the original Sound table; the remaining names use the
# closest existing story track because the editor's MP3 names are not IDs.
BGM_IDS = {
    "UI_Main_Funk": 99120110019,
    "bgm": 99120100249,
    "Everything's gonna be Okay": 99120100531,
    "Normal Stage": 99120110015,
    "Shop": 99120110016,
    "Barrier Maze": 99120110014,
    "Conspiracy": 99120110017,
    "Sewer": 99120110002,
    "Deep Water": 99120110003,
    "Like A Girl": 99120110005,
    "Sign of brave": 99120110006,
    "Sonar": 99120110004,
}
IGNORED_VISUAL_EVENTS = {
    "character_move_left", "character_light", "character_dark",
    "character_2nd_light", "character_2nd_dark",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def action(name: str, **fields) -> dict:
    return {**fields, "$type": ACTION + name}


def source_events(episode: int) -> list[tuple[str, list[str]]]:
    path = SCRIPT / f"stardustdescends_ep{episode}.gd"
    data = path.read_bytes()
    if sha(data) != SCRIPT_HASHES[episode]:
        raise ValueError(f"Unreviewed chapter {episode} editor source")
    result = []
    for number, line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        if "novel_interface." not in line:
            continue
        match = EVENT.match(line)
        if not match:
            raise ValueError(f"Unparsed editor event at {path.name}:{number}")
        arguments = ast.parse("f(" + match.group(2) + ")", mode="eval").body
        if arguments.keywords:
            raise ValueError(f"Unexpected editor keyword argument on line {number}")
        result.append((match.group(1), [ast.literal_eval(value) for value in arguments.args]))
    expected = {20: (341, 1), 21: (196, 1)}[episode]
    if sum(kind in {"show_dialog", "show_text_only"} for kind, _ in result) != expected[0]:
        raise ValueError(f"Chapter {episode} dialogue count changed")
    if sum(kind == "end_story_episode" for kind, _ in result) != expected[1]:
        raise ValueError(f"Chapter {episode} end marker changed")
    return result


def background_name(source_path: str) -> str:
    stem = Path(source_path).stem
    if stem == "opsRoom":
        return "bg_sid_opsroom"
    if stem == "Vessel":
        return "bg_soya_vessel"
    if not stem.startswith("BG_"):
        raise ValueError("Unknown editor background: " + source_path)
    return stem.lower()


def background_member(name: str) -> str:
    return PREFIX + BG_PREFIX + name + ".ab"


def sprite_speaker(sprite: str | None) -> str | None:
    if not sprite:
        return None
    return CHARACTER_NAME.get(sprite.split("_", 1)[0])


def original_face(role_sn: str, expression: str) -> str:
    requested = "pc_" + expression
    if requested in SUPPORTED_FACES[role_sn]:
        return requested
    substitute = FACE_ALIASES.get(role_sn, {}).get(requested, FACE_DEFAULT[role_sn])
    if substitute not in SUPPORTED_FACES[role_sn]:
        raise ValueError("Unsupported story portrait face")
    return substitute


def clone_identity(env, previous: str, replacement: str) -> None:
    """Replace only the bundle/asset path identity, retaining object PPtr IDs."""
    for obj in env.objects:
        if obj.type.name != "AssetBundle":
            continue
        tree = obj.read_typetree()
        for key in ("m_Name", "m_AssetBundleName"):
            if previous not in tree[key]:
                raise ValueError(f"Bundle {key} lacks template identity")
            tree[key] = tree[key].replace(previous, replacement)
        containers = []
        for path, metadata in tree["m_Container"]:
            if previous not in path:
                raise ValueError("Bundle container lacks template identity")
            containers.append((path.replace(previous, replacement), metadata))
        tree["m_Container"] = containers
        obj.save_typetree(tree)
        return
    raise ValueError("Template AssetBundle object missing")


def graph_from_events(template: dict, episode: int, events) -> tuple[dict, list[str], dict]:
    graph = copy.deepcopy(template)
    nodes = []
    connections = []
    lines = []
    role_names = []
    pending = [action("C_Begin")]
    first_music = True
    first_background = True
    screen_dark = False
    primary_sprite = None
    secondary_sprite = None
    primary_expression = "normal"
    secondary_expression = "normal"
    dual_mode = False
    # Preserve entrance order: the existing lesson303190 graph exits dual
    # portraits in that order before moving to a narrator or another scene.
    visible_roles = {}
    first_music_name = None
    ignored_count = {}
    music_names = set()
    background_names = set()

    def ensure_role(name: str) -> int:
        if name not in role_names:
            role_names.append(name)
        return role_names.index(name)

    def remove_visible_roles(keep: int | None = None) -> None:
        # The original NodeCanvas lessons release the portrait slot, then wait
        # for its exit animation before another speaker claims that slot.
        # Without the paired delay, RoleSpeak can add a duplicate slot key.
        for role_idx in list(visible_roles):
            if role_idx == keep:
                continue
            pending.append(action("C_roleOut", roleIdx=role_idx))
            pending.append(action("DelayTime", delaytime=0.5))
            visible_roles.pop(role_idx)

    for kind, args in events:
        if kind == "change_music":
            music = Path(args[0]).stem
            music_names.add(music)
            if first_music_name is None:
                first_music_name = music
            if not first_music:
                pending.append(action("StopBGM"))
            pending.append(action("PlayBGM", sndID=BGM_IDS[music]))
            first_music = False
        elif kind == "stop_music":
            pending.append(action("StopBGM"))
            first_music = True
        elif kind in {"change_background", "show_background"}:
            remove_visible_roles()
            dual_mode = False
            secondary_sprite = None
            name = background_name(args[0])
            background_names.add(name)
            pending.append(action("C_changeBG", picName=name))
            if screen_dark:
                pending.append(action("HideColor", layerType="C"))
            screen_dark = False
            first_background = False
        elif kind in {"hide_background", "hide_background_with_fade"}:
            remove_visible_roles()
            dual_mode = False
            secondary_sprite = None
            if not screen_dark and not first_background:
                pending.append(action("FillColor", layerType="C"))
            screen_dark = True
        elif kind == "show_character":
            primary_sprite = args[0]
            primary_expression = args[1]
            secondary_sprite = None
            dual_mode = False
        elif kind == "show_2nd_character":
            secondary_sprite = args[0]
            secondary_expression = args[1]
            dual_mode = True
        elif kind == "change_expression":
            primary_expression = args[0]
        elif kind == "hide_character":
            remove_visible_roles()
            primary_sprite = None
            secondary_sprite = None
            dual_mode = False
        elif kind == "hide_all_characters":
            remove_visible_roles()
            primary_sprite = None
            secondary_sprite = None
            dual_mode = False
        elif kind == "character_light":
            if len(args) > 1 and isinstance(args[-1], str):
                primary_expression = args[-1]
            ignored_count[kind] = ignored_count.get(kind, 0) + 1
        elif kind == "character_2nd_light":
            if len(args) > 1 and isinstance(args[-1], str):
                secondary_expression = args[-1]
            ignored_count[kind] = ignored_count.get(kind, 0) + 1
        elif kind in IGNORED_VISUAL_EVENTS:
            ignored_count[kind] = ignored_count.get(kind, 0) + 1
        elif kind in {"show_dialog", "show_text_only"}:
            if kind == "show_dialog":
                word, speaker = args
                speaker = speaker.strip()
            else:
                (word,) = args
                speaker = ""
            word = word.replace("\t", " ").replace("\r", "").replace("\n", "\\n")
            if not word or "\n" in word:
                raise ValueError(f"Invalid chapter {episode} sentence text")
            idx = len(lines)
            # In the original converted 19th lesson, a named line without a
            # matching visible sprite is spoken as C_speakAside.  Treating
            # every known name as a portrait speaker makes an unseen role
            # claim a slot and can leave stale portraits in RoleSpeak's map.
            portrait_speakers = {sprite_speaker(primary_sprite)}
            if dual_mode:
                portrait_speakers.add(sprite_speaker(secondary_sprite))
            if speaker in ROLE_SN and speaker in portrait_speakers:
                role_idx = ensure_role(speaker)
                if not dual_mode or (role_idx not in visible_roles and
                                     len(visible_roles) >= 2):
                    remove_visible_roles(keep=role_idx)
                if speaker == sprite_speaker(primary_sprite):
                    face = original_face(ROLE_SN[speaker], primary_expression)
                elif speaker == sprite_speaker(secondary_sprite):
                    face = original_face(ROLE_SN[speaker], secondary_expression)
                else:
                    face = FACE_DEFAULT[ROLE_SN[speaker]]
                pending.append(action("C_roleSpeak", enableSentenceMapping=True,
                                      _roleIdx=role_idx, faceStr=face,
                                      wordStr=word, sentenceIdx=idx,
                                      spRoleName=""))
                visible_roles[role_idx] = None
            else:
                remove_visible_roles()
                pending.append(action("C_speakAside", enableSentenceMapping=True,
                                      spName=speaker, wordStr=word,
                                      sentenceIdx=idx))
            fields = [str(idx + 1), speaker or "N/A"] + [word] * 5 + [""]
            lines.append("\t".join(fields) + "\r\n")
            node_id = str(idx + 1)
            nodes.append({
                "_roundInfo": {
                    "_b4cmdActionList": {"actions": pending},
                    "_a4cmdActionList": {"actions": []},
                },
                "_position": {"x": 3000.0, "y": float(idx * 80)},
                "$type": "NodeCanvas.GuideLessonTrees.GuideRoundNode",
                "$id": node_id,
            })
            if idx:
                connections.append({
                    "_sourceNode": {"$ref": str(idx)},
                    "_targetNode": {"$ref": node_id},
                    "$type": "NodeCanvas.GuideLessonTrees.GLTConnection",
                })
            pending = []
        elif kind == "end_story_episode":
            pass
        else:
            raise ValueError(f"Unmapped editor action: {kind}")
    if not nodes:
        raise ValueError("Empty story graph")
    nodes[-1]["_roundInfo"]["_a4cmdActionList"]["actions"] = (
        pending + [action("StopBGM"), action("C_end"), action("EndLesson")])
    graph["nodes"] = nodes
    graph["connections"] = connections
    graph["primeNode"] = {"$ref": "1"}
    graph["derivedData"]["claimInfo"]["role"] = [
        {"roleSN": ROLE_SN[name], "name": name} for name in role_names]
    graph["derivedData"]["claimInfo"]["defaultBGM"] = str(
        BGM_IDS.get(first_music_name, 99120100250))
    graph["derivedData"]["sentenceFName"] = f"sentence_303{episode}.txt"
    info = {"sentences": len(lines), "roles": role_names,
            "backgrounds": sorted(background_names), "music": sorted(music_names),
            "visualEventsApproximated": ignored_count}
    return graph, lines, info


def patch_lesson(raw: bytes, episode: int, graph: dict) -> bytes:
    env = UnityPy.load(raw)
    obj = next(o for o in env.objects if o.type.name == "MonoBehaviour")
    tree = obj.read_typetree()
    if tree["m_Name"] != "lesson303190" or tree["sentenceFileName"] != "sentence_303190.txt":
        raise ValueError("Unreviewed lesson template")
    tree["m_Name"] = f"lesson303{episode}"
    tree["sentenceFileName"] = f"sentence_303{episode}.txt"
    tree["_serializedGraph"] = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    obj.save_typetree(tree)
    clone_identity(env, "lesson303190", f"lesson303{episode}")
    result = env.file.save(packer="original")
    check = UnityPy.load(result)
    check_tree = next(o.read_typetree() for o in check.objects if o.type.name == "MonoBehaviour")
    if check_tree["m_Name"] != tree["m_Name"] or json.loads(check_tree["_serializedGraph"]) != graph:
        raise ValueError("Lesson bundle round-trip failed")
    return result


def patch_sentence(raw: bytes, episode: int, lines: list[str]) -> bytes:
    env = UnityPy.load(raw)
    obj = next(o for o in env.objects if o.type.name == "MonoBehaviour")
    tree = obj.read_typetree()
    if tree["m_Name"] != "sentence_303190":
        raise ValueError("Unreviewed sentence template")
    tree["m_Name"] = f"sentence_303{episode}"
    payload = codecs.BOM_UTF8 + "".join(lines).encode("utf-8")
    tree["bytes"] = [x ^ 255 for x in payload]
    obj.save_typetree(tree)
    clone_identity(env, "sentence_303190", f"sentence_303{episode}")
    result = env.file.save(packer="original")
    check = UnityPy.load(result)
    check_tree = next(o.read_typetree() for o in check.objects if o.type.name == "MonoBehaviour")
    if check_tree["m_Name"] != tree["m_Name"] or bytes(x ^ 255 for x in check_tree["bytes"]) != payload:
        raise ValueError("Sentence bundle round-trip failed")
    return result


def patch_background(raw: bytes, name: str, png: Path) -> bytes:
    env = UnityPy.load(raw)
    obj = next(o for o in env.objects if o.type.name == "Texture2D")
    texture = obj.read()
    if texture.m_Name != "bg_stardust_recording":
        raise ValueError("Unreviewed background template")
    with Image.open(png) as source:
        image = source.convert("RGBA")
    if image.size != (1024, 576):
        raise ValueError("Unexpected source background size: " + str(png))
    texture.m_Name = name
    texture.image = image
    texture.save()
    clone_identity(env, "bg_stardust_recording", name)
    result = env.file.save(packer="original")
    check = UnityPy.load(result)
    check_texture = next(o.read() for o in check.objects if o.type.name == "Texture2D")
    if check_texture.m_Name != name or check_texture.image.convert("RGBA").tobytes() != image.tobytes():
        raise ValueError("Background bundle pixel round-trip failed: " + name)
    return result


def csv_bundle(raw: bytes, transform) -> bytes:
    env = UnityPy.load(raw)
    obj = next(o for o in env.objects if o.type.name == "MonoBehaviour")
    tree = obj.read_typetree()
    original = bytes(x ^ 255 for x in tree["bytes"])
    if not original.startswith(codecs.BOM_UTF8):
        raise ValueError("Unreviewed CSV encoding")
    updated = transform(original.decode("utf-8-sig"))
    tree["bytes"] = [x ^ 255 for x in codecs.BOM_UTF8 + updated.encode("utf-8")]
    obj.save_typetree(tree)
    result = env.file.save(packer="original")
    check = UnityPy.load(result)
    check_tree = next(o.read_typetree() for o in check.objects if o.type.name == "MonoBehaviour")
    if bytes(x ^ 255 for x in check_tree["bytes"]) != codecs.BOM_UTF8 + updated.encode("utf-8"):
        raise ValueError("CSV bundle round-trip failed")
    return result


def story_text(source: str) -> str:
    lines = source.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n").split(",")
    if header[:9] != ["ID", "channel_group", "type", "name", "file",
                      "isWrite", "story_group", "serial", "sort_num"] or header[-1] != "can_see":
        raise ValueError("Unreviewed Story table columns")
    results = []
    channels = set()
    for line in lines:
        row = line.rstrip("\r\n").split(",")
        if row[0] == "61300041020":
            if len(row) != len(header) or row[1] in channels:
                raise ValueError("Unexpected chapter 20 row")
            channels.add(row[1])
            if row[1] == "25":
                row[5] = "1"
                row[-1] = "1"
                line = ",".join(row) + line[len(line.rstrip("\r\n")):]
            results.append(line)
            successor = row.copy()
            successor[0] = "61300041021"
            successor[3] = "16130004102101"
            successor[4] = "30321"
            successor[7:9] = ["21", "21"]
            if row[1] != "25":
                successor[5] = "0"
                successor[-1] = "0"
            results.append(",".join(successor) + line[len(line.rstrip("\r\n")):])
        else:
            if row[0] == "61300041021":
                raise ValueError("Chapter 21 already exists")
            results.append(line)
    if channels != {"22", "25", "70"}:
        raise ValueError("Unexpected chapter 20 channel set")
    return "".join(results)


def dictionary_text(source: str) -> str:
    lines = source.splitlines(keepends=True)
    if not lines[0].startswith("ID\tcontent_chinese\tcontent_tw"):
        raise ValueError("Unreviewed Dictionary table")
    output = []
    hits = 0
    for line in lines:
        row = line.rstrip("\r\n").split("\t")
        if row[0] == "16130004102001":
            if hits or len(row) != 8 or "缺原版资源" not in row[1]:
                raise ValueError("Unexpected chapter 20 title")
            hits += 1
            row[1] = "第20节"
            output.append("\t".join(row) + line[len(line.rstrip("\r\n")):])
            row[0] = "16130004102101"
            row[1:6] = ["第21节", "第21節", "第21節", "제21절", "Part 21"]
            output.append("\t".join(row) + line[len(line.rstrip("\r\n")):])
        else:
            if row[0] == "16130004102101":
                raise ValueError("Chapter 21 title already exists")
            output.append(line)
    if hits != 1:
        raise ValueError("Missing chapter 20 title")
    return "".join(output)


def patch_index(raw: bytes, bundles: dict[str, bytes]) -> bytes:
    source = raw.decode("utf-8")
    rows = source.splitlines(keepends=True)
    target = {"/" + name.removeprefix(PREFIX): content for name, content in bundles.items()}
    seen = set()
    result = []
    for line in rows:
        match = re.fullmatch(r"([0-9a-f]{32})=(/[^:]+):(\d+)(\r?\n)?", line)
        if not match:
            raise ValueError("Unreviewed asset index syntax")
        path = match.group(2)
        if path in target:
            if path in seen:
                raise ValueError("Duplicate asset index entry")
            seen.add(path)
            content = target[path]
            result.append(f"{hashlib.md5(content).hexdigest()}={path}:{len(content)}" +
                          (match.group(4) or "\n"))
        else:
            result.append(line)
    for path, content in sorted(target.items()):
        if path not in seen:
            result.append(f"{hashlib.md5(content).hexdigest()}={path}:{len(content)}\n")
    updated = "".join(result).encode("utf-8")
    for path, content in target.items():
        expected = f"{hashlib.md5(content).hexdigest()}={path}:{len(content)}"
        if updated.decode("utf-8").count(expected) != 1:
            raise ValueError("Asset index mismatch: " + path)
    return updated


def write_blob(content: bytes) -> str:
    digest = sha(content)
    path = BLOBS / digest
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("Content-addressed blob collision")
    else:
        path.write_bytes(content)
    return digest


def build() -> dict:
    with APK.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != APK_SHA256:
            raise ValueError("Unreviewed v102 APK")
    assets = {}
    details = {}
    with zipfile.ZipFile(APK) as source:
        graph_template = json.loads(next(o.read_typetree()["_serializedGraph"]
            for o in UnityPy.load(source.read(LESSON_TEMPLATE)).objects
            if o.type.name == "MonoBehaviour"))
        all_background_paths = {}
        for episode in (20, 21):
            events = source_events(episode)
            graph, sentences, info = graph_from_events(graph_template, episode, events)
            details[str(episode)] = info
            lesson_member = PREFIX + f"assets/resources/guide/lesson/lesson303{episode}.ab"
            sentence_member = PREFIX + f"config/lesson/sentence_303{episode}.ab"
            if lesson_member in source.namelist() or sentence_member in source.namelist():
                raise ValueError("Chapter already exists in baseline APK")
            assets[lesson_member] = patch_lesson(source.read(LESSON_TEMPLATE), episode, graph)
            assets[sentence_member] = patch_sentence(source.read(SENTENCE_TEMPLATE), episode, sentences)
            for kind, args in events:
                if kind in {"change_background", "show_background"}:
                    name = background_name(args[0])
                    png = GODOT / args[0].removeprefix("res://")
                    if not png.is_file():
                        raise FileNotFoundError(png)
                    all_background_paths[name] = png
        new_backgrounds = []
        for name, png in sorted(all_background_paths.items()):
            member = background_member(name)
            if member not in source.namelist():
                assets[member] = patch_background(source.read(BACKGROUND_TEMPLATE), name, png)
                new_backgrounds.append(name)
        assets[STORY_TABLE] = csv_bundle(source.read(STORY_TABLE), story_text)
        assets[DICTIONARY_TABLE] = csv_bundle(source.read(DICTIONARY_TABLE), dictionary_text)
        index = patch_index(source.read(INDEX), assets)
    BLOBS.mkdir(parents=True, exist_ok=True)
    asset_report = {member.removeprefix("assets/"): {
        "sha256": write_blob(raw), "bytes": len(raw)} for member, raw in sorted(assets.items())}
    index_sha = write_blob(index)
    report = {
        "sourceApk": str(APK), "sourceApkSha256": APK_SHA256,
        "editorSourceSha256": {str(key): value for key, value in SCRIPT_HASHES.items()},
        "chapters": details, "newBackgrounds": new_backgrounds,
        "assets": asset_report,
        "apkAssetIndex": {"sha256": index_sha, "bytes": len(index)},
        "runtimeValidated": False,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json.loads(REPORT.read_text(encoding="utf-8")) != report:
        raise ValueError("Resource report write verification failed")
    return report


if __name__ == "__main__":
    result = build()
    print("STARDUST_20_21_RESOURCES_OK", len(result["assets"]),
          result["chapters"]["20"]["sentences"],
          result["chapters"]["21"]["sentences"])
