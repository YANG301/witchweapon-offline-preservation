"""Build an isolated signed157 combat-effect candidate; never publish or deploy.

Description-derived coefficients are distinguished from local timing choices.
The original server EffectArgumentInfo is still unavailable for these skills.
"""
from __future__ import annotations

import argparse
import base64
import copy
from collections import Counter
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.dont_write_bytecode = True
import build_combat_weapon_repair as common

PROJECT = Path(r"D:\Project\魔女兵器在线版")
DEFAULT_SEED = PROJECT / "验收/战斗全面核查/候选/offline_responses.json"
DEFAULT_OUT = PROJECT / "验收/战斗效果修复/候选"
SEQUENCE = "157-19113cb6aca17494d33d726e524f4fc01198df2aac5392c4dbe4b24a250d6f32"
SEED_HASH = "eccf65bebf75270fab64ceee2f79c698f7b8f0bb7aa22c7cbcba8de8baea881a"
SPELL_HASH = "6d804f65a58cad309572a857e86671e89506dc5273c174cc1827e057a1bf87a8"
OFFICIAL_XML = PROJECT / "参考资料/战斗数据核查/关服前热更配置/spells.xml"
AUDIT = PROJECT / "验收/战斗全面核查/全部武器协议与模板对照.json"
PURE_WEAPONS = (1701020101, 1701030101, 1701030102)
ACTIVE_UNITS = (110, 118)


def one(rows, predicate, label):
    matches = [row for row in rows if predicate(row)]
    common.require(len(matches) == 1, f"Expected one {label}; found {len(matches)}")
    return matches[0]


def replace_template(root, name, source):
    old = one(root, lambda x: x.get("TempletID") == name, name)
    index = list(root).index(old)
    result = copy.deepcopy(source)
    result.set("TempletID", name)
    root.remove(old)
    root.insert(index, result)
    return result


def sharp_patch(role, attack, recovery):
    common.require(0 < attack <= 10000 and 0 <= recovery <= 10000,
                   "Sharp calibration must fit the 10000-point scale")
    changes = []
    for sv in role.SvCombatInfo:
        original = {f.name: getattr(sv.WeaponSharpInfo, f.name)
                    for f in sv.WeaponSharpInfo.DESCRIPTOR.fields}
        sv.WeaponSharpInfo.SharpMax = 10000
        sv.WeaponSharpInfo.SharpRecovery = recovery
        sv.WeaponSharpInfo.SharpReduceAttack = attack
        sv.WeaponSharpInfo.SharpReduceSecond = 0
        sv.WeaponSharpInfo.SharpReduceHit = 0
        sv.WeaponSharpInfo.SharpConsumeIn = 0
        changes.append({"weaponID": sv.SvWeaponCardID, "before": original,
                        "after": {f.name: getattr(sv.WeaponSharpInfo, f.name)
                                  for f in sv.WeaponSharpInfo.DESCRIPTOR.fields}})
    return {"classification": "本地可校准；原版客户端Sharp列全部空，非原服实参",
            "attackEventPercent": attack / 100, "sheathedRecoveryPercentPerSecond": recovery / 100,
            "rankPolicy": "未发现原Rank消耗倍率，不按晋升虚构消耗；保持10000归一化",
            "native": {"OnStart": "0x3B7E858", "AttackChangeSharp": "0x3B80D1C",
                       "UpdateSharp": "0x3B8021C"}, "weapons": changes}


