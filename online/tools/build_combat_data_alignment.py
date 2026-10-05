"""Build the evidence-backed combat data candidate without deploying it.

Keep restored stage layouts, engine binaries, unsupported damage coefficients,
and 2016-only combat constants unchanged. The fixture change is one role route.
"""
from __future__ import annotations

import base64
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_combat_weapon_repair as wire

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / '热更新测试/主线热更候选'
AUDIT = PROJECT / '验收/战斗全面核查'
OUTPUT = AUDIT / '候选'
BASE = '155-97d31dc9cc2653617d30057cff1b2c0925e8d2a78e91241752a3d3661bbf05ed'
BASE_FIXTURE = '2b9bc5116b66f975287373bc7b60c038306686d53de6a0dd9258ccc70dba283d'
BASE_SPELL = '4fa0f229b76c1db3963724e65cf2aa844cb8da7d88cf67d9bc38f57bb5eb04e5'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def normalized(node):
    return (node.tag, tuple(sorted(node.attrib.items())), (node.text or '').strip(),
            tuple(normalized(child) for child in node))


def read(name):
    return json.loads((AUDIT / name).read_text(encoding='utf-8'))


def patch_xml(raw):
    env, obj, tree, root = wire.load_spell_bundle(raw)
    before = copy.deepcopy(root)
    lookup = {n.get('TempletID'): n for n in root}
    original_names = [n.get('TempletID') for n in root]
    changes = read('关服8模板差异与实际引用.json')
    late = ET.parse(PROJECT / '参考资料/战斗数据核查/关服前热更配置/spells.xml').getroot()
    assert sha((PROJECT / '参考资料/战斗数据核查/关服前热更配置/spells.xml').read_bytes()) == changes['sourceSHA256']
    official = {n.get('TempletID'): n for n in late}
    altered = set()
    for row in changes['changes']:
        name = row['template']
        assert original_names.count(name) == 1
        replacement = ET.fromstring(row['replacementXML'])
        assert normalized(replacement) == normalized(official[name])
        old = lookup[name]
        index = list(root).index(old)
        root.remove(old)
        root.insert(index, replacement)
        altered.add(name)
    clone = changes['actualOffline121ClonePatch']
    target = lookup[clone['template']]
    phases = target.findall('FuncDef')
    assert len(phases) == clone['beforeFuncDefs'] == 3
    first = normalized(phases[0])
    for node in phases[1:]:
        target.remove(node)
    assert normalized(target.findall('FuncDef')[0]) == first
    altered.add(clone['template'])
    # Any additional argument-slot collisions are handled by a separate,
    # explicit list; the original coefficients and animation phases survive.
    slot_file = AUDIT / '6把武器声音附伤兼容分槽清单.json'
    slot_changes = []
    if slot_file.exists():
        raw_changes = read(slot_file.name)['changes']
        for raw_row in raw_changes:
            row = dict(template=raw_row['template'], mapping=raw_row['slotMapping'],
                silentSlot=raw_row['emptySoundSlot'],
                soundSlots=[s['before'] for s in raw_row['soundRefs']],
                effectIDs=[p['effectID'] for p in raw_row['roleParams']])
            slot_changes.append(row)
            target = lookup[row['template']]
            old = copy.deepcopy(target)
            assert original_names.count(row['template']) == 1
            for node in target.iter():
                if node.tag == 'LinkString' and node.get('String2') in row['soundSlots']:
                    node.set('String2', '@ARGUMENT' + str(row['silentSlot']))
                elif node.tag != 'LinkString':
                    import re
                    for field, expression in list(node.attrib.items()):
                        node.set(field, re.sub(r'@ARGUMENT(\d+)\b',
                            lambda m: '@ARGUMENT' + str(row['mapping'].get(m.group(1), m.group(1))),
                            expression))
            assert len(target.findall('FuncDef')) == len(old.findall('FuncDef'))
            assert normalized(target) == normalized(ET.fromstring(raw_row['replacementXML']))
            altered.add(row['template'])
    assert [n.get('TempletID') for n in root] == original_names
    actual = {a.get('TempletID') for a, b in zip(before, root) if normalized(a) != normalized(b)}
    assert actual == altered
    assert len(root) == len(before)
    serialized = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    tree['bytes'] = list(bytes(x ^ 255 for x in serialized) if tree.get('isEncrypt') else serialized)
    before_objects = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    obj.save_typetree(tree)
    payload = env.file.save(packer='original')
    check_env, check_obj, check_tree, check_root = wire.load_spell_bundle(payload)
    assert normalized(root) == normalized(check_root)
    after_objects = {o.path_id: sha(o.get_raw_data()) for o in check_env.objects}
    assert {p for p in before_objects if before_objects[p] != after_objects[p]} == {obj.path_id}
    return payload, sorted(altered), slot_changes


