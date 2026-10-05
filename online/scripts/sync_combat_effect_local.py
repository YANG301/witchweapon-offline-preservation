"""Keep the reviewed weapon/maze changes in the stopped PC service and source seed."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
AUDIT = PROJECT / '验收/战斗效果修复'
LOCAL_ROOT = Path(r'D:\Project\魔女兵器工程恢复\本地模式服务')
LOCAL = LOCAL_ROOT / '程序'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def files_digest(folder):
    return {str(p.relative_to(folder)): sha(p.read_bytes())
            for p in folder.rglob('*') if p.is_file()}

def main():
    report_path = AUDIT / '发布.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['status'] == 'DEPLOYED_AND_HEALTHY'
    pc_report = json.loads((PROJECT / '验收/迷宫修复/本地模式回归结果.json').read_text(encoding='utf-8'))
    assert pc_report['result'] == 'MAZE_REPAIR_SELF_TEST_OK'
    assert not (LOCAL_ROOT / '运行状态.json').exists(), 'PC local service has active state'
    for port in (19876, 19180, 19896, 19181):
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0, 'PC service is running'
    jar, seed = LOCAL / 'witchweapon-legacy.jar', LOCAL / 'offline_responses.json'
    candidate = Path(pc_report['candidate'])
    assert sha(jar.read_bytes()) == pc_report['pcBaselineSha256']
    assert sha(candidate.read_bytes()) == pc_report['candidateSha256']
    with zipfile.ZipFile(jar) as old, zipfile.ZipFile(candidate) as new:
        assert set(old.namelist()).issubset(new.namelist())
        changed = {p for p in old.namelist() if old.read(p) != new.read(p)}
        added = set(new.namelist()) - set(old.namelist())
        assert changed | added == set(pc_report['changedMembers'])
    original = json.loads(seed.read_text(encoding='utf-8-sig'))
    revised = copy.deepcopy(original)
    online_seed = Path(report['fixture'])
    assert sha(online_seed.read_bytes()) == report['fixtureSha256']
    revised['/combat/role/info'] = json.loads(online_seed.read_text(encoding='utf-8'))['/combat/role/info']
    assert {k for k in original if original[k] != revised[k]} == {'/combat/role/info'}
    payload = (json.dumps(revised, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    canonical = PROJECT / 'legacy-server/resources/offline_responses.json'
    assert sha(canonical.read_bytes()) == report['baseFixtureSha256']
    player_files = files_digest(LOCAL_ROOT / '数据')
    backup = AUDIT / '本地服务回退'
    backup.mkdir()
    for path in (jar, seed):
        shutil.copyfile(path, backup / path.name)
        assert (backup / path.name).read_bytes() == path.read_bytes()
    try:
        shutil.copyfile(candidate, jar)
        seed.write_bytes(payload)
        canonical.write_bytes(online_seed.read_bytes())
        assert sha(jar.read_bytes()) == pc_report['candidateSha256']
        assert json.loads(seed.read_text(encoding='utf-8')) == revised
        assert sha(canonical.read_bytes()) == report['fixtureSha256']
        assert files_digest(LOCAL_ROOT / '数据') == player_files
    except Exception:
        for path in (jar, seed): shutil.copyfile(backup / path.name, path)
        raise
    report['localServiceSync'] = dict(jarSha256=sha(jar.read_bytes()),
        fixtureSha256=sha(payload), playerDataUntouched=True, serviceWasStopped=True,
        localAdminAndStartupPreserved=True, rollback=str(backup))
    report['canonicalFixtureSynced'] = True
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('COMBAT_EFFECT_LOCAL_AND_CANONICAL_SYNCED; player data unchanged')

if __name__ == '__main__': main()