def pure_base_patch(role, root):
    changes = []
    for wid in PURE_WEAPONS:
        sv = one(role.SvCombatInfo, lambda s: s.SvWeaponCardID == wid, str(wid))
        ids = sorted(set([sv.RoleDashAtkID, *sv.RoleNormalAtkIDs]))
        spells = [one(role.Unit.SpellInfos, lambda s: s.ID == sid, str(sid)) for sid in ids]
        names = set(s.SpellTempletId for s in spells)
        common.require(len(names) == 1, "Normal and dash unexpectedly use different templates")
        name = next(iter(names))
        graph = one(root, lambda n: n.get("TempletID") == name, name)
        encoded = ET.tostring(graph, encoding="unicode")
        common.require(not re.search(r"@ARGUMENT(?:25|26|27|28)(?!\d)", encoded),
                       f"New base slots already used by {name}")
        packs = [n for n in graph.iter("CreateDamagePack")
                 if n.get("DamageTag") == "248" and n.get("DamageType") == "1"]
        common.require(len(packs) == 5, f"Expected five original normal packs: {name}")
        old_pure = [dict(n.attrib) for n in graph.iter("CreateDamagePack")
                    if n.get("DamageType") == "4"]
        for pack in packs:
            common.require(pack.get("SPPDmgP") == "@ARGUMENT4" and
                           pack.get("SPPAP") == "@ARGUMENT5", "Unexpected normal ratio fields")
            pack.set("SPPDmgP", "@ARGUMENT25")
            pack.set("SPPAP", "@ARGUMENT26")
            pack.set("SPPAV", "{@ARGUMENT27 + @ARGUMENT28 * @SKILL_LEVEL}")
        argument_changes = []
        for spell in spells:
            arg = one(role.Unit.EffectArgumentInfos,
                      lambda a: a.ID == spell.SpellEffectArgu, str(spell.SpellEffectArgu))
            original = {str(i): getattr(arg, f"Argument{i}") for i in (4, 5, 6, 7)}
            for slot, value in {25: 10000, 26: 4100, 27: 0, 28: 0}.items():
                common.require(getattr(arg, f"Argument{slot}") == 0, "Candidate slot is not empty")
                setattr(arg, f"Argument{slot}", value)
            common.require(original == {str(i): getattr(arg, f"Argument{i}") for i in (4, 5, 6, 7)},
                           "Legacy pure coefficients changed")
            argument_changes.append({"spellID": spell.ID, "effectArgID": arg.ID,
                                     "legacyPureSlotsPreserved": original,
                                     "baseSlots": {"25": 10000, "26": 4100, "27": 0, "28": 0}})
        # The shipped offline fixture has no recovered sound ids. LinkString
        # concatenates 99 + 0, causing a native miss-sound log on every hit.
        # Suppress only the proved empty placeholders in these three graphs.
        for spell in spells:
            arg = one(role.Unit.EffectArgumentInfos,
                      lambda a: a.ID == spell.SpellEffectArgu, str(spell.ID))
            common.require(all(getattr(arg, f"Argument{i}") == 0 for i in range(9, 17)),
                           "Unexpected nonempty sound ids; preserve them")
        empty_sounds = {n.get("Variable") for n in graph.iter("LinkString")
                        if n.get("String1") == "99" and
                        re.fullmatch(r"@ARGUMENT(?:9|1[0-6])", n.get("String2", ""))}
        muted = 0
        for parent in graph.iter():
            for node in list(parent):
                if node.tag == "PlaySound" and node.get("SoundName", "").lstrip("$") in empty_sounds:
                    parent.remove(node)
                    muted += 1
            if parent.tag == "CreateDamagePack" and parent.get("HitSound", "").lstrip("$") in empty_sounds:
                del parent.attrib["HitSound"]
                muted += 1
        common.require(old_pure == [dict(n.attrib) for n in graph.iter("CreateDamagePack")
                                   if n.get("DamageType") == "4"], "Pure mechanism changed")
        changes.append({"weaponID": wid, "template": name, "basePackCount": len(packs),
                        "classification": "按2020武器普攻描述恢复41%物攻；新旧客户端参数兼容分槽",
                        "arguments": argument_changes,
                        "soundPlaceholderCallsRemoved": muted,
                        "remaining": "原作者纯伤仅拼在第一阶段；告死天使尚缺暴击门禁。此步不伪称已还原附伤频率/刻印Rank系数"})
    return changes


