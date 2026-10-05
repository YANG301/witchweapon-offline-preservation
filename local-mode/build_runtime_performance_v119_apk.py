"""Fold the signed, scene-scoped UI performance repair into the online/local APK."""
import json
from pathlib import Path
import build_preserved_battle_v111_apk as builder

PROJECT=Path(r'D:\Project\魔女兵器在线版')
builder.SOURCE=PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk'
builder.SOURCE_SHA='6c9fffe0faf44a44d43660ec05826a9aa8b3c502d5fa8ae2f4d306ae47ee161e'
builder.OUTPUT=PROJECT/'构建/运行性能修复/魔女兵器-在线本地双区服-v119-测试.apk'
builder.REPORT=builder.OUTPUT.with_suffix('.json')
builder.TEMP=Path(r'D:\Environment\Android\temp\witch-performance-v119')
builder.SOURCE_SETTLEMENT_SHA=builder.PATCHED_SETTLEMENT_SHA
builder.SOURCE_VERSION_CODE,builder.TARGET_VERSION_CODE=20043113,20043119
builder.CACHE_WARNING='内置第151版性能资源；场景隐藏后停止后台模型检查，保留任务实时刷新和原版结算动画。'

if __name__=='__main__':
    release=json.loads((PROJECT/'验收/运行性能/发布.json').read_text(encoding='utf-8'))['release']
    assert release.startswith('151-')
    builder.build(release)
