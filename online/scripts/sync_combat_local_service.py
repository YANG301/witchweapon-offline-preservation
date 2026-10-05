"""Mirror only the furnace classes and one role response into the PC service."""
import copy
import hashlib
import json
import shutil
import socket
import sys
import zipfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'android-client'))
from build_online_apk import copy_compressed_entry

LOCAL = Path(r'D:\Project\魔女兵器工程恢复\本地模式服务\程序')
JAR = LOCAL / 'witchweapon-legacy.jar'
SEED = LOCAL / 'offline_responses.json'
BASE = 'ffbea6f405e1758b83b035699fc52e7d871469c465717bd234b5dd0a97ad7ef9'
SCOPE = {'com/codex/witchweapon/WeaponFurnace.class',
         'com/codex/witchweapon/WeaponFurnace$Settlement.class'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    assert sha(JAR.read_bytes()) == BASE
    for port in (19876, 19180, 19896, 19181):
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0, 'Local service still running'
    report = json.loads((PROJECT / '验收/战斗修复/发布.json').read_text(encoding='utf-8'))
    source = json.loads(SEED.read_text(encoding='utf-8-sig'))
    revised = json.loads(Path(report['fixture']).read_text(encoding='utf-8'))
    source['/combat/role/info'] = revised['/combat/role/info']
    seed = (json.dumps(source, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    candidate = PROJECT / '构建/战斗修复/witchweapon-local-legacy.jar'
    assert not candidate.exists()
    with zipfile.ZipFile(JAR) as old, zipfile.ZipFile(PROJECT / '构建/战斗修复/witchweapon-legacy.jar') as online:
        assert SCOPE.issubset(old.namelist())
        with zipfile.ZipFile(candidate, 'x') as new:
            for entry in old.infolist():
                if entry.filename in SCOPE:
                    new.writestr(copy.copy(entry), online.read(entry.filename))
                else:
                    copy_compressed_entry(old, new, entry)
    with zipfile.ZipFile(JAR) as old, zipfile.ZipFile(candidate) as new:
        assert set(old.namelist()) == set(new.namelist())
        assert {p for p in old.namelist() if old.read(p) != new.read(p)} == SCOPE
    backup = PROJECT / '验收/战斗修复/本地服务回退'
    backup.mkdir()
    for path in (JAR, SEED):
        shutil.copyfile(path, backup / path.name)
        assert (backup / path.name).read_bytes() == path.read_bytes()
    shutil.copyfile(candidate, JAR)
    SEED.write_bytes(seed)
    assert JAR.read_bytes() == candidate.read_bytes()
    assert SEED.read_bytes() == seed
    report['localServiceSync'] = dict(jarSha256=sha(JAR.read_bytes()), fixtureSha256=sha(seed),
                                    onlyTwoFurnaceClassesChanged=True, playerDataUntouched=True,
                                    rollback=str(backup), serviceWasStopped=True)
    (PROJECT / '验收/战斗修复/发布.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('LOCAL_COMBAT_SERVICE_SYNCED; account data unchanged', flush=True)


if __name__ == '__main__':
    main()
