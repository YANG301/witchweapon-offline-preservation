"""Build the user-requested temporary one-room, one-enemy campaign profile.

Original tables and the reconstructed layout remain separate restoration input.
This is explicitly a playable placeholder, not recovered original server data.
"""
import base64
import copy
import hashlib
import json
from pathlib import Path

from generate_stage_catalog import basket_class, DESCRIPTORS

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'resources/stage_catalog_reconstruction.json'
TARGET = ROOT / 'resources/stage_catalog.json'
SOURCE_SHA = '90a8cd2a161d98362b0b1a7046e4a6c0d7d56378346463f9ba329fcaa7516e9e'
MODE = 'simple-campaign-v1'


def generate():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('Restoration input differs from reviewed layout')
    document = json.loads(raw)
    first = document['stages']['3110001001']
    template = copy.deepcopy(first['combatJson'])
    zone = template['EnemyLayer']['areas'][0]['zones'][0]
    enemy = next(m for w in zone['waves'] for m in w['monsters']
                 if m['statID'] == '331010342201-1-1')
    enemy['name'] = 'Enemy_1'
    wave = copy.deepcopy(zone['waves'][0])
    wave['monsters'] = [enemy]
    zone['waves'] = [wave]
    template['EnemyLayer']['areas'] = [dict(name='Area_0', zones=[zone])]
    template['MapInfo'].update(globalBuff=0, isForceGuideMap=False,
                               servantInitialEnergyRate=10000)
    template['QuestInfo']['LevelObjectiveType'] = 0
    basket_type = basket_class(DESCRIPTORS)
    original_basket = basket_type.FromString(base64.b64decode(first['combatMobInfo']['base64']))
    basket = basket_type()
    basket.CopyFrom(original_basket)
    basket.ClearField('MobInfos')
    basket.ClearField('MobTypeInfos')
    mob = basket.MobInfos.add()
    mob.CopyFrom(next(m for m in original_basket.MobInfos if m.ID == 331010342201))
    mob.Hp = 100
    mob.PhysicalAttack = mob.MagicalAttack = 1
    mob.PhysicalDefense = mob.MagicalDefense = 0
    basket.MobTypeInfos.add().CopyFrom(next(m for m in original_basket.MobTypeInfos
                                          if m.ID == 331010342201))
    wire = dict(type='application/octet-stream', base64=base64.b64encode(basket.SerializeToString()).decode('ascii'))
    for sid, stage in document['stages'].items():
        original_quest = (stage.get('combatJson') or {}).get('QuestInfo')
        original_mob = stage['source'].get('mobList')
        if original_quest is not None:
            bonus_type = original_quest['BonusType']
            bonus_param = original_quest['BonusParam']
            if original_mob is None or bonus_type != int(original_mob['instBonusType']) or \
                    bonus_param != float(original_mob['intstBonusParam'] or 0):
                raise ValueError('Original sweep condition disagrees with MobList: ' + sid)
        else:
            # Chapter 16 has no preserved InstanceMobList row. Keep the
            # temporary client profile's repeatable-stage convention there.
            if original_mob is not None or not sid.startswith('3110016'):
                raise ValueError('Unexpected missing original sweep condition: ' + sid)
            repeatable = stage['source']['instance']['instance_repeatable'] == '1'
            bonus_type = 2 if repeatable else 0
            bonus_param = 0.5 if repeatable else 0.75
        prior = dict(supported=stage['supported'], reason=stage['reason'],
                     mapId=stage.get('mapId'), guide=stage.get('guide'))
        # Avoid presenting original navigation evidence as validation of a new layout.
        for key in ('navigation', 'guide', 'enemies', 'originalEvidence'):
            stage.pop(key, None)
        battle = copy.deepcopy(template)
        battle['EnemyLayer']['levelID'] = sid
        battle['EnemyLayer']['lvMin'] = battle['EnemyLayer']['lvMax'] = 1
        # Sweep visibility is decided by this battle condition as well as the
        # account's three-star progress. Clearing it hid the original button.
        battle['QuestInfo'].update(BonusType=bonus_type, BonusParam=bonus_param)
        stage.update(supported=True, reason='', mode=MODE, mapId=1010,
                     sceneName='map_1010_classroomhallway',
                     layoutSource='user-requested temporary single-room placeholder',
                     localReconstruction=True, restorationEvidence=prior,
                     guide=dict(disabled=True, reason='single wave temporary campaign'),
                     enemies=[dict(id=331010342201, model='mob_422', rank=1, level=1)],
                     combatJson=battle, combatMobInfo=copy.deepcopy(wire))
    document.update(mode=MODE,
        description='用户指定的临时极简主线：235关统一教学走廊、单区单波、一个弱敌；不代表原版关卡设计。',
        restorationSource=dict(file=SOURCE.name, sha256=SOURCE_SHA),
        summary=dict(total=235, supported=235, unsupported=0, normal=160, elite=75,
                     maps=1, zones=235, waves=235, monstersPerStage=1, guideStages=0,
                     guideCombatEvents=0, unsupportedIds=[]))
    TARGET.write_text(json.dumps(document, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
    print('SIMPLE_CAMPAIGN_GENERATED', len(document['stages']), hashlib.sha256(TARGET.read_bytes()).hexdigest())


if __name__ == '__main__':
    generate()
