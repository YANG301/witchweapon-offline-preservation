"""Apply the separately verified PC maze boundary fix without touching its saves."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import zipfile

PROJECT=Path(__file__).resolve().parents[1]
LOCAL=Path(r'D:\Project\魔女兵器工程恢复\本地模式服务')
AUDIT=PROJECT/'验收/战斗效果修复'
OLD='1a82a775014402780a5d3537cf8f7bbb925bc36623c50d8fd382dca3c579e1f7'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def fingerprint():
    return {str(p.relative_to(LOCAL/'数据')):sha(p.read_bytes())
            for p in (LOCAL/'数据').rglob('*') if p.is_file()}
def main():
    report_path=AUDIT/'发布.json';report=json.loads(report_path.read_text(encoding='utf-8'))
    assert report['finalRelease'].startswith('163-')
    entry=next(x for x in json.loads((PROJECT/'验收/迷宫修复/初次选组与四槽回归.json').read_text(encoding='utf-8')) if x['mode']=='PC')
    assert all(x['result'].endswith('SELF_TEST_OK') for x in entry['tests'])
    assert not (LOCAL/'运行状态.json').exists()
    for port in (19876,19180,19896,19181):
        with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',port))!=0,'PC local service is running'
    current=LOCAL/'程序/witchweapon-legacy.jar';candidate=Path(entry['jar'])
    assert sha(current.read_bytes())==OLD and sha(candidate.read_bytes())==entry['sha256']
    prior=PROJECT/'验收/迷宫修复/本地模式候选/witchweapon-legacy.jar'
    assert sha(prior.read_bytes())==OLD
    with zipfile.ZipFile(current) as old,zipfile.ZipFile(candidate) as new:
        assert set(old.namelist())==set(new.namelist())
        assert {p for p in old.namelist() if old.read(p)!=new.read(p)}=={
            'com/codex/witchweapon/BarrierLabyrinth.class','com/codex/witchweapon/LocalSave.class'}
    saves=fingerprint();seed=LOCAL/'程序/offline_responses.json';seed_sha=sha(seed.read_bytes())
    try:
        shutil.copyfile(candidate,current)
        assert sha(current.read_bytes())==entry['sha256']
        assert fingerprint()==saves and sha(seed.read_bytes())==seed_sha
    except Exception:
        shutil.copyfile(prior,current);raise
    report['localServiceSync'].update(finalJarSha256=entry['sha256'],fourCardMazeTeam=True,
        initialMazeGroupEmpty=True,previousCandidateRollback=str(prior))
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('MAZE_GROUP_PC_SYNCED; all player data and local administration preserved')
if __name__=='__main__':main()
