"""Mirror the reviewed combat change into the stopped PC local service."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import zipfile

sys.dont_write_bytecode=True
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'android-client'))
from build_online_apk import copy_compressed_entry
AUDIT=PROJECT/'验收/战斗全面核查'
LOCAL=Path(r'D:\Project\魔女兵器工程恢复\本地模式服务\程序')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    record=json.loads((AUDIT/'发布.json').read_text(encoding='utf-8'))
    assert record['status']=='DEPLOYED_AND_HEALTHY'
    jar,seed=LOCAL/'witchweapon-legacy.jar',LOCAL/'offline_responses.json'
    assert sha(jar.read_bytes())=='960bb2a3fc2af3c341c6da480566a6e0e1f20b51bf08978213bca9703e09c089'
    for port in (19876,19180,19896,19181):
        with socket.socket() as probe:assert probe.connect_ex(('127.0.0.1',port))!=0,'Local service still running'
    previous=json.loads(seed.read_text(encoding='utf-8-sig'))
    source=copy.deepcopy(previous)
    revised=json.loads(Path(record['fixture']).read_text(encoding='utf-8'))
    source['/combat/role/info']=revised['/combat/role/info']
    assert {k for k in source if source[k]!=previous[k]}=={'/combat/role/info'}
    payload=(json.dumps(source,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    result=AUDIT/'候选/witchweapon-local-legacy.jar'
    replacements=('com/codex/witchweapon/LocalEconomy.class','com/codex/witchweapon/OriginalCombatRules.class')
    with zipfile.ZipFile(jar) as old,zipfile.ZipFile(Path(record['jar'])) as online:
        with zipfile.ZipFile(PROJECT/'构建/战斗修复/witchweapon-legacy.jar') as baseline:
            assert old.read(replacements[0])==baseline.read(replacements[0])
        assert replacements[1] not in old.namelist()
        with zipfile.ZipFile(result,'x') as new:
            for entry in old.infolist():
                if entry.filename==replacements[0]:new.writestr(copy.copy(entry),online.read(entry.filename))
                else:copy_compressed_entry(old,new,entry)
            new.writestr(replacements[1],online.read(replacements[1]))
    with zipfile.ZipFile(jar) as old,zipfile.ZipFile(result) as new:
        assert {p for p in old.namelist() if old.read(p)!=new.read(p)}=={replacements[0]}
        assert set(new.namelist())-set(old.namelist())=={replacements[1]}
    backup=AUDIT/'本地服务回退';backup.mkdir()
    for path in (jar,seed):
        shutil.copyfile(path,backup/path.name)
        assert (backup/path.name).read_bytes()==path.read_bytes()
    shutil.copyfile(result,jar);seed.write_bytes(payload)
    assert jar.read_bytes()==result.read_bytes() and json.loads(seed.read_text(encoding='utf-8'))==source
    canonical=PROJECT/'legacy-server/resources/offline_responses.json'
    assert sha(canonical.read_bytes())==record['baseFixtureSha256']
    canonical.write_bytes(Path(record['fixture']).read_bytes())
    assert sha(canonical.read_bytes())==record['fixtureSha256']
    record['localServiceSync']=dict(jarSha256=sha(jar.read_bytes()),fixtureSha256=sha(payload),
        changes=list(replacements),playerDataUntouched=True,rollback=str(backup),serviceWasStopped=True)
    record['canonicalFixtureSynced']=True
    (AUDIT/'发布.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT_ALIGNMENT_LOCAL_AND_CANONICAL_SYNCED; player data untouched')


if __name__=='__main__':main()
