"""Build an isolated signed151 weapon/targeting candidate; never deploy it.

This repairs verified argument collisions, weapon-trigger currentSkill capture,
and four fixed-target selectors. It
preserves the offline damage values, attack phases, weapon switching, and mixed
area/random summons. It does not claim to recover missing original server args.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
sys.path[:0] = [r"D:\Environment\UnityTools\python-libs",
                r"D:\Environment\UnityTools\ProtocolBuffers\python"]
import UnityPy
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

PROJECT = Path(r"D:\Project\魔女兵器在线版")
RECOVERY = Path(r"D:\Project\魔女兵器工程恢复")
HOT_ROOT = PROJECT / "热更新测试/主线热更候选"
APK = PROJECT / "构建/运行性能修复/魔女兵器-在线本地双区服-v119-测试.apk"
SEED = PROJECT / "legacy-server/resources/offline_responses.json"
DESCRIPTORS = RECOVERY / "原版/原生代码/协议描述符/game-descriptors-complete.pb"
NATIVE = RECOVERY / "原版/原生代码/输入/arm64/libil2cpp.so"
SPELL_PATH = "assetbundle/config/xmlconf/skill/spells.ab"
BASE_SEQUENCE = "151-5828bc45e31ec52fb8d3f30e87098dd74e1d94a66eaa603796ba7a400486a4af"
BASE_SPELL_SHA = "d8322a1919ce488590b27fa4e48a78519fd4304a9649ddf7ea736ad11ef3d8dd"
# Current coefficient, source attack factor, local flat value. No balancing edits.
NORMALS = {
    1701010102: (95000030, "SH", (13500, 10000, 90)),
    1701140101: (95000290, "DW", (4500, 10000, 8)),
    1701150102: (95000320, "DW", (5800, 10000, 0)),
}
SUMMONS = {111: 2010311102, 114: 2010311402,
           115: 2010311502, 127: 2010312701}
# Entity.ReleaseSkill writes currentSkill for COMMON=1 / ACTIVE=2 only.
# Trigger-owned weapon effects use WEAPON=4 and retain the same caller.
WEAPON_TRIGGER_SPELLS = {
    91000030: "Offline_Weapon_1701010102",
    91000290: "Offline_Weapon_1701140101",
    91000291: "Offline_Weapon_1701140101_1",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def native_evidence():
    original = NATIVE.read_bytes()
    with zipfile.ZipFile(APK) as archive:
        current = archive.read("lib/arm64-v8a/libil2cpp.so")

    def offset(data, rva, size):
        require(data[:6] == b"\x7fELF\x02\x01", "Expected little-endian ELF64")
        table = struct.unpack_from("<Q", data, 32)[0]
        entry_size, count = struct.unpack_from("<HH", data, 54)
        for index in range(count):
            kind, _, file_pos, virtual, _, file_size, _, _ = struct.unpack_from(
                "<IIQQQQQQ", data, table + index * entry_size)
            if kind == 1 and virtual <= rva and rva + size <= virtual + file_size:
                return file_pos + rva - virtual
        raise ValueError("RVA is outside file-backed ELF segments")

    methods = [
        ("Entity.ReleaseSkill", 0x132244C, 0x13225E4),
        ("Entity.RemoveSkill", 0x1321BAC, 0x1321CA4),
        ("Skill.Initialize", 0x151241C, 0x1512464),
        ("Skill.Update", 0x151251C, 0x1512894),
        ("Skill.OnStartPoint", 0x1515468, 0x1515C44),
        ("Skill.OnReleasePoint", 0x15147DC, 0x1514E08),
        ("Skill.OnEffectPoint", 0x1516A28, 0x1516CC4),
        ("PassiveTrigger.TriggerSkill", 0x3B16628, 0x3B16A08),
        ("HeroEntity.onEvent", 0x3B60F08, 0x3B61344),
    ]
    records = []
    for name, start, end in methods:
        length = end - start
        old_pos, new_pos = offset(original, start, length), offset(current, start, length)
        old, new = original[old_pos:old_pos + length], current[new_pos:new_pos + length]
        require(old == new, f"Inspected native method differs from APK: {name}")
        records.append({"method": name, "rva": hex(start), "endRvaExclusive": hex(end),
                        "fileOffset": old_pos, "apkFileOffset": new_pos,
                        "length": length, "sha256": sha(old), "matchesApk": True})
    ranges = [(0x1322500, 0x1322564), (0x13225B0, 0x13225E4),
              (0x1321C78, 0x1321C8C), (0x151242C, 0x1512464),
              (0x15126D0, 0x1512758), (0x1515B50, 0x1515B94),
              (0x1514D74, 0x1514E08), (0x3B16748, 0x3B167E8)]
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    instructions = []
    for start, end in ranges:
        pos = offset(original, start, end - start)
        instructions.extend({"rva": hex(i.address), "bytes": bytes(i.bytes).hex(),
                             "instruction": i.mnemonic + " " + i.op_str}
                            for i in decoder.disasm(original[pos:pos + end - start], start))
    lookup = {int(x["rva"], 16): x["instruction"] for x in instructions}
    for rva, expected in {
        0x1322504: "cmp w8, #2", 0x132251C: "cmp w8, #1",
        0x1322550: "ldrb w9, [x8, #0xe8]", 0x132255C: "str x8, [x19, #0x118]",
        0x13225E0: "b #0x1521654", 0x1321C88: "str xzr, [x19, #0x118]",
        0x1512434: "stp x1, x3, [x19, #0x40]", 0x1512460: "b #0x151251c",
        0x1512754: "b #0x1512a84", 0x1515B90: "b #0x15147dc",
        0x3B167E4: "blr x9",
    }.items():
        require(lookup.get(rva) == expected, f"Native evidence opcode drift at {rva:#x}")
    return {"schema": 1, "originalLib": str(NATIVE), "apk": str(APK),
            "apkEntry": "lib/arm64-v8a/libil2cpp.so", "methods": records,
            "instructions": instructions,
            "constants": {"TYPE_COMMON": 1, "TYPE_ACTIVE": 2, "TYPE_PASSIVE": 3, "TYPE_WEAPON": 4},
            "constantSource": str(RECOVERY / "原版/原生代码/类型与方法索引/dump.cs"),
            "configurationPatch": {str(sid): {"SpellType": 4} for sid in WEAPON_TRIGGER_SPELLS},
            "limits": ["原CSV的spell_type=04是武器类别证据；缺少原服每条触发子技能的完整SkillInfo",
                       "证实当前类型会抢占currentSkill及新类型避开赋值，不等于设备战斗验收"]}


def role_class():
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.ParseFromString(DESCRIPTORS.read_bytes())
    pool = descriptor_pool.DescriptorPool()
    pending = list(descriptors.file)
    while pending:
        previous = len(pending)
        for file in pending[:]:
            try:
                pool.Add(file)
                pending.remove(file)
            except Exception:
                pass
        require(len(pending) < previous, "Unresolved protobuf descriptor dependencies")
    effects = pool.FindMessageTypeByName("combatmod.EffectArgumentInfo")
    require(all(f"Argument{x}" in effects.fields_by_name for x in (25, 26, 27)),
            "EffectArgumentInfo must expose argument slots 25..27")
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("combatmod.RoleCombatInfoProto"))


def read_current_spell(apk=APK, hot_root=HOT_ROOT):
    current = (hot_root / "current").read_text(encoding="utf-8-sig").strip()
    require(current == BASE_SEQUENCE, "Candidate is pinned to the inspected signed151 release")
    manifest = json.loads((hot_root / "releases" / current / "manifest.json").read_text(encoding="utf-8-sig"))
    asset = next((a for a in manifest["assets"] if a["path"] == SPELL_PATH), None)
    if asset:
        data = (hot_root / "blobs" / asset["sha256"]).read_bytes()
        require(sha(data) == asset["sha256"], "Signed spell blob hash mismatch")
    else:
        with zipfile.ZipFile(apk) as archive:
            data = archive.read("assets/" + SPELL_PATH)
    require(sha(data) == BASE_SPELL_SHA, "Unexpected spells.ab baseline")
    return data


def load_spell_bundle(data):
    environment = UnityPy.load(data)
    matches = []
    for obj in environment.objects:
        if obj.type.name == "MonoBehaviour":
            tree = obj.read_typetree()
            if "bytes" in tree:
                payload = bytes(tree["bytes"])
                if tree.get("isEncrypt"):
                    payload = bytes(x ^ 255 for x in payload)
                if b"SpellEffect" in payload:
                    matches.append((obj, tree, ET.fromstring(payload)))
    require(len(matches) == 1, "Expected one XML spell payload")
    return environment, *matches[0]


def template_map(root):
    result = {x.get("TempletID"): x for x in root if x.tag == "SpellEffect"}
    # Five duplicate names already ship in signed151. Do not normalize or remove
    # those unrelated records; demand uniqueness only for the candidate scope.
    names = [x.get("TempletID") for x in root if x.tag == "SpellEffect"]
    scoped = [f"Offline_Normal_{wid}" for wid in NORMALS]
    scoped += [f"Offline_Roster{s}_{kind}" for s in SUMMONS for kind in ("Summon", "Effect")]
    require(all(names.count(name) == 1 for name in scoped), "Ambiguous candidate template ID")
    return result


def native_attack_packs(template):
    return [x for x in template.iter("CreateDamagePack") if x.get("DamageTag") == "248"]


def repair_xml(root):
    original_records = [ET.tostring(x) for x in root]
    before = template_map(copy.deepcopy(root))
    templates = template_map(root)
    changed = set()
    for wid, (_, family, _) in NORMALS.items():
        name = f"Offline_Normal_{wid}"
        template = templates[name]
        source = templates[f"Player_NormalAttack_{family}_01"]
        require(not any(re.search(r"@ARGUMENT(?:25|26|27|28)\b", str(v))
                        for x in template.iter() for v in x.attrib.values()),
                f"{name}: new slots already used")
        packs = [x for x in template.iter("CreateDamagePack")
                 if x.get("DamageTag") == "0" and x.get("SPMDmgP") == "@ARGUMENT20"]
        require(len(packs) == len(native_attack_packs(source)), f"{name}: unexpected extra pack count")
        for pack in packs:
            require(pack.get("SPMAP") == "@ARGUMENT21" and pack.get("SPMAV") == "@ARGUMENT22",
                    f"{name}: unexpected extra pack coefficients")
            pack.set("SPMDmgP", "@ARGUMENT25")
            pack.set("SPMAP", "@ARGUMENT26")
            pack.set("SPMAV", "@ARGUMENT27")
        # No phase removal, timing change, animation change, or new damage pack.
        old = before[name]
        require(len(template.findall("FuncDef")) == len(old.findall("FuncDef")), "Attack phases changed")
        require([x.attrib for x in native_attack_packs(template)] ==
                [x.attrib for x in native_attack_packs(old)], "Base attack packets changed")
        # Keep legacy coefficients in 19..22 for old clients. In this new XML,
        # original empty sound values read a verified empty slot instead.
        sound_slots = {"@ARGUMENT20", "@ARGUMENT21", "@ARGUMENT22"}
        if wid == 1701010102:
            sound_slots.add("@ARGUMENT19")
        for sound in template.iter("LinkString"):
            if sound.get("String2") in sound_slots:
                sound.set("String2", "@ARGUMENT28")
        for current, previous in zip(template.iter("LinkString"), old.iter("LinkString")):
            expected = dict(previous.attrib)
            if expected.get("String2") in sound_slots:
                expected["String2"] = "@ARGUMENT28"
            require(current.attrib == expected, "Unrelated sound reference changed")
        changed.add(name)
    for servant in SUMMONS:
        outer_name = f"Offline_Roster{servant}_Summon"
        outer = templates[outer_name]
        require(len(list(outer.iter("CreateAgent"))) == 1, "Unexpected outer summon")
        targets = list(outer.iter("TargetSelect"))
        require(len(targets) == 1 and targets[0].get("TargetArgu4") == "3", "Outer target drift")
        targets[0].set("TargetArgu4", "2")
        inner_name = f"Offline_Roster{servant}_Effect"
        inner = templates[inner_name]
        ranges = list(inner.iter("RangeSelect"))
        require(ranges and all(x.get("RangeType") == "3" and x.get("RangeArgu1") == "1500"
                               for x in ranges), "Unexpected inner summon range")
        for node in ranges:
            node.set("RangeType", "1")
            node.set("RangeArgu1", "0")
        require([x.attrib for x in inner.iter("CreateDamagePack")] ==
                [x.attrib for x in before[inner_name].iter("CreateDamagePack")],
                "Summon damage values changed")
        changed.update((outer_name, inner_name))
    require(set(templates) == set(before), "Template set changed")
    for name in set(templates) - changed:
        require(ET.tostring(templates[name]) == ET.tostring(before[name]), f"Unrelated template {name} changed")
    for node, original in zip(root, original_records):
        if node.get("TempletID") not in changed:
            require(ET.tostring(node) == original, "Unrelated/duplicate XML record changed")
    return sorted(changed)


def repair_role(message):
    original = type(message)()
    original.CopyFrom(message)
    spells = {x.ID: x for x in message.Unit.SpellInfos}
    effects = {x.ID: x for x in message.Unit.EffectArgumentInfos}
    agents = {x.ID: x for x in message.Unit.AgentInfos}
    patches = {"effectArgumentPatches": [], "spellInfoPatches": [],
               "agentInfoPatches": [], "servantCombatPatches": []}
    for wid, (normal, family, values) in NORMALS.items():
        for sid in (normal, normal + 1):
            spell = spells[sid]
            require(spell.SpellTempletId == f"Offline_Normal_{wid}", "Normal reference drift")
            effect = effects[spell.SpellEffectArgu]
            require(tuple(getattr(effect, f"Argument{x}") for x in (20, 21, 22)) == values,
                    "Normal coefficients differ from inspected seed")
            require(not any(getattr(effect, f"Argument{x}") for x in (25, 26, 27, 28)), "Destination slots occupied")
            updates = {f"Argument{x}": value for x, value in zip((25, 26, 27), values)}
            updates["Argument28"] = 0
            # Keep this legacy marker: old clients still receive identical data.
            if wid == 1701010102:
                require(effect.Argument19 == 2, "Unexpected SH conversion marker")
            # Source seed kept no original sound IDs. Restore its actual zero values.
            source_sounds = [effects[s.SpellEffectArgu] for s in message.Unit.SpellInfos
                             if s.SpellTempletId == f"Player_NormalAttack_{family}_01"]
            require(source_sounds and all(not getattr(e, f"Argument{x}") for e in source_sounds
                                          for x in (19, 20, 21, 22)), "Cannot infer source sound values")
            for key, value in updates.items():
                setattr(effect, key, value)
            patches["effectArgumentPatches"].append({"ID": effect.ID, "set": updates})
    enemy_target = {"TargetTypeTrue": 1, "TargetTypeTrue1": 1,
                    "TargetTypeNominal": 1, "TargetArgu4": 2}
    for sid, template in WEAPON_TRIGGER_SPELLS.items():
        spell = spells[sid]
        require(spell.SpellTempletId == template and spell.SpellType == 1 and
                spell.SpellTypeTag == 4 and not spell.DriveByAnimation,
                "Weapon trigger spell drift")
        require(any(t.Spell == sid for t in message.Unit.TriggerInfos),
                "Weapon trigger spell has no trigger")
        previous = type(spell)()
        previous.CopyFrom(spell)
        spell.SpellType = 4
        previous.SpellType = 4
        require(spell == previous, "Unrelated weapon trigger field changed")
        patches["spellInfoPatches"].append({"ID": sid, "set": {"SpellType": 4}})
    for servant, outer_id in SUMMONS.items():
        outer = spells[outer_id]
        agent = agents[effects[outer.SpellEffectArgu].Argument1]
        inner = spells[agent.SpellCastSpawn]
        require((agent.ID, inner.ID) == (90610000 + servant, 90510000 + servant), "Summon chain drift")
        for spell in (outer, inner):
            require(spell.TargetTypeTrue1 == 2 and spell.TargetTypeNominal == 2 and spell.TargetArgu4 == 3,
                    "Unexpected current summon targeting")
            for key, value in enemy_target.items():
                setattr(spell, key, value)
            patches["spellInfoPatches"].append({"ID": spell.ID, "set": enemy_target.copy()})
        require(agent.TargetType == 1 and agent.TargetArgu4 == 3, "Agent target drift")
        agent.TargetArgu4 = 2
        patches["agentInfoPatches"].append({"ID": agent.ID, "set": {"TargetArgu4": 2}})
        matched = [s for s in message.SvCombatInfo if s.SvCardID == 10000001 + servant * 100]
        require(matched and all(s.ActiveSpellID == outer_id for s in matched), "Servant active spell drift")
        for entry in matched:
            entry.SpaNeedCurTarget = True
        patches["servantCombatPatches"].append({"SvCardID": matched[0].SvCardID,
                                               "ActiveSpellID": outer_id,
                                               "set": {"SpaNeedCurTarget": True}})
    # Protobuf round trip validates serialization and preserves fields/unknown data.
    encoded = message.SerializeToString(deterministic=True)
    reread = type(message)()
    reread.ParseFromString(encoded)
    require(reread == message, "Candidate protobuf failed round trip")
    require(message.Unit.TriggerInfos == original.Unit.TriggerInfos, "Weapon trigger lifecycle changed")
    for current, previous in zip(message.SvCombatInfo, original.SvCombatInfo):
        require(current.RoleNormalAtkIDs == previous.RoleNormalAtkIDs and
                current.RoleDashAtkID == previous.RoleDashAtkID and current.SvCtrl == previous.SvCtrl,
                "Attack animation/normal chain changed")
    return encoded, patches


def build(output=None):
    evidence = native_evidence()
    spell_raw = read_current_spell()
    environment, obj, tree, root = load_spell_bundle(spell_raw)
    changed_templates = repair_xml(root)
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    tree["bytes"] = list(bytes(x ^ 255 for x in payload) if tree.get("isEncrypt") else payload)
    obj.save_typetree(tree)
    candidate_bundle = environment.file.save(packer="original")
    _, _, _, reread = load_spell_bundle(candidate_bundle)
    require(ET.tostring(root) == ET.tostring(reread), "Candidate AssetBundle failed round trip")
    responses = json.loads(SEED.read_text(encoding="utf-8-sig"))
    role_raw = base64.b64decode(responses["/combat/role/info"]["base64"], validate=True)
    cls = role_class()
    message = cls()
    message.ParseFromString(role_raw)
    role_candidate, patches = repair_role(message)
    specification = {"schema": 1, "name": "signed151-weapon-slots-fixed-target-candidate",
                     "candidateOnly": True, "requiresCoupledResourceAndProtocolUpdate": True,
                     "legacyNormalCoefficientsPreserved": True,
                     "baselineRelease": BASE_SEQUENCE, "baselineSpellSha256": sha(spell_raw),
                     "baselineRoleSha256": sha(role_raw), "candidateSpellSha256": sha(candidate_bundle),
                     "candidateRoleSha256": sha(role_candidate), "changedTemplates": changed_templates,
                     "argumentMapping": {"20": 25, "21": 26, "22": 27},
                     "emptySoundSlot": 28,
                     "weaponTriggerSpellType": 4, **patches,
                     "limits": ["保留当前离线伤害数值；不等于恢复原服EffectArgs",
                                "不屏蔽同武器自切；仅修三条武器被动SpellType，不改触发条件/频率/归属者",
                                "不改110/120混合范围、119随机持续、112持续线圈",
                                "原生证据确认COMMON/ACTIVE被动会抢currentSkill；未做设备战斗验收",
                                "原版刻印完整SkillInfo/EffectArgs/Trigger仍缺，本次不恢复85%或190%系数"]}
    if output:
        output = Path(output).resolve()
        forbidden = (PROJECT / "legacy-server/resources", HOT_ROOT, PROJECT / "构建")
        require(not any(output == p.resolve() or p.resolve() in output.parents for p in forbidden),
                "Output must not overwrite production resources or signed releases")
        output.mkdir(parents=True, exist_ok=True)
        (output / "spells.ab").write_bytes(candidate_bundle)
        (output / "role-combat-candidate.pb").write_bytes(role_candidate)
        (output / "combat-weapon-patch.json").write_text(json.dumps(specification, ensure_ascii=False, indent=2) + "\n",
                                                       encoding="utf-8")
        require(sha((output / "spells.ab").read_bytes()) == sha(candidate_bundle), "Written bundle mismatch")
        require(sha((output / "role-combat-candidate.pb").read_bytes()) == sha(role_candidate), "Written role mismatch")
        require(json.loads((output / "combat-weapon-patch.json").read_text(encoding="utf-8")) == specification,
                "Written specification mismatch")
        (output / "weapon-trigger-native-evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        require(json.loads((output / "weapon-trigger-native-evidence.json").read_text(encoding="utf-8")) == evidence,
                "Written native evidence mismatch")
    return specification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="独立候选目录；省略时仅内存验证，不写文件")
    arguments = parser.parse_args()
    result = build(arguments.output)
    print("COMBAT_WEAPON_CANDIDATE_OK " + json.dumps({"changedTemplates": len(result["changedTemplates"]),
                                                     "effectArgumentPatches": len(result["effectArgumentPatches"]),
                                                     "spellInfoPatches": len(result["spellInfoPatches"]),
                                                     "candidateSpellSha256": result["candidateSpellSha256"],
                                                     "candidateRoleSha256": result["candidateRoleSha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
