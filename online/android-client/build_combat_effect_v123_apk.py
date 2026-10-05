"""Embed the final combat hotfix and the level-one maze access table."""
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
import build_combat_effect_v122_apk as prior

builder=prior.builder
PROJECT=prior.PROJECT
builder.SOURCE=PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v122-测试.apk'
builder.SOURCE_SHA='3bdfcff4bbbf1cb0ae0992ab2bf123fb4b71bd9def98aa6ab83afc8c157b8807'
builder.SOURCE_VERSION_CODE,builder.TARGET_VERSION_CODE=20043122,20043123
builder.OUTPUT=PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
builder.REPORT=builder.OUTPUT.with_suffix('.json')
builder.TEMP=Path(r'D:\Environment\Android\temp\witch-combat-effect-v123')
builder.CACHE_WARNING='内置第165版能量、索敌、分批技能和迷宫修复；支持低等级魔女整备。'

if __name__=='__main__':
    record=json.loads((PROJECT/'验收/战斗效果修复/准入发布.json').read_text(encoding='utf-8'))
    assert record['release'].startswith('165-')
    builder.build(record['release'])
