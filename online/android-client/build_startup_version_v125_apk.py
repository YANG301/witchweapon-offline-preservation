"""Integrate release 191 and the verified APK asset reuse into the dual-zone APK."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
sys.path.insert(0, r'D:\Project\魔女兵器工程恢复\本地模式客户端')
import build_preserved_battle_v111_apk as builder
import build_server_list_v110_apk as dual
import patch_local_mode_bridge as bridge
from patch_embedded_asset_reuse import patch

builder.SOURCE = PROJECT/'构建/用户协议/魔女兵器-在线本地双区服-v124-测试.apk'
builder.SOURCE_SHA = '8243da865f1277bcc307d27ea28ff756b47214cbbc369f603873039eb9f31de9'
builder.SOURCE_VERSION_CODE, builder.TARGET_VERSION_CODE = 20043124, 20043125
builder.OUTPUT = PROJECT/'构建/启动版本检查修复/魔女兵器-在线本地双区服-v125-测试.apk'
builder.REPORT = builder.OUTPUT.with_suffix('.json')
builder.TEMP = Path(r'D:\Environment\Android\temp\witch-startup-v125-apk')
builder.SOURCE_SETTLEMENT_SHA = builder.PATCHED_SETTLEMENT_SHA
builder.CACHE_WARNING = '内置最新121项资源，首次启动复用签名核对后的APK资源；区服和账号功能保留。'
COMPILE = Path(r'D:\Environment\Android\temp\witch-startup-v125-java')

def compile_dex():
    adapter, updater = builder.adapter, builder.updater
    if COMPILE.exists(): raise FileExistsError(COMPILE)
    with zipfile.ZipFile(builder.SOURCE) as apk:
        old_classes = set(adapter.dex_classes(apk.read('classes2.dex')))
    adapter.TEMP = COMPILE
    sources = updater._compile_sources(COMPILE, baseline=False, mode='production')
    app = sources[0]
    app.write_text(updater.inherited_application(dual.integrated_app(
        bridge.ONLINE_APPLICATION.read_bytes()).decode('utf-8')), encoding='utf-8')
    original = HERE/'src/com/codex/witchweapon/AssetUpdateManager.java'
    modified = app.with_name('AssetUpdateManager.java')
    modified.write_bytes(patch(dual.integrated_updater(original.read_bytes())))
    sources[sources.index(original)] = modified
    sources.extend([bridge.LOCAL_BRIDGE, HERE/'src/com/codex/witchweapon/SignedAssetReuse.java'])
    dex, classes = adapter.compile_dex(sources, old_classes)
    if set(classes) != old_classes | {'Lcom/codex/witchweapon/SignedAssetReuse;'}:
        raise ValueError('Dual-zone helper class inventory changed unexpectedly')
    return dex

def main():
    record = json.loads((PROJECT/'验收/公告图文与正式协议最终热更新.json').read_text(encoding='utf-8'))
    report = builder.build(record['release'], helper_dex=compile_dex())
    report['coldInstallAssetReuse'] = True
    report['versionCheckNetworkBudgetSeconds'] = 20
    builder.REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

if __name__ == '__main__': main()
