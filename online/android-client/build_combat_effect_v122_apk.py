"""Keep the deployed combat/maze hotfix in the next complete APK."""
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode=True
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,r'D:\Project\魔女兵器工程恢复\本地模式客户端')
import build_preserved_battle_v111_apk as builder

builder.SOURCE=PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'
builder.SOURCE_SHA='6183635cc03a347739f54fe5d4c5ce5c32316186a856556891b7e66b741734d3'
builder.OUTPUT=PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v122-测试.apk'
builder.REPORT=builder.OUTPUT.with_suffix('.json')
builder.TEMP=Path(r'D:\Environment\Android\temp\witch-combat-effect-v122')
builder.SOURCE_SETTLEMENT_SHA=builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE,builder.TARGET_VERSION_CODE=20043121,20043122
builder.CACHE_WARNING='内置第163版能量、索敌、分批技能和迷宫选人修复；启动时按原版更新流程核对资源。'

if __name__=='__main__':
    record=json.loads((PROJECT/'验收/战斗效果修复/发布.json').read_text(encoding='utf-8'))
    followup=json.loads((PROJECT/'验收/战斗效果修复/后续发布.json').read_text(encoding='utf-8'))
    assert record['release'].startswith('159-') and followup['release'].startswith('163-')
    with zipfile.ZipFile(builder.SOURCE) as z:fixture=json.loads(z.read('assets/offline_responses.json'))
    revised=json.loads(Path(record['fixture']).read_text(encoding='utf-8'))
    fixture['/combat/role/info']=revised['/combat/role/info']
    builder.build(followup['release'],extra_members={'assets/offline_responses.json':
        (json.dumps(fixture,ensure_ascii=False,indent=2)+'\n').encode('utf-8')})
