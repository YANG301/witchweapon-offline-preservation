"""从原始编辑器表构建敌人Basket，并明确记录技能兼容替换。

build_basket(stat_ids) -> (protobuf_bytes, provenance_dict)
纯生成器，不写resources、不启动服务。原始基础属性/位阶成长与兼容AI分开标注。
"""
from __future__ import annotations

import base64
import copy
import csv
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

from generate_stage_catalog import ASSETS, CONFIG, DESCRIPTORS, PROJECT, basket_class

AUDIT = PROJECT.parent / "参考资料/战斗数据核查"
TABLE_DIR = AUDIT / "2019编辑器战斗表/1.1.70"
GUIDE_DIR = AUDIT / "原始关卡/国服1.1.70/GuideSData"
COMPATIBILITY_RESPONSES = PROJECT / "resources/offline_responses.json"
MOTION_XML = CONFIG.parent / "xmlconf/motion.xml"
_GROUPS = ("SpellInfos", "BuffInfos", "AgentInfos", "TriggerInfos",
           "MobInfos", "MobTypeInfos", "EffectArgumentInfos", "BehaviorTreeArgumentInfos")
_GUIDE_GROUPS = {"Spells": "SpellInfos", "Buffs": "BuffInfos", "Agents": "AgentInfos",
                 "Triggers": "TriggerInfos", "EffectArg": "EffectArgumentInfos"}
_ALIASES = {"Lv": "Level", "SpellCD": "SpellD"}
_BASIC = ("Hp", "PhysicalAttack", "MagicalAttack", "PhysicalDefense", "MagicalDefense")


class ParameterError(ValueError):
    """输入或依赖资料不足，不能可靠生成敌人。"""


