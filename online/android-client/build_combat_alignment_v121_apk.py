"""Fold the signed v157 combat resources into the preserved v120 client."""
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,r'D:\Project\魔女兵器工程恢复\本地模式客户端')
import build_preserved_battle_v111_apk as builder

builder.SOURCE=PROJECT/'构建/战斗修复/魔女兵器-在线本地双区服-v120-测试.apk'
builder.SOURCE_SHA='4548ba0b5067f0853a4ff60bf6c9f214291878c0bfe65f40ffaba3bd434ef97e'
builder.OUTPUT=PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'
builder.REPORT=builder.OUTPUT.with_suffix('.json')
builder.TEMP=Path(r'D:\Environment\Android\temp\witch-combat-alignment-v121')
builder.SOURCE_SETTLEMENT_SHA=builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE,builder.TARGET_VERSION_CODE=20043120,20043121
builder.CACHE_WARNING='内置第157版战斗数据校正资源；启动时按原版更新流程核对资源。'

if __name__=='__main__':
    record=json.loads((PROJECT/'验收/战斗全面核查/发布.json').read_text(encoding='utf-8'))
    assert record['release'].startswith('157-')
    with zipfile.ZipFile(builder.SOURCE) as apk:
        fixture=json.loads(apk.read('assets/offline_responses.json'))
    revised=json.loads(Path(record['fixture']).read_text(encoding='utf-8'))
    fixture['/combat/role/info']=revised['/combat/role/info']
    builder.build(record['release'],extra_members={
        'assets/offline_responses.json':(json.dumps(fixture,ensure_ascii=False,indent=2)+'\n').encode('utf-8')})
