"""Finalize native maze group boundaries and bounded combat observations."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sys
import zipfile
import UnityPy

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'android-client'),str(PROJECT/'deploy'),r'D:\Environment\VPS-SSH\packages313']
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
import publish_settlement_runtime_v51_vps as update
import deploy_task_stage_progress_vps as server
ROOT=PROJECT/'热更新测试/主线热更候选'
AUDIT=PROJECT/'验收/战斗效果修复'
REPORT=AUDIT/'后续发布.json'
APK=PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'
BASE='161-77b07c4283be08fa5b1b63207a2eff640f9d09c035ab7fd221daf00c865c7280'
OLD_JAR='5b19a60a933e788c0fc9a24f6c2eaf6c60fa6b3e846c4c1d5c40cb3f01b0e7b8'
LIVE='/opt/witchweapon-legacy/witchweapon-legacy.jar'
NEXT='.maze-group-v163-next'
BACKUP='.before-maze-group-v163'
SNAPSHOT='/var/lib/witchweapon-legacy/data-before-maze-group-v163.tar.gz'
LOGICAL='assetbundle/lua/lua.ab'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def public_key():
    with zipfile.ZipFile(APK) as z:return update.serialization.load_der_public_key(z.read('assets/update_public_key.der'))

def build(jar):
    assert (ROOT/'current').read_text(encoding='utf-8').strip()==BASE
    previous_jar=PROJECT/'验收/迷宫修复/witchweapon-maze-candidate.jar'
    assert sha(previous_jar.read_bytes())==OLD_JAR
    with zipfile.ZipFile(previous_jar) as old,zipfile.ZipFile(jar) as new:
        assert set(old.namelist())==set(new.namelist())
        changed={p for p in old.namelist() if old.read(p)!=new.read(p)}
        allowed={'com/codex/witchweapon/BarrierLabyrinth.class','com/codex/witchweapon/BarrierLabyrinth$Group.class','com/codex/witchweapon/LocalSave.class'}
        assert changed and changed.issubset(allowed),changed
    folder=ROOT/'releases'/BASE;body=(folder/'manifest.json').read_bytes();public=public_key()
    assert sha(body)==BASE.split('-',1)[1]
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),body,update.padding.PKCS1v15(),update.hashes.SHA256())
    original=json.loads(body);asset=next(a for a in original['assets'] if a['path']==LOGICAL)
    env=UnityPy.load((ROOT/'blobs'/asset['sha256']).read_bytes());before={o.path_id:sha(o.get_raw_data()) for o in env.objects}
    obj,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree=obj.read_typetree();script=tree['m_Script']
    anchor='-- Observe the original initialization once per hero. Diagnostics only.'
    assert script.count(anchor)==1
    start=script.index(anchor);prefix=script[:start]
    runtime=(PROJECT/'android-client/lua/init-combat-effect-ready.lua').read_text(encoding='utf-8').rstrip()
    assert sha((PROJECT/'android-client/lua/init-combat-effect-ready.lua').read_bytes())=='5114c945670cff51499aa48fb71d95d1dc43d7a071347b4102698c41b8612943'
    script=prefix+runtime+'\n';check_lua(script);tree['m_Script']=script;obj.save_typetree(tree)
    raw=env.file.save(packer='original');after={o.path_id:sha(o.get_raw_data()) for o in UnityPy.load(raw).objects}
    assert {p for p in before if before[p]!=after[p]}=={obj.path_id}
    blob=ROOT/'blobs'/sha(raw)
    if blob.exists():assert blob.read_bytes()==raw
    else:blob.write_bytes(raw)
    asset=dict(path=LOGICAL,url='/updates/stable/blobs/'+sha(raw),size=len(raw),sha256=sha(raw))
    revised=copy.deepcopy(original);revised['assets']=[asset if a['path']==LOGICAL else a for a in original['assets']]
    private=update.serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    release=signed_release(revised,163,private,public);rollback=signed_release(original,164,private,public)
    for name,data,sig in (release,rollback):
        dest=ROOT/'releases'/name;dest.mkdir();(dest/'manifest.json').write_bytes(data);(dest/'manifest.sig').write_bytes(sig)
    REPORT.write_text(json.dumps(dict(base=BASE,release=release[0],rollback=rollback[0],changedAssets={LOGICAL:asset},
        jar=str(jar.resolve()),jarSha256=sha(jar.read_bytes()),baseJarSha256=OLD_JAR,changedClasses=sorted(changed),status='SIGNED'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT_FOLLOWUP_SIGNED',release[0])

def configure(record):
    update.OLD,update.NEW,update.ROLLBACK=record['base'],record['release'],record['rollback']
    update.PATCH_ASSETS=record['changedAssets'];update.APK=APK;update.BACKUP=update.base.CURRENT+BACKUP
    def inventory():
        data={};public=public_key()
        for name in (update.OLD,update.NEW,update.ROLLBACK):
            folder=ROOT/'releases'/name;raw=(folder/'manifest.json').read_bytes();assert sha(raw)==name.split('-',1)[1]
            public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,update.padding.PKCS1v15(),update.hashes.SHA256())
            data[name]={a['path']:a for a in json.loads(raw)['assets']}
        assert len(data[update.OLD])==len(data[update.NEW])==118 and data[update.ROLLBACK]==data[update.OLD]
        assert {p for p in data[update.OLD] if data[update.OLD][p]!=data[update.NEW][p]}=={LOGICAL}
        assert sha(Path(record['jar']).read_bytes())==record['jarSha256']
    update.inventory=inventory

def deploy(mode):
    record=json.loads(REPORT.read_text(encoding='utf-8'));configure(record);update.inventory()
    client=update.base.connect(Path(r'E:\Desktop\密码.txt'))
    try:
        assert update.live(client)==(BASE,161)
        assert update.base.remote_sha(client,LIVE)==OLD_JAR
        if mode=='stage':
            assert not update.base.exists(client,LIVE+NEXT) and not update.base.exists(client,LIVE+BACKUP)
            with client.open_sftp() as sftp:update.base.put_checked(client,sftp,Path(record['jar']),LIVE+NEXT)
            update.stage(client)
        else:
            update.base.health(client);update.ready(client)
            assert update.base.remote_sha(client,LIVE+NEXT)==record['jarSha256']
            assert not update.base.exists(client,LIVE+BACKUP) and not update.base.exists(client,SNAPSHOT)
            other=server.other_state(client)
            update.base.run(client,'cp -p -- '+LIVE+' '+LIVE+BACKUP)
            try:
                update.base.run(client,'systemctl stop witchweapon-legacy.service')
                before=server.save_fingerprint(client)
                update.base.run(client,'tar -C /var/lib/witchweapon-legacy -czf '+SNAPSHOT+' data',timeout=60)
                update.base.run(client,'mv -T -- '+LIVE+NEXT+' '+LIVE)
                assert update.base.remote_sha(client,LIVE)==record['jarSha256'] and server.save_fingerprint(client)==before
                update.base.run(client,'systemctl start witchweapon-legacy.service');server.await_health(client,19877)
                assert server.other_state(client)==other
                update.activate(client);update.verify(client)
            except Exception:
                if update.live(client)[0]==update.NEW:update.base.pointer(client,update.ROLLBACK)
                update.base.run(client,'systemctl stop witchweapon-legacy.service')
                update.base.run(client,'cp -p -- '+LIVE+BACKUP+' '+LIVE)
                update.base.run(client,'systemctl start witchweapon-legacy.service');server.await_health(client,19877)
                raise
            (ROOT/'current').write_text(update.NEW+'\n',encoding='utf-8')
            record.update(status='DEPLOYED_AND_HEALTHY',playerSaveSnapshot=SNAPSHOT,playerSavesUntouched=True)
            REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            mainpath=AUDIT/'发布.json';main=json.loads(mainpath.read_text(encoding='utf-8'))
            main.update(finalRelease=update.NEW,finalServerJar=str(record['jar']),finalServerJarSha256=record['jarSha256'])
            mainpath.write_text(json.dumps(main,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print('COMBAT_FOLLOWUP_DEPLOYED_AND_HEALTHY')
    finally:client.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('build','stage','activate'));p.add_argument('--jar',type=Path);args=p.parse_args()
    if args.mode=='build':assert args.jar;build(args.jar)
    else:deploy(args.mode)
