"""Fold the native CAPH-button signed snapshot into the complete dual-mode APK."""
import json
from pathlib import Path
import build_preserved_battle_v111_apk as builder

PROJECT = Path(r'D:\Project\魔女兵器在线版')
builder.SOURCE = PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v112-测试.apk'
builder.SOURCE_SHA = '3a721ad57b901308db9ddd0d44682940ba72c39f82e5e91bf97e546772ee659a'
builder.OUTPUT = PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk'
builder.REPORT = builder.OUTPUT.with_suffix('.json')
builder.TEMP = Path(r'D:\Environment\Android\temp\witch-caph-button-v113')
builder.SOURCE_SETTLEMENT_SHA = builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE, builder.TARGET_VERSION_CODE = 20043112, 20043113
builder.CACHE_WARNING = '内置第125版资源；CAPH商店按钮保留，关闭提示沿用原版点击校验。'

if __name__ == '__main__':
    release = json.loads((PROJECT/'验收/入口显示修复/CAPH按钮修复.json').read_text(encoding='utf-8'))['release']
    builder.build(release)