def active_patch(role, root, official):
    # Exact damage/count/radius comes from the shipped Chinese descriptions.
    # Missing original event offsets, rectangle size and knockback are local.
    values = {
        110: {4: 400, 5: 400, 6: 7, 7: 3000, 8: 10000, 9: 19000,
              10: 4, 11: 36, 12: 3400, 13: 300, 14: 10000, 15: 28000,
              16: 4, 17: 32},
        118: {4: 10000, 5: 9000, 6: -3, 7: 30, 8: 8, 9: 250,
              10: 300, 11: 800, 12: 600, 13: 50},
    }
    results = []
    for unit in ACTIVE_UNITS:
        inner = one(role.Unit.SpellInfos, lambda s: s.ID == 90510000 + unit, str(unit))
        outer = one(role.Unit.SpellInfos,
                    lambda s: s.SpellTempletId == f"Offline_Roster{unit}_Summon", str(unit))
        agent = one(role.Unit.AgentInfos, lambda a: a.ID == 90610000 + unit, str(unit))
        official_inner = one(official, lambda n: n.get("TempletID") == f"Servant{unit}_ActiveSkill_01", str(unit))
        official_outer = one(official, lambda n: n.get("TempletID") == f"Servant{unit}_ActiveSkill", str(unit))
        new_inner = replace_template(root, inner.SpellTempletId, official_inner)
        replace_template(root, outer.SpellTempletId, official_outer)
        arg = one(role.Unit.EffectArgumentInfos, lambda a: a.ID == inner.SpellEffectArgu, str(inner.ID))
        arg.Clear()
        arg.ID = inner.SpellEffectArgu
        for slot, value in values[unit].items():
            setattr(arg, f"Argument{slot}", value)
        inner.ChannelTime = 6200 if unit == 110 else 2600
        agent.LifeTime = 6800 if unit == 110 else 3200
        agent.TargetType = 1
        agent.TargetArgu4 = 2 if unit == 110 else 3
        for spell in (inner, outer):
            spell.TargetArgu4 = 2 if unit == 110 else 3
            spell.TargetTypeTrue = 1
            spell.TargetTypeTrue1 = 1 if unit == 110 else 2
            spell.TargetTypeNominal = 1 if unit == 110 else 2
        results.append({"unit": unit, "activeSpellID": outer.ID, "innerSpellID": inner.ID,
                        "agentID": agent.ID, "templates": [outer.SpellTempletId, inner.SpellTempletId],
                        "originalTemplates": [official_outer.get("TempletID"), official_inner.get("TempletID")],
                        "classification": "原模板结构与动态表现；参数按2020描述重建，非原服EffectArgs",
                        "restored": ("7段190%总物攻+(4+36*等级)，最后目标3米内280%总物攻+(4+32*等级)；原绕目标位移与苍蓝守护者表现"
                                     if unit == 110 else "8段90%总魔攻+(-3+30*等级)；原矩形范围、每段击退与离场表现"),
                        "calibration": ({"firstHitMs": 400, "hitIntervalMs": 400, "finisherStartMs": 3400}
                                        if unit == 110 else {"firstHitMs": 300, "hitIntervalMs": 250,
                                                            "rectangleLengthCm": 800, "rectangleWidthCm": 600,
                                                            "knockbackCmPerHit": 50}),
                        "args": {str(k): v for k, v in values[unit].items()},
                        "levelSource": "正文SPDesc(type01)使用Servant Level；服务端需沿原技能等级helper设置内外Spell/Agent.Level",
                        "expectedDamagePacksPerCast": 8,
                        "originalGraphSha256": common.sha(ET.tostring(official_inner)),
                        "candidateGraphSha256": common.sha(ET.tostring(new_inner))})
    return results


