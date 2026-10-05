"""Sync only the three reviewed draw classes to the stopped local-mode server."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'验收/抽卡与升星修复'
LIVE=Path(r'D:\Project\魔女兵器工程恢复\本地模式服务\程序\witchweapon-legacy.jar')
BASE_SHA='59ed0ef6cd1bb9dacc58b8637b75d4b3ff9f5363a8d6770f2c5a69172f94bda1'
SOURCE=ROOT/'legacy-server/build/witchweapon-legacy-draw-persistence.jar'
CANDIDATE=ROOT/'legacy-server/build/witchweapon-local-draw-persistence.jar'
SCOPE={'com/codex/witchweapon/'+name+'.class' for name in ('LocalEconomy','PrayerShop','NormalDrawRates')}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    assert sha(LIVE)==BASE_SHA and not CANDIDATE.exists()
    release=json.loads((EVIDENCE/'发布与恢复结果.json').read_text(encoding='utf-8'))
    assert release['candidateSha256']==sha(SOURCE)
    for port in (19876,19180,19896,19181):
        with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',port))!=0,'Local service still running'
    with zipfile.ZipFile(LIVE) as old,zipfile.ZipFile(SOURCE) as online,zipfile.ZipFile(EVIDENCE/'正式基线.jar') as baseline:
        assert all(old.read(n)==baseline.read(n) for n in SCOPE)
        assert old.read('prayer_shop_catalog.json')==online.read('prayer_shop_catalog.json')
        with zipfile.ZipFile(CANDIDATE,'x') as new:
            for entry in old.infolist():new.writestr(entry,online.read(entry.filename) if entry.filename in SCOPE else old.read(entry))
    with zipfile.ZipFile(LIVE) as old,zipfile.ZipFile(CANDIDATE) as new:
        assert set(old.namelist())==set(new.namelist())
        assert {n for n in old.namelist() if old.read(n)!=new.read(n)}==SCOPE
    temp=Path(r'D:\Environment\Java\temp\witch-draw-persistence')
    cp=os.pathsep.join(map(str,(CANDIDATE,temp/'classes',Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'))))
    result=subprocess.run([r'D:\Environment\Java\jdk8\bin\java.exe','-Dfile.encoding=UTF-8','-cp',cp,
        'com.codex.witchweapon.DrawPersistenceSelfTest',str(EVIDENCE/'正式基线响应.json'),
        str(ROOT/'legacy-server/resources/prayer_shop_catalog.json'),str(temp/'save-local')],
        capture_output=True,text=True,encoding='utf-8',errors='replace',env=dict(os.environ,TEMP=str(temp),TMP=str(temp)))
    assert result.returncode==0,result.stdout+result.stderr
    print(result.stdout.strip(),flush=True)
    backup=EVIDENCE/'本地服务回退.jar';assert not backup.exists()
    shutil.copyfile(LIVE,backup);assert sha(backup)==BASE_SHA
    stage=LIVE.with_suffix('.draw-next.jar');assert not stage.exists()
    shutil.copyfile(CANDIDATE,stage);os.replace(stage,LIVE);assert sha(LIVE)==sha(CANDIDATE)
    release['localServiceSync']={'sha256':sha(LIVE),'changedClasses':sorted(SCOPE),'playerDataUntouched':True,'rollback':str(backup)}
    (EVIDENCE/'发布与恢复结果.json').write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('LOCAL_DRAW_CLASSES_SYNCED; no local player data or activity data changed',flush=True)

if __name__=='__main__':main()
