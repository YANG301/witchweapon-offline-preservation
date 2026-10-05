"""Build an opt-in catalog from preserved 2019 layouts and editor attributes.

Only stages with verified source layouts are added. Existing catalogs, rewards,
account progress and the missing stages are never rewritten by this generator.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT.parent / '参考资料/战斗数据核查'
OUTPUT = ROOT / 'test-profiles/preserved-original/preserved_battle_catalog.json'
LAYOUT_ROOT = EVIDENCE / '原始关卡/国服1.1.70'
CATALOGS = ('stage_catalog.json', 'daily_stage_catalog.json',
            'weapon_furnace_catalog.json', 'stone_slate_catalog.json')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def stat_ids(node):
    if isinstance(node, dict):
        if 'statID' in node:
            value = node['statID']
            if not isinstance(value, str) or not re.fullmatch(r'\d+-[123]-\d+', value):
                raise ValueError('Unexpected original monster statID: ' + repr(value))
            yield value
        for value in node.values():
            yield from stat_ids(value)
    elif isinstance(node, list):
        for value in node:
            yield from stat_ids(value)


def load_layout(entry, index):
    paths = entry['selectedPaths']
    if len(paths) != 1:
        raise ValueError('Ambiguous source for stage ' + entry['stageID'])
    member = paths[0]
    directory = '关卡文本' if member.startswith('assets/level/new/') else '早期关卡样例'
    path = LAYOUT_ROOT / directory / Path(member).name
    raw = path.read_bytes()
    if sha(raw) != index[member]['sha256']:
        raise ValueError('Original layout hash changed: ' + str(path))
    data = json.loads(raw.decode('utf-8-sig'))
    if str(data['EnemyLayer']['levelID']) != entry['stageID']:
        raise ValueError('Wrong original stage ID: ' + str(path))
    if not data['EnemyLayer']['areas']:
        raise ValueError('Empty original stage: ' + str(path))
    scene = data['MapInfo']['sceneName']
    match = re.fullmatch(r'map_(\d+)_\w+', scene)
    if not match or not entry['availableScene']:
        raise ValueError('Unavailable original scene: ' + scene)
    return data, {'archiveMember': member, 'sha256': sha(raw),
                  'mapId': int(match[1]), 'sceneName': scene}


def generate():
    from original_enemy_parameters import build_basket
    coverage = json.loads((EVIDENCE / '关卡覆盖核对.json').read_text(encoding='utf-8'))
    index = {item['path']: item for item in coverage['layouts']}
    resource_hashes = {name: sha((ROOT / 'resources' / name).read_bytes()) for name in CATALOGS}
    expected = {name: coverage['productionCatalogsUnchanged'][name] for name in CATALOGS}
    if resource_hashes != expected:
        raise ValueError('Fallback resources changed since the source audit; review before generating')
    result = {'schemaVersion': 1, 'mode': 'preserved-layouts-v1',
              'sourceVersion': '1.1.70.19012564',
              'description': '保留原始关卡布局与编辑器基础属性；缺失特殊技能参数逐项记录兼容处理。',
              'baseResourceHashes': resource_hashes, 'stages': {}, 'missingStageIds': []}
    counts = Counter()
    for entry in coverage['coverage']:
        stage_id = entry['stageID']
        if not entry['selectedPaths']:
            result['missingStageIds'].append(int(stage_id))
            continue
        layout, source = load_layout(entry, index)
        ids = sorted(set(stat_ids(layout)))
        if not ids:
            raise ValueError('No monster references in restored stage ' + stage_id)
        wire, provenance = build_basket(ids)
        result['stages'][stage_id] = {
            'id': int(stage_id), 'kind': entry['mode'], 'source': source,
            'navigationByteIdenticalTo2020': entry['navigationByteIdentical'],
            'combatJson': layout, 'combatMobInfo': base64.b64encode(wire).decode('ascii'),
            'statIds': ids, 'enemyParameterProvenance': provenance,
        }
        counts[entry['mode']] += 1
    if dict(counts) != {'主线': 190, '日常检视': 36, '刻印熔炉': 4,
                        '石板挑战': 5, '结界迷宫': 12}:
        raise ValueError('Unexpected restored stage membership: ' + repr(counts))
    if len(result['missingStageIds']) != 50 or len(result['stages']) != 247:
        raise ValueError('Restoration coverage changed')
    result['summary'] = dict(counts)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    destination = args.output.resolve()
    if (ROOT / 'resources').resolve() in destination.parents:
        raise ValueError('Build the isolated candidate before enabling a release resource')
    result = generate()
    raw = (json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    if destination.read_bytes() != raw:
        raise IOError('Generated catalog readback differs')
    print(json.dumps({'status': 'PRESERVED_BATTLE_CATALOG_OK', 'restored': 247,
                      'fallbackUnchanged': 50, 'bytes': len(raw), 'sha256': sha(raw),
                      'output': str(destination)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
