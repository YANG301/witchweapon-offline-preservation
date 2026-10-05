"""Fold the reviewed combat resources and matching role fixture into v120."""
import json
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, r'D:\Project\魔女兵器工程恢复\本地模式客户端')
import build_preserved_battle_v111_apk as builder

builder.SOURCE = PROJECT / '构建/运行性能修复/魔女兵器-在线本地双区服-v119-测试.apk'
builder.SOURCE_SHA = '1ad58f207fb04d2cf5f5cf0f81072d13b4356788e9d62276bf6b84b9962dac5f'
builder.OUTPUT = PROJECT / '构建/战斗修复/魔女兵器-在线本地双区服-v120-测试.apk'
builder.REPORT = builder.OUTPUT.with_suffix('.json')
builder.TEMP = Path(r'D:\Environment\Android\temp\witch-combat-v120')
builder.SOURCE_SETTLEMENT_SHA = builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE, builder.TARGET_VERSION_CODE = 20043119, 20043120
builder.CACHE_WARNING = '内置第155版战斗修复资源；启动时按原版更新流程核对资源。'

if __name__ == '__main__':
    report = json.loads((PROJECT / '验收/战斗修复/发布.json').read_text(encoding='utf-8'))
    release = report['clientFollowup']['release']
    assert release.startswith('155-')
    assert report['clientFollowup']['status'] == 'DEPLOYED_AND_HEALTHY'
    with zipfile.ZipFile(builder.SOURCE) as source:
        fixture = json.loads(source.read('assets/offline_responses.json'))
    revised = json.loads(Path(report['fixture']).read_text(encoding='utf-8'))
    fixture['/combat/role/info'] = revised['/combat/role/info']
    builder.build(release, extra_members={
        'assets/offline_responses.json': (json.dumps(fixture, ensure_ascii=False,
            indent=2) + '\n').encode('utf-8')})