def _table(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = [r for r in csv.DictReader(stream) if (r.get("ID") or "").isdigit()]
    result = {int(r["ID"]): r for r in rows}
    if len(result) != len(rows):
        raise ParameterError("原表ID重复：" + str(path))
    return result


def _integer(value):
    return int(value or 0)


def _f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def parse_stat_id(value):
    """严格保留原statID的mobID、rank、level，不猜缺失值。"""
    match = re.fullmatch(r"([1-9]\d*)-([123])-([1-9]\d*)", str(value))
    if not match:
        raise ParameterError("非法statID：" + str(value))
    return tuple(map(int, match.groups()))


def _dependencies(group, msg):
    """显式协议引用，以及Effect/行为树前几个长整数参数中的对象ID。"""
    mapping = {}
    if group == "SpellInfos":
        mapping = {"SpellEffectArgu": "EffectArgumentInfos"}
        mapping.update({f"SpellBuff{i}": "BuffInfos" for i in range(1, 4)})
        mapping.update({f"SpellAgent{i}": "AgentInfos" for i in range(1, 3)})
        mapping.update({f"SpellSpell{i}": "SpellInfos" for i in range(1, 6)})
        mapping.update({f"LinkSpell{i}": "SpellInfos" for i in range(1, 11)})
        mapping.update({f"SpellSummon{i}": "MobInfos" for i in range(1, 3)})
    elif group == "BuffInfos":
        mapping = {"BuffEffectArgu": "EffectArgumentInfos"}
        mapping.update({f"AttachedBuff{i}": "BuffInfos" for i in range(1, 4)})
        mapping.update({f"BuffTrigger{i}": "TriggerInfos" for i in range(1, 4)})
        mapping.update({"BuffTrigger" + n: "TriggerInfos" for n in ("Tick", "Interrupt", "Sublayer", "End")})
    elif group == "AgentInfos":
        mapping = {f"BuffId{i}": "BuffInfos" for i in range(1, 3)}
        mapping.update({"SpellCast" + n: "SpellInfos" for n in ("Spawn", "Hit", "Dead")})
        # MotionArgu也是外置执行参数。
        mapping["MotionArgu"] = "EffectArgumentInfos"
    elif group == "TriggerInfos":
        mapping = {"Spell": "SpellInfos"}
    elif group == "MobTypeInfos":
        mapping = {"BehaviorTreeId": "BehaviorTreeArgumentInfos"}
        mapping.update({f"MobSpell{i}": "SpellInfos" for i in range(1, 11)})
        mapping.update({f"BuffId{i}": "BuffInfos" for i in range(1, 3)})
        mapping.update({f"Trigger{i}": "TriggerInfos" for i in range(1, 6)})
    elif group == "MobInfos":
        mapping = {"MobTypeInfo" + rank: "MobTypeInfos" for rank in ("Normal", "Elite", "Boss")}
        mapping.update({f"SummonMob{i}": "MobInfos" for i in range(1, 4)})
        for field, target in (("SpawnBuffs", "BuffInfos"), ("SpawnTriggers", "TriggerInfos")):
            for value in getattr(msg, field):
                if value:
                    yield target, value
    for field, target in mapping.items():
        value = getattr(msg, field)
        if value:
            yield target, value
    if group in ("EffectArgumentInfos", "BehaviorTreeArgumentInfos"):
        last = 3 if group == "EffectArgumentInfos" else 10
        first = 1 if group == "EffectArgumentInfos" else 0
        for i in range(first, last + 1):
            value = getattr(msg, f"Argument{i}")
            # 此范围是对象ID空间；小整数仍是模板中的常量/枚举。
            if value >= 10_000_000:
                yield "object", value


def _motion_templates(path):
    """读取当前客户端发射器及其bullet模板，不用旧MovementType猜MotionId。"""
    emit_ids, complete = set(), set()
    for node in ET.parse(path).iter("emit"):
        ident = node.get("id")
        if not ident or ident in emit_ids:
            raise ParameterError("客户端发射器ID为空/重复：" + str(path))
        emit_ids.add(ident)
        if node.find("bullet") is not None:
            complete.add(ident)
    return frozenset(complete)


def _validate_agent_motion(message, templates):
    # 2020原生SaveAgent直接保存MotionId（0x12d0adc），CreateMotion用它
    # 拼缓存键（0x16a0b80）。SaveEmit经GetID取第一个'-'前的字符串，
    # 在Config/xmlConf/motion.xml查//emit[@id="..."]，再读取同节点bullet。
    # 旧教程只有MovementType，空MotionId会查不到emit并留下空Emit对象。
    if not message.MotionId:
        raise ParameterError(f"AgentInfos/{message.ID}缺客户端MotionId；旧MovementType不能替代当前发射器ID")
    if "-" in message.MotionId or message.MotionId not in templates:
        raise ParameterError(f"AgentInfos/{message.ID}缺客户端emit/bullet模板：{message.MotionId}")


def validate_basket(basket, *, motion_templates=None):
    """核查协议闭包及当前客户端投射物XML依赖，二者均需成立。"""
    ids = {}
    for group in _GROUPS:
        messages = getattr(basket, group)
        keys = [(m.ID, m.CurType, m.Level) if group == "MobInfos" else m.ID for m in messages]
        if len(set(keys)) != len(keys):
            raise ParameterError("输出重复对象：" + group)
        ids[group] = {m.ID for m in messages}
    for group in _GROUPS:
        for msg in getattr(basket, group):
            for target, value in _dependencies(group, msg):
                present = any(value in ids[g] for g in _GROUPS) if target == "object" else value in ids[target]
                if not present:
                    raise ParameterError(f"悬空引用：{group}/{msg.ID} -> {target}/{value}")
    if any(not t.Name for t in basket.BehaviorTreeArgumentInfos):
        raise ParameterError("行为树name为空")
    if basket.AgentInfos:
        templates = _motion_templates(MOTION_XML) if motion_templates is None else motion_templates
        for agent in basket.AgentInfos:
            _validate_agent_motion(agent, templates)


class EnemyParameterBuilder:
    """一次读取原资料，可重复为不同关卡生成互不共享可变状态的Basket。"""

    def __init__(self, table_dir=TABLE_DIR, descriptors=DESCRIPTORS, guide_dir=GUIDE_DIR,
                 compatibility_responses=COMPATIBILITY_RESPONSES, config=CONFIG, assets=ASSETS):
        self.cls = basket_class(Path(descriptors))
        self.mob = _table(Path(table_dir) / "Mob.csv")
        self.types = _table(Path(table_dir) / "MobType.csv")
        self.levels = _table(Path(table_dir) / "MobLevelInfo.csv")
        self.assets = Path(assets)
        self.catalog = {g: {} for g in _GROUPS}
        self.sources = {}
        self.rejected = {}
        self.source_warnings = []
        inputs = [Path(table_dir) / n for n in ("Mob.csv", "MobType.csv", "MobLevelInfo.csv")]
        inputs += [Path(descriptors), Path(compatibility_responses), Path(config) / "behaviortreeargument.txt", Path(config) / "effect.txt"]
        self.effect_paths = {}
        # 当前effect表有重复ID且对应不同资源；不能靠覆盖顺序猜映射。
        with (Path(config) / "effect.txt").open(encoding="utf-8-sig", newline="") as stream:
            effect_rows = [r for r in csv.DictReader(stream) if (r.get("ID") or "").isdigit()]
        effect_ids, duplicate_effect_ids = set(), set()
        for row in effect_rows:
            ident = int(row["ID"])
            if ident in effect_ids:
                duplicate_effect_ids.add(ident)
            effect_ids.add(ident)
        if duplicate_effect_ids:
            self.source_warnings.append({"kind": "ambiguous-client-effect-id", "ids": sorted(duplicate_effect_ids), "policy": "排除这些ID的资源路径转换"})
        for row in effect_rows:
            ident = int(row["ID"])
            if ident in duplicate_effect_ids:
                continue
            for field in ("effect_name1", "effect_name2"):
                if row.get(field):
                    self.effect_paths.setdefault(row[field], set()).add(ident)
        # XML模板名称属于当前客户端，不能用旧响应里不存在的模板。
        spells_xml = Path(config).parent / "xmlconf/skill/spells.xml"
        buffs_xml = Path(config).parent / "xmlconf/buff/buffs.xml"
        motion_xml = Path(config).parent / "xmlconf/motion.xml"
        inputs += [spells_xml, buffs_xml, motion_xml]
        self.motion_templates = _motion_templates(motion_xml)
        self.templates = {"SpellInfos": {n.get("TempletID") for n in ET.parse(spells_xml).iter() if n.get("TempletID")},
                          "BuffInfos": {n.get("TempletID") for n in ET.parse(buffs_xml).iter() if n.get("TempletID")}}
        # 教程Lv是样本技能等级，保持原样；不把敌人等级猜成技能等级。
        for path in sorted(Path(guide_dir).glob("battle_*_MyMonsterInfo.json")):
            inputs.append(path)
            doc = json.loads(path.read_text(encoding="utf-8"))
            timestamp = doc["Content"].get("Timestamp", "")
            content = json.loads(doc["Content"]["Content"])
            for old, group in _GUIDE_GROUPS.items():
                for row in content.get(old, []):
                    ident = _integer(row.get("ID"))
                    try:
                        message = self._convert(group, row)
                    except ParameterError as exc:
                        self.rejected.setdefault((group, ident), []).append(str(exc))
                        continue
                    self.catalog[group][ident] = message
                    self.sources[(group, ident)] = {"kind": "original-guide-response-sample", "path": str(path),
                        "timestamp": timestamp, "sampleLevel": row.get("Lv"), "levelScaling": "未推导额外技能等级成长"}
        for ident, row in _table(Path(config) / "behaviortreeargument.txt").items():
            if not row.get("name") or not (self.assets / "resources-/behavior/ext" / (row["name"] + ".asset")).is_file():
                continue
            message = self.cls().BehaviorTreeArgumentInfos.add()
            message.ID, message.Name = ident, row["name"]
            for i in range(31):
                setattr(message, f"Argument{i}", _integer(row.get(f"argument{i}")))
            self.catalog["BehaviorTreeArgumentInfos"][ident] = message
            self.sources[("BehaviorTreeArgumentInfos", ident)] = {"kind": "original-client-behavior-arguments", "path": str(Path(config) / "behaviortreeargument.txt")}
        responses = json.loads(Path(compatibility_responses).read_text(encoding="utf-8"))
        compat = self.cls.FromString(base64.b64decode(responses["/combat/mob/info"]["base64"]))
        validate_basket(compat, motion_templates=self.motion_templates)
        self.compat_spell = next((m for m in compat.SpellInfos if m.SpellTempletId == "Mob_NormalAttack_Melee_Physical"), None)
        self.compat_tree = next((m for m in compat.BehaviorTreeArgumentInfos if m.Name == "normal_attack" and self.compat_spell and m.Argument0 == self.compat_spell.ID), None)
        if self.compat_spell is None or self.compat_tree is None:
            raise ParameterError("兼容模板缺闭合普通攻击/normal_attack树")
        for group in _GROUPS:
            if group in ("MobInfos", "MobTypeInfos"):
                continue
            for message in getattr(compat, group):
                if message.ID not in self.catalog[group]:
                    self.catalog[group][message.ID] = message
                    self.sources[(group, message.ID)] = {"kind": "local-compatible-template", "path": str(compatibility_responses)}
        # 原表中有仅魔攻的敌人；物理普攻不能冒充其伤害。两种原版XML
        # 模板的4/5/6/7参数用途对应，转换只作为有记录的本地兼容策略。
        magical_name = "Mob_NormalAttack_Melee_Magical"
        if magical_name not in self.templates["SpellInfos"]:
            raise ParameterError("当前客户端缺魔法兼容普攻模板")
        self.compat_magical = type(self.compat_spell)()
        self.compat_magical.CopyFrom(self.compat_spell)
        self.compat_magical.ID = 8_800_000_000_000_001
        self.compat_magical.SpellTempletId = magical_name
        self.catalog["SpellInfos"][self.compat_magical.ID] = self.compat_magical
        self.sources[("SpellInfos", self.compat_magical.ID)] = {
            "kind": "local-compatible-magical-normal-attack", "templateSpellID": self.compat_spell.ID,
            "spellTemplate": magical_name, "reason": "保持原敌人的魔攻属性，避免缺技能时改用零物攻伤害"}
        self.input_evidence = [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()} for p in inputs]

    def _convert(self, group, row):
        message = getattr(self.cls(), group).add()
        fields = message.DESCRIPTOR.fields_by_name
        for original, value in row.items():
            field = _ALIASES.get(original, original)
            if field not in fields:
                if value not in (0, "", None):
                    raise ParameterError("旧响应有未映射非零字段：" + original)
                continue
            desc = fields[field]
            if desc.type == desc.TYPE_STRING:
                setattr(message, field, str(value or ""))
            else:
                if isinstance(value, str) and value and not re.fullmatch(r"-?\d+", value):
                    candidates = self.effect_paths.get(value, set())
                    if field not in ("HitEffects", "BuffPrefabAdd", "BuffPrefabLoop", "BuffPrefabTick", "BuffPrefabEnd") or len(candidates) != 1:
                        raise ParameterError("旧资源路径无法唯一映射当前effectID：" + field)
                    value = next(iter(candidates))
                try:
                    setattr(message, field, _integer(value))
                except (ValueError, TypeError) as exc:
                    raise ParameterError("旧字段类型不兼容：" + field) from exc
        template_field = "SpellTempletId" if group == "SpellInfos" else "BuffTempletId"
        if group in self.templates and getattr(message, template_field) and getattr(message, template_field) not in self.templates[group]:
            raise ParameterError("当前客户端缺技能/Buff模板：" + getattr(message, template_field))
        return message

    def _closure(self, group, ident, visiting=None):
        key = group, ident
        visiting = set() if visiting is None else visiting
        if key in visiting:
            return {}
        if group == "object":
            found = [g for g in _GROUPS if ident in self.catalog[g]]
            if len(found) != 1:
                raise ParameterError("执行参数引用缺失/不唯一：" + str(ident))
            return self._closure(found[0], ident, visiting)
        message = self.catalog[group].get(ident)
        if message is None:
            reason = "; ".join(self.rejected.get(key, []))
            raise ParameterError(f"缺{group}/{ident}" + ("：" + reason if reason else ""))
        if group == "AgentInfos":
            # 协议引用齐全仍可能缺当前客户端XML；整条技能闭包失败后由
            # build_basket记录缺口并选择无投射物的兼容普攻，不伪造弹道。
            _validate_agent_motion(message, self.motion_templates)
        visiting.add(key)
        result = {key: message}
        for target, value in _dependencies(group, message):
            result.update(self._closure(target, value, visiting))
        return result

    def build_basket(self, stat_ids):
        keys = sorted({parse_stat_id(value) for value in stat_ids})
        if not keys:
            raise ParameterError("statID列表为空")
        basket = self.cls()
        provenance = {"schemaVersion": 1, "sourceVersion": "2019-1.1.70-editor-tables", "inputs": self.input_evidence,
            "sourceWarnings": self.source_warnings,
            "formula": "2020原生CalcFinalMobStat五项基础属性，按字段名适配旧CSV；float32每步乘法后向零截断入int32协议", "integerConversion": "兼容协议选择，尚未验证旧服务器最终取整", "percentagePolicy": "保持Mob原表整数，不作未经验证的归一化", "enemies": [], "objects": [], "gaps": [],
            "fullOriginalCombatParameters": False, "verification": "协议回读/引用闭包及投射物emit/bullet XML校验，未进行实机/UI测试"}
        selected = {}
        emitted_types = {}
        for mob_id, rank, level in keys:
            stat_id = f"{mob_id}-{rank}-{level}"
            if mob_id not in self.mob or level not in self.levels:
                raise ParameterError("Mob/Level原表缺失：" + stat_id)
            row = self.mob[mob_id]
            rank_name = ("normal", "elite", "boss")[rank - 1]
            type_id = _integer(row["mob_type_info_" + rank_name])
            if type_id not in self.types:
                raise ParameterError("MobType原表缺失：" + stat_id)
            typ_row = self.types[type_id]
            monster = basket.MobInfos.add()
            for field in monster.DESCRIPTOR.fields:
                source = _snake(field.name)
                if source in row:
                    setattr(monster, field.name, row[source] if field.type == field.TYPE_STRING else _integer(row[source]))
            monster.ID, monster.CurType, monster.Level = mob_id, rank, level
            if not monster.Model:
                raise ParameterError("Mob原模型为空：" + stat_id)
            base = [_f32(float(row[_snake(f)])) for f in _BASIC]
            multipliers = []
            for name in ("hp", "attack", "defense"):
                index = _integer(typ_row["attribute_type_" + name])
                if not 0 <= index < 10:
                    raise ParameterError("等级成长索引越界：" + stat_id)
                factor = _f32(_integer(self.levels[level][f"attribute_modulus{index + 1}"]) / 10000)
                if name != "defense":
                    factor = _f32(factor * _f32(_integer(typ_row["multi_" + ("hp" if name == "hp" else "attack")]) / 10000))
                multipliers.append(factor)
            values = [int(_f32(v * multipliers[i])) for v, i in zip(base, (0, 1, 1, 2, 2))]
            for field, value in zip(_BASIC, values):
                setattr(monster, field, value)
            if monster.Hp <= 0:
                raise ParameterError("原成长结果无正HP：" + stat_id)
            # 召唤对象还需要独立的等级/位阶；缺这条链时不输出悬空ID。
            for i in range(1, 4):
                field = f"SummonMob{i}"
                if getattr(monster, field):
                    provenance["gaps"].append({"statID": stat_id, "kind": "summon-disabled", "originalID": getattr(monster, field), "reason": "原表召唤缺独立statID/参数闭包"})
                    setattr(monster, field, 0)
                    setattr(monster, f"SummonNum{i}", 0)
            # 一个type可能被不同等级敌人共享；字段自身不随level猜测成长。
            type_key = type_id
            if type_key not in emitted_types:
                typ = basket.MobTypeInfos.add()
                for field in typ.DESCRIPTOR.fields:
                    if _snake(field.name) in typ_row:
                        setattr(typ, field.name, _integer(typ_row[_snake(field.name)]))
                typ.ID = type_id
                good_spells = []
                had_gap = False
                for i in range(1, 11):
                    original = _integer(typ_row[f"mob_spell{i}"])
                    if not original:
                        continue
                    try:
                        selected.update(self._closure("SpellInfos", original))
                        good_spells.append(original)
                    except ParameterError as exc:
                        setattr(typ, f"MobSpell{i}", 0)
                        had_gap = True
                        provenance["gaps"].append({"statID": stat_id, "typeID": type_id, "kind": "skill-compatible-replacement", "originalID": original, "reason": str(exc)})
                for prefix, count, group in (("BuffId", 2, "BuffInfos"), ("Trigger", 5, "TriggerInfos")):
                    for i in range(1, count + 1):
                        field, original = f"{prefix}{i}", getattr(typ, f"{prefix}{i}")
                        if not original:
                            continue
                        try:
                            selected.update(self._closure(group, original))
                        except ParameterError as exc:
                            setattr(typ, field, 0)
                            if prefix == "BuffId":
                                setattr(typ, f"BuffLayer{i}", 0)
                            had_gap = True
                            provenance["gaps"].append({"statID": stat_id, "typeID": type_id, "kind": "dependency-disabled", "originalID": original, "reason": str(exc)})
                try:
                    if had_gap:
                        raise ParameterError("技能/触发链不完整，原树可能仍尝试缺失的技能")
                    selected.update(self._closure("BehaviorTreeArgumentInfos", typ.BehaviorTreeId))
                except ParameterError as exc:
                    # 使用完整普通攻击样本时保留其参数；缺时采用现有本地模板。
                    compatible = self.compat_magical if monster.PhysicalAttack == 0 and monster.MagicalAttack > 0 else self.compat_spell
                    primary = next((i for i in good_spells if self.catalog["SpellInfos"][i].SpellType == 1 and "NormalAttack" in self.catalog["SpellInfos"][i].SpellTempletId), compatible.ID)
                    selected.update(self._closure("SpellInfos", primary))
                    for gap in provenance["gaps"]:
                        if gap.get("typeID") == type_id and gap["kind"] == "skill-compatible-replacement":
                            gap["replacementID"] = primary
                            gap["policy"] = "移除缺参技能槽，由兼容树调用该普通攻击"
                    if primary not in good_spells:
                        if typ.MobSpell1:
                            provenance["gaps"].append({"statID": stat_id, "typeID": type_id, "kind": "primary-slot-compatible-replacement", "originalID": typ.MobSpell1, "replacementID": primary, "reason": "兼容normal_attack树需要一个可执行的普攻"})
                        typ.MobSpell1 = primary
                    tree = type(self.compat_tree)()
                    tree.CopyFrom(self.compat_tree)
                    tree.ID, tree.Argument0 = 8_900_000_000_000_000 + type_id, primary
                    selected[("BehaviorTreeArgumentInfos", tree.ID)] = tree
                    provenance["objects"].append({"group": "BehaviorTreeArgumentInfos", "id": tree.ID, "kind": "compatible-normal-attack-tree", "templateID": self.compat_tree.ID, "primarySpellID": primary})
                    provenance["gaps"].append({"statID": stat_id, "typeID": type_id, "kind": "behavior-compatible-replacement", "originalID": typ.BehaviorTreeId, "replacementID": tree.ID, "reason": str(exc)})
                    typ.BehaviorTreeId = tree.ID
                emitted_types[type_key] = typ
            # 当前rank只引用实际输出的type；未选位阶引用置0，避免缺表项悬空。
            monster.MobTypeInfoNormal = monster.MobTypeInfoElite = monster.MobTypeInfoBoss = 0
            setattr(monster, "MobTypeInfo" + rank_name.capitalize(), type_id)
            provenance["enemies"].append({"statID": stat_id, "mobID": mob_id, "rank": rank, "level": level, "originalTypeID": type_id,
                "basicStats": dict(zip(_BASIC, values)), "levelFactorSlots": {n: _integer(typ_row["attribute_type_" + n]) + 1 for n in ("hp", "attack", "defense")}, "parameters": "原表基础/位阶成长；技能和AI替换见gaps"})
        for (group, ident), message in sorted(selected.items()):
            getattr(basket, group).add().CopyFrom(message)
            if (group, ident) in self.sources:
                provenance["objects"].append({"group": group, "id": ident, **self.sources[(group, ident)]})
        validate_basket(basket, motion_templates=self.motion_templates)
        data = basket.SerializeToString(deterministic=True)
        check = self.cls.FromString(data)
        validate_basket(check, motion_templates=self.motion_templates)
        if {(m.ID, m.CurType, m.Level) for m in check.MobInfos} != set(keys):
            raise ParameterError("statID与协议回读不一致")
        provenance["counts"] = {g: len(getattr(check, g)) for g in _GROUPS}
        provenance["protobufSha256"] = hashlib.sha256(data).hexdigest()
        return data, copy.deepcopy(provenance)


@lru_cache(maxsize=4)
def _builder(table_dir, descriptors, guide_dir, compatibility_responses, config, assets):
    return EnemyParameterBuilder(table_dir, descriptors, guide_dir, compatibility_responses, config, assets)


def build_basket(stat_ids, *, table_dir=TABLE_DIR, descriptors=DESCRIPTORS, guide_dir=GUIDE_DIR,
                 compatibility_responses=COMPATIBILITY_RESPONSES, config=CONFIG, assets=ASSETS):
    """返回敌人protobuf原字节及可JSON序列化来源/兼容缺口，不产生文件。"""
    paths = tuple(str(Path(p).resolve()) for p in (table_dir, descriptors, guide_dir, compatibility_responses, config, assets))
    return _builder(*paths).build_basket(stat_ids)
