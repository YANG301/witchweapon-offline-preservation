"""Include the community contract and notice in the next full APK integration."""
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, r'D:\Project\魔女兵器工程恢复\本地模式客户端')
import build_preserved_battle_v111_apk as builder

PROJECT = Path(__file__).resolve().parents[1]
builder.SOURCE = PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
builder.SOURCE_SHA = '77af6df1b6f6ad5b25be722f35b9d41a21b33069ce6061b5f8f00a2ac0aa5839'
builder.SOURCE_VERSION_CODE, builder.TARGET_VERSION_CODE = 20043123, 20043124
builder.OUTPUT = PROJECT/'构建/用户协议/魔女兵器-在线本地双区服-v124-测试.apk'
builder.REPORT = builder.OUTPUT.with_suffix('.json')
builder.TEMP = Path(r'D:\Environment\Android\temp\witch-community-agreement-v124')
builder.SOURCE_SETTLEMENT_SHA = builder.PATCHED_SETTLEMENT_SHA
builder.CACHE_WARNING = '内置最新公告、用户协议及邮箱找回功能；保留区服登录资源和已有玩法修复。'


def main(check=False):
    record = json.loads((PROJECT/'验收/公告图文与正式协议最终热更新.json').read_text(encoding='utf-8'))
    assert int(record['release'].split('-', 1)[0]) >= 175
    with zipfile.ZipFile(builder.SOURCE) as apk:
        fixture = json.loads(apk.read('assets/offline_responses.json'))
    online = json.loads((PROJECT/'legacy-server/resources/offline_responses.json').read_text(encoding='utf-8'))
    fixture['/Notice/gameContent'] = online['/Notice/gameContent']
    return builder.build(record['release'],check,
        extra_members={'assets/offline_responses.json':
            (json.dumps(fixture,ensure_ascii=False,indent=2)+'\n').encode('utf-8')},
        extra_fixture_routes=frozenset({'/Notice/gameContent'}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    main(parser.parse_args().check)
