"""Client table support for the deliberately simplified mainline battles.

Keep every original lesson asset and all non-campaign triggers. UIEvtType has
no None member: LessonTrigger .ctor calls Enum.Parse (ARM64 0x3E2EF10).
Instead use an unreachable, numeric negative level parameter for exactly six
PreCombatBegin records. get_uiEvtID concatenates type + parameter (0x3E2F38C)
and event dispatch uses an exact dictionary key (0x3E36820).
"""

import codecs
import hashlib

import UnityPy

from patch_feature_level_gates import _csv_tree


BATTLE_GUIDES = {
    "201": ("3110001001", "04004"),
    "204": ("3110001002", "00101"),
    "206": ("3110001003", "00103"),
    "209": ("3110001005", "00106"),
    "211": ("3110001007", "00109"),
    "213": ("3110001009", "00503"),
}
MAINLINE_IDS = frozenset(
    str(3110000000 + chapter * 1000 + stage)
    for chapter in range(1, 17)
    for stage in range(1, 11 if chapter == 1 else 16)
)
CHAPTER16_IDS = frozenset(str(3110016000 + stage) for stage in range(1, 16))
ORIGINAL_DUPLICATE_MOB_IDS = frozenset(str(3110012000 + stage) for stage in (1, 3, 5, 7, 9))


def _repeatable_mainline(identity: str) -> bool:
    if identity not in MAINLINE_IDS:
        raise ValueError("Not a mainline stage: " + identity)
    stage = int(identity) % 1000
    # Original Instance table: even normal stages and elite stages are
    # repeatable. The missing chapter-16 MobList rows follow this same rule.
    return stage > 10 or stage % 2 == 0


def patch_lesson_text(text: str) -> str:
    lines = text.splitlines(keepends=True)
    expected_header = "recID,nextID,localPrefID,quest1,quest2,quest3,fileSuffixName,storyID,storyGroupID,uiEvtType,uiEvtParam,roleLvConstrain,channel_group,comment"
    if not lines or lines[0].rstrip("\r\n") != expected_header:
        raise ValueError("Unexpected LessonTrigger header")
    seen, output = set(), []
    for line in lines:
        content = line.rstrip("\r\n")
        columns = content.split(",")
        identity = columns[0]
        if identity in BATTLE_GUIDES:
            stage, lesson = BATTLE_GUIDES[identity]
            if identity in seen or len(columns) < 14:
                raise ValueError("Duplicate or malformed mainline battle guide")
            if columns[1] != "-1" or columns[3:6] != ["-1"] * 3 or \
                    columns[6] != lesson or columns[9] != "PreCombatBegin" or \
                    columns[10] not in (stage, "-" + stage) or columns[12] != "0":
                raise ValueError("Mainline battle guide identity changed: " + identity)
            seen.add(identity)
            columns[10] = "-" + stage
            line = ",".join(columns) + line[len(content):]
        elif len(columns) > 10 and columns[9] == "PreCombatBegin" and columns[10] in MAINLINE_IDS:
            raise ValueError("Unexpected additional mainline battle guide")
        output.append(line)
    # The preserved APK already removed all 200-217 records. Do not re-add
    # disabled rows just to claim a mutation; keep that known absent state.
    if not seen:
        identities = {line.split(",", 1)[0] for line in lines}
        if not {"1", "2", "3", "4", "13", "50", "218", "219"} <= identities:
            raise ValueError("Not the known preserved LessonTrigger table")
        return text
    if seen != set(BATTLE_GUIDES):
        raise ValueError("Six expected battle guides not found")
    result = "".join(output)
    for before, after in zip(lines, result.splitlines(keepends=True)):
        identity = before.split(",", 1)[0]
        if identity not in BATTLE_GUIDES and before != after:
            raise ValueError("Unrelated guide changed")
    return result