def validate(before_role, role, before_root, root, changes):
    # No unknown templates, duplicate protocol ids or out-of-range argument slots.
    names = [n.get("TempletID") for n in root]
    common.require(Counter(names) == Counter(n.get("TempletID") for n in before_root),
                   "XML template inventory/duplicate multiplicity changed")
    for field in role.Unit.DESCRIPTOR.fields:
        rows = getattr(role.Unit, field.name)
        ids = [row.ID for row in rows]
        common.require(len(ids) == len(set(ids)), f"Duplicate {field.name} IDs")
    for spell in role.Unit.SpellInfos:
        common.require(spell.SpellTempletId in names, f"Missing template: {spell.SpellTempletId}")
    changed_names = {x["template"] for x in changes["pureBase"]}
    changed_names.update(n for x in changes["actives"] for n in x["templates"])
    old = {n.get("TempletID"): ET.tostring(n) for n in before_root}
    new = {n.get("TempletID"): ET.tostring(n) for n in root}
    common.require(set(old) == set(new), "Template inventory changed")
    actual = {k for k in old if old[k] != new[k]}
    common.require(actual == changed_names, f"Unexpected XML scope: {actual ^ changed_names}")
    # Verify all role/unit mutations by removing precisely authorized fields.
    normalized = copy.deepcopy(role)
    for i, sv in enumerate(normalized.SvCombatInfo):
        sv.WeaponSharpInfo.CopyFrom(before_role.SvCombatInfo[i].WeaponSharpInfo)
    affected_spells = {sid for x in changes["actives"] for sid in (x["activeSpellID"], x["innerSpellID"])}
    affected_agents = {x["agentID"] for x in changes["actives"]}
    affected_args = {x["innerSpellID"] for x in changes["actives"]}
    affected_args.update(x["effectArgID"] for p in changes["pureBase"] for x in p["arguments"])
    for field, ids in (("SpellInfos", affected_spells), ("AgentInfos", affected_agents),
                       ("EffectArgumentInfos", affected_args)):
        previous = {x.ID: x for x in getattr(before_role.Unit, field)}
        for item in getattr(normalized.Unit, field):
            if item.ID in ids:
                item.CopyFrom(previous[item.ID])
    common.require(normalized.SerializeToString() == before_role.SerializeToString(),
                   "Unexpected role mutation outside authorized paths")
    # Mathematical checks distinguish seven single-target hits from the finisher.
    common.require(19000 * 7 + 28000 == 161000, "110 total ratio")
    common.require(9000 * 8 == 72000, "118 total ratio")
    common.require(10000 * 4100 / 100000000 == 0.41, "41% normal damage")
    return {"templateScope": sorted(actual), "templateCount": len(names),
            "roleScopeVerified": True, "protocolIDsUnique": True,
            "normalRatio": 0.41, "110TotalPercent": 1610, "118TotalPercent": 720,
            "deviceTest": "未执行；由root负责实际战斗验证"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--attack-consume", type=int, default=200)
    parser.add_argument("--sheathed-recovery", type=int, default=500)
    args = parser.parse_args()
    seed_bytes = args.seed.read_bytes()
    common.require(common.sha(seed_bytes) == SEED_HASH, "Unexpected signed157 role fixture baseline")
    hot = common.HOT_ROOT
    sequence = (hot / "current").read_text(encoding="utf-8-sig").strip()
    common.require(sequence == SEQUENCE, "Unexpected current hot-update release")
    manifest = json.loads((hot / "releases" / sequence / "manifest.json").read_text(encoding="utf-8-sig"))
    asset = one(manifest["assets"], lambda a: a["path"] == common.SPELL_PATH, "spells asset")
    raw = (hot / "blobs" / asset["sha256"]).read_bytes()
    common.require(common.sha(raw) == SPELL_HASH, "Unexpected signed157 spells baseline")
    seed = json.loads(seed_bytes.decode("utf-8-sig"))
    role = common.role_class()()
    role.ParseFromString(base64.b64decode(seed["/combat/role/info"]["base64"]))
    before_role = copy.deepcopy(role)
    environment, obj, tree, root = common.load_spell_bundle(raw)
    before_root = copy.deepcopy(root)
    official = ET.parse(OFFICIAL_XML).getroot()
    changes = {"sharp": sharp_patch(role, args.attack_consume, args.sheathed_recovery),
               "pureBase": pure_base_patch(role, root),
               "actives": active_patch(role, root, official)}
    checks = validate(before_role, role, before_root, root, changes)
    pb = role.SerializeToString()
    roundtrip = type(role)()
    roundtrip.ParseFromString(pb)
    common.require(roundtrip == role, "Protobuf serialization roundtrip")
    seed["/combat/role/info"]["base64"] = base64.b64encode(pb).decode("ascii")
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    tree["bytes"] = list(bytes(b ^ 255 for b in xml) if tree.get("isEncrypt") else xml)
    obj.save_typetree(tree)
    bundle = environment.file.save(packer="original")
    _, _, _, decoded = common.load_spell_bundle(bundle)
    common.require(ET.tostring(decoded) == ET.tostring(root), "AssetBundle XML roundtrip")
    audit = json.loads(AUDIT.read_text(encoding="utf-8-sig"))
    remaining = {}
    for weapon in audit["weapons"]:
        unit = weapon["servantUnit"]
        if unit in (100, 101, 102, 103, 112) or unit in ACTIVE_UNITS:
            continue
        remaining[str(unit)] = {"unit": unit, "activeSpellID": int(weapon["officialActive"]["row"]["ID"]),
                                "description": weapon["officialActive"]["translatedText"]["spell_desc_floor"],
                                "status": "仍是作者本地简化模板；逐技能恢复，未用本轮两个技能替代"}
    args.output.mkdir(parents=True, exist_ok=True)
    artifacts = {"offline_responses.json": json.dumps(seed, ensure_ascii=False, indent=2).encode("utf-8"),
                 "role-info.pb": pb, "spells.ab": bundle, "Spells.xml": xml,
                 "逐技能剩余边界.json": json.dumps(remaining, ensure_ascii=False, indent=2).encode("utf-8")}
    report = {"schema": 1, "baseline": {"release": sequence, "seed": str(args.seed),
                                           "seedSha256": SEED_HASH, "spellsSha256": SPELL_HASH},
              "sources": {"officialXml": str(OFFICIAL_XML), "descriptionAudit": str(AUDIT)},
              "changes": changes, "checks": checks,
              "artifacts": {name: {"path": str(args.output / name), "size": len(data),
                                   "sha256": common.sha(data)} for name, data in artifacts.items()}}
    for name, data in artifacts.items():
        (args.output / name).write_bytes(data)
    (args.output / "候选说明.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "artifacts": report["artifacts"], "checks": checks}, ensure_ascii=False))


if __name__ == "__main__":
    main()