def patch_role(raw, slots):
    role = wire.role_class()()
    role.ParseFromString(raw)
    old = copy.deepcopy(role)
    unit = role.Unit
    type_changes = read('92条武器触发类型修复清单.json')['changes']
    spells = {s.ID: s for s in unit.SpellInfos if s.ID != 90911101}
    for row in type_changes:
        spell = spells[row['ID']]
        assert spell.SpellType == 1 and spell.SpellTempletId == row['template']
        spell.SpellType = 4
    mapping = read('4组武器召唤ID冲突修复映射.json')['changes']
    colliding_spells = [s for s in unit.SpellInfos if s.ID == 90911101]
    colliding_trees = [s for s in unit.BehaviorTreeArgumentInfos if s.ID == 90921101]
    assert len(colliding_spells) == len(colliding_trees) == 4
    assert len({s.SerializeToString() for s in colliding_spells}) == 1
    assert len({s.SerializeToString() for s in colliding_trees}) == 1
    cloned_spell, cloned_tree = copy.deepcopy(colliding_spells[0]), copy.deepcopy(colliding_trees[0])
    assert sum(e.ID == 90911101 for e in unit.EffectArgumentInfos) == 4
    all_ids = {s.ID for group in ('SpellInfos','BuffInfos','AgentInfos','TriggerInfos',
                   'MobInfos','MobTypeInfos','EffectArgumentInfos','BehaviorTreeArgumentInfos')
               for s in getattr(unit, group)}
    for row in mapping:
        assert row['newSpellID'] not in all_ids and row['newBehaviorTreeID'] not in all_ids
        effect = unit.EffectArgumentInfos[row['effectArgumentBeforeIndex']]
        assert effect.ID == 90911101
        for field, value in row['preserveEffectArgs'].items():
            assert getattr(effect, field) == int(value)
        effect.ID = row['newEffectArgumentID']
        spell = unit.SpellInfos.add()
        spell.CopyFrom(cloned_spell)
        spell.ID = row['newSpellID']
        spell.SpellEffectArgu = row['newEffectArgumentID']
        tree = unit.BehaviorTreeArgumentInfos.add()
        tree.CopyFrom(cloned_tree)
        tree.ID = row['newBehaviorTreeID']
        tree.Argument0 = row['newSpellID']
        mob, = [m for m in unit.MobTypeInfos if m.ID == row['MobTypeInfoID']]
        assert mob.MobSpell1 == 90911101 and mob.BehaviorTreeId == 90921101
        mob.MobSpell1 = row['newSpellID']
        mob.BehaviorTreeId = row['newBehaviorTreeID']
    for group, collision in (('SpellInfos',90911101),('BehaviorTreeArgumentInfos',90921101)):
        values = [copy.deepcopy(s) for s in getattr(unit, group) if s.ID != collision]
        del getattr(unit, group)[:]
        getattr(unit, group).extend(values)
    for row in slots:
        for eid in row['effectIDs']:
            effect, = [e for e in unit.EffectArgumentInfos if e.ID == eid]
            for old_slot, new_slot in row['mapping'].items():
                assert getattr(effect, 'Argument'+str(new_slot)) == 0
                setattr(effect, 'Argument'+str(new_slot), getattr(effect, 'Argument'+old_slot))
            assert getattr(effect, 'Argument'+str(row['silentSlot'])) == 0
    for group in ('SpellInfos','BuffInfos','AgentInfos','TriggerInfos','MobInfos',
                  'MobTypeInfos','EffectArgumentInfos','BehaviorTreeArgumentInfos'):
        ids = [s.ID for s in getattr(unit, group)]
        assert len(ids) == len(set(ids)), (group, Counter(ids).most_common(5))
    assert role.CommonAttr == old.CommonAttr and role.SvCombatInfo == old.SvCombatInfo
    assert role.RoleLv == old.RoleLv and role.CombatConst == old.CombatConst
    # Changes outside the Unit are prohibited, including stage/target payloads.
    stripped, prior = copy.deepcopy(role), copy.deepcopy(old)
    stripped.ClearField('Unit'); prior.ClearField('Unit')
    assert stripped.SerializeToString() == prior.SerializeToString()
    return role.SerializeToString(), len(type_changes), len(mapping)


def main():
    assert (ROOT / 'current').read_text(encoding='utf-8').strip() == BASE
    path = PROJECT / 'legacy-server/resources/offline_responses.json'
    source = path.read_bytes()
    assert sha(source) == BASE_FIXTURE
    manifest = json.loads((ROOT / 'releases' / BASE / 'manifest.json').read_text(encoding='utf-8'))
    entry, = [a for a in manifest['assets'] if a['path'] == wire.SPELL_PATH]
    raw = (ROOT / 'blobs' / entry['sha256']).read_bytes()
    assert sha(raw) == entry['sha256'] == BASE_SPELL
    spells, templates, slots = patch_xml(raw)
    fixture = json.loads(source.decode('utf-8'))
    before = copy.deepcopy(fixture)
    raw_role = base64.b64decode(fixture['/combat/role/info']['base64'], validate=True)
    role, types, summons = patch_role(raw_role, slots)
    fixture['/combat/role/info']['base64'] = base64.b64encode(role).decode('ascii')
    assert {k for k in fixture if fixture[k] != before[k]} == {'/combat/role/info'}
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'spells.ab').write_bytes(spells)
    (OUTPUT / 'role-combat-candidate.pb').write_bytes(role)
    (OUTPUT / 'offline_responses.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    report = dict(base=BASE, baseFixtureSha256=BASE_FIXTURE, baseSpellSha256=BASE_SPELL,
        candidateSpellSha256=sha(spells), candidateRoleSha256=sha(role),
        candidateFixtureSha256=sha((OUTPUT / 'offline_responses.json').read_bytes()),
        weaponTypeChanges=types, uniqueSummonAttackMappings=summons,
        changedTemplates=templates, slotChanges=slots,
        unrelatedRoutesUnchanged=True, layoutsUnchanged=True, engineUnchanged=True,
        limitations=['CommonAttr全队合成权重没有原服证据，保留现公式等待补全。',
            '仅2016样本存在的等级/概率常量不覆盖2020客户端。',
            '没有原服实参的伤害、刻印晋升层数与耐久值不凭文字推测。'])
    (OUTPUT / 'candidate.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    assert json.loads((OUTPUT / 'offline_responses.json').read_text(encoding='utf-8')) == fixture
    print('COMBAT_ALIGNMENT_CANDIDATE_OK', types, summons, len(templates), sha(spells))


if __name__ == '__main__':
    main()
