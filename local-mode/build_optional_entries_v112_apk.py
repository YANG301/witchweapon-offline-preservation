"""Fold the CAPH/guide-entry signed snapshot into the complete dual-mode APK."""
import json
from pathlib import Path
import build_preserved_battle_v111_apk as builder

PROJECT = Path(r'D:\Project\魔女兵器在线版')
builder.SOURCE = PROJECT / '构建/原始关卡候选/魔女兵器-在线本地双区服-v111-测试.apk'
builder.SOURCE_SHA = '6528e981016ed87ce881a503011fee4843e980bd95510a210fcf3a348f7f2d54'
builder.OUTPUT = PROJECT / '构建/入口显示修复/魔女兵器-在线本地双区服-v112-测试.apk'
builder.REPORT = builder.OUTPUT.with_suffix('.json')
builder.TEMP = Path(r'D:\Environment\Android\temp\witch-optional-v112')
builder.SOURCE_SETTLEMENT_SHA = builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE, builder.TARGET_VERSION_CODE = 20043111, 20043112
builder.CACHE_WARNING = '内置第123版资源；原版更新流程仍会检查后续热更新。'

if __name__ == '__main__':
    release = json.loads((PROJECT/'验收/入口显示修复/发布.json').read_text(encoding='utf-8'))['release']
    builder.build(release)