def patch_moblist_text(text: str) -> str:
    lines = text.splitlines(keepends=True)
    header = lines[0].rstrip("\r\n").split(",") if lines else []
    expected = ["ID", "mapID", "instObjectiveType", "instBonusType", "intstBonusParam", "time", "globalbuff"]
    for prefix in ("mob", "npc"):
        for index in range(1, 6):
            expected.extend([prefix + str(index), prefix + str(index) + "_type", prefix + str(index) + "_lv"])
    if header != expected:
        raise ValueError("Unexpected InstanceMobList header")
    newline = "\r\n" if lines[0].endswith("\r\n") else "\n"
    # Enemy model mob_422 is selected by original Monster ID 331010342201.
    # This is an intentionally simple preview, not original-server combat data.
    def row(identity, bonus_type):
        cols = [identity, "1010", "0", bonus_type, "0", "300", "0", "331010342201", "1", "1"]
        return ",".join(cols + [""] * (len(header) - len(cols)))
    seen, duplicates, output, expected_rows = set(), set(), [], {}
    for line in lines:
        content = line.rstrip("\r\n")
        identity = content.split(",", 1)[0]
        if identity in MAINLINE_IDS:
            columns = content.split(",")
            # Original rows may omit trailing empty mob/npc columns.
            if len(columns) < 4 or len(columns) > len(header) or columns[3] not in {"0", "1", "2", "3", "4"}:
                raise ValueError("Unexpected mainline bonus type: " + identity)
            if identity in seen:
                if identity not in ORIGINAL_DUPLICATE_MOB_IDS or identity in duplicates:
                    raise ValueError("Unexpected duplicate campaign mob row")
                duplicates.add(identity)
                continue
            seen.add(identity)
            # Native ProgressInfoHelper hides Sweep whenever instBonusType=0.
            # Keep each original nonzero bonus type; the old temporary patch
            # had zeroed every row, so recover a repeatable row with type 2.
            bonus_type = columns[3] if columns[3] != "0" else (
                "2" if _repeatable_mainline(identity) else "0")
            expected_rows[identity] = row(identity, bonus_type)
            line = expected_rows[identity] + line[len(content):]
        output.append(line)
    missing = MAINLINE_IDS - seen
    if missing not in (CHAPTER16_IDS, frozenset()):
        raise ValueError("Expected 220 original or 235 patched mainline mob rows")
    if missing:
        if output and not output[-1].endswith(("\r", "\n")):
            output[-1] += newline
        for identity in sorted(missing):
            bonus_type = "2" if _repeatable_mainline(identity) else "0"
            expected_rows[identity] = row(identity, bonus_type)
            output.append(expected_rows[identity] + newline)
    result = "".join(output)
    updated = {line.split(",", 1)[0]: line for line in result.splitlines()
               if line.split(",", 1)[0] in MAINLINE_IDS}
    if set(updated) != MAINLINE_IDS or any(updated[k] != expected_rows[k] for k in MAINLINE_IDS):
        raise ValueError("Campaign preview rows incomplete")
    # Every unrelated original line remains byte-for-byte; no filters/reorders.
    untouched_before = [line for line in text.splitlines() if line.split(",", 1)[0] not in MAINLINE_IDS]
    untouched_after = [line for line in result.splitlines() if line.split(",", 1)[0] not in MAINLINE_IDS]
    if untouched_after != untouched_before:
        raise ValueError("Non-mainline mob data changed")
    return result


def _patch(raw: bytes, asset_name: str, transform) -> bytes:
    env, item, tree, original, bom = _csv_tree(raw, asset_name)
    before = {obj.path_id: hashlib.sha256(obj.get_raw_data()).digest() for obj in env.objects}
    expected = transform(original)
    if expected == original:
        return raw
    encoded = (codecs.BOM_UTF8 if bom else b"") + expected.encode("utf-8")
    tree["bytes"] = [byte ^ 255 for byte in encoded]
    item.save_typetree(tree)
    result = env.file.save(packer="original")
    verified, changed, other_tree, readback, other_bom = _csv_tree(result, asset_name)
    if readback != expected or other_bom != bom:
        raise ValueError("Simplified campaign bundle round-trip mismatch")
    if {obj.path_id for obj in verified.objects} != set(before):
        raise ValueError("Unity object set changed")
    for obj in verified.objects:
        if obj.path_id != item.path_id and hashlib.sha256(obj.get_raw_data()).digest() != before[obj.path_id]:
            raise ValueError("Unrelated Unity object changed")
    original_meta = {k: v for k, v in tree.items() if k != "bytes"}
    if {k: v for k, v in other_tree.items() if k != "bytes"} != original_meta:
        raise ValueError("Unrelated table metadata changed")
    if transform(readback) != readback:
        raise ValueError("Patch is not idempotent")
    return result


def patch_bundle(raw: bytes) -> bytes:
    """Patch config/clientexel/lessontrigger.ab; update asset index afterwards."""
    return _patch(raw, "LessonTrigger", patch_lesson_text)


def patch_simple_moblist(raw: bytes) -> bytes:
    """Patch config/clientexel/instancemoblist.ab; update asset index afterwards."""
    return _patch(raw, "InstanceMobList", patch_moblist_text)
