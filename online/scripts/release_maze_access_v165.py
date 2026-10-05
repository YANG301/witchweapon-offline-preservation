"""Remove the one remaining maze witch-level gate through a signed config update."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'android-client'),str(PROJECT/'deploy'),r'D:\Environment\VPS-SSH\packages313']
from build_settlement_levelup_hotupdate import signed_release
from patch_maze_servant_level_gate import patch_bundle
import publish_settlement_runtime_v51_vps as update

ROOT=PROJECT/'热更新测试/主线热更候选'
REPORT=PROJECT/'验收/战斗效果修复/准入发布.json'
APK=PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'
BASE='163-9d65f77bf78e9667e14e0834a8129993b913dade00473af0327896b62d97b54c'
CONSTANT=PROJECT/'验收/迷宫修复/低等级准入/Constant.ab'
LOGICAL='assetbundle/config/clientexel/constant.ab'
BASE_CONSTANT_SHA='8ea1ae95071c46e7d224d87ba0ae9442641e3c10f52dc2ca3b8258c4636dd878'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def public_key():
    with zipfile.ZipFile(APK) as z:return update.serialization.load_der_public_key(z.read('assets/update_public_key.der'))
def build():
    assert (ROOT/'current').read_text(encoding='utf-8').strip()==BASE
    folder=ROOT/'releases'/BASE;body=(folder/'manifest.json').read_bytes();public=public_key()
    assert sha(body)==BASE.split('-',1)[1]
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),body,update.padding.PKCS1v15(),update.hashes.SHA256())
    original=json.loads(body)
    assert len(original['assets'])==118 and LOGICAL not in {a['path'] for a in original['assets']}
    with zipfile.ZipFile(APK) as z:previous=z.read('assets/'+LOGICAL)
    assert sha(previous)==BASE_CONSTANT_SHA
    base_asset=dict(path=LOGICAL,url='/updates/stable/blobs/'+BASE_CONSTANT_SHA,size=len(previous),sha256=BASE_CONSTANT_SHA)
    base_blob=ROOT/'blobs'/BASE_CONSTANT_SHA
    if base_blob.exists():assert base_blob.read_bytes()==previous
    else:base_blob.write_bytes(previous)
    raw=CONSTANT.read_bytes()
    assert raw==patch_bundle(previous), 'The candidate must equal the exact single-row patch'
    blob=ROOT/'blobs'/sha(raw)
    if blob.exists():assert blob.read_bytes()==raw
    else:blob.write_bytes(raw)
    asset=dict(path=LOGICAL,url='/updates/stable/blobs/'+sha(raw),size=len(raw),sha256=sha(raw))
    revised=copy.deepcopy(original);revised['assets'].append(asset)
    restored=copy.deepcopy(original);restored['assets'].append(base_asset)
    private=update.serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    release=signed_release(revised,165,private,public);rollback=signed_release(restored,166,private,public)
    for name,data,sig in (release,rollback):
        dest=ROOT/'releases'/name;dest.mkdir();(dest/'manifest.json').write_bytes(data);(dest/'manifest.sig').write_bytes(sig)
    REPORT.write_text(json.dumps(dict(base=BASE,release=release[0],rollback=rollback[0],
        changedAssets={LOGICAL:asset},rollbackBaseAsset=base_asset,changedRow='CORE_INSTANCE_SERVANT_MIN_LEVEL: 20 -> 1',
        ruleSource='用户要求取消功能等级限制',status='SIGNED'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('MAZE_ACCESS_RELEASE_SIGNED',release[0])

def deploy(mode):
    record=json.loads(REPORT.read_text(encoding='utf-8'))
    update.OLD,update.NEW,update.ROLLBACK=record['base'],record['release'],record['rollback']
    update.PATCH_ASSETS=record['changedAssets'];update.APK=APK
    update.BACKUP=update.base.CURRENT+'.before-maze-access-v165'
    def inventory():
        data={};public=public_key()
        for name in (update.OLD,update.NEW,update.ROLLBACK):
            folder=ROOT/'releases'/name;raw=(folder/'manifest.json').read_bytes();assert sha(raw)==name.split('-',1)[1]
            public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,update.padding.PKCS1v15(),update.hashes.SHA256())
            data[name]={a['path']:a for a in json.loads(raw)['assets']}
        old,new,rollback=data[update.OLD],data[update.NEW],data[update.ROLLBACK]
        assert len(old)==118 and len(new)==len(rollback)==119
        assert set(new)-set(old)=={LOGICAL} and set(rollback)-set(old)=={LOGICAL}
        assert all(old[p]==new[p]==rollback[p] for p in old)
        assert new[LOGICAL]==record['changedAssets'][LOGICAL] and rollback[LOGICAL]==record['rollbackBaseAsset']
    update.inventory=inventory
    client=update.base.connect(Path(r'E:\Desktop\密码.txt'))
    try:
        if mode=='stage':
            base_asset=record['rollbackBaseAsset'];digest=base_asset['sha256'];remote=update.base.BLOBS+'/'+digest
            if update.base.exists(client,remote):assert update.base.remote_sha(client,remote)==digest
            else:
                temporary=remote+'.maze-base-constant-next'
                assert not update.base.exists(client,temporary)
                with client.open_sftp() as sftp:update.base.put_checked(client,sftp,ROOT/'blobs'/digest,temporary)
                update.base.run(client,'mv -T -- '+temporary+' '+remote)
            update.stage(client)
        else:
            update.activate(client);update.verify(client)
            (ROOT/'current').write_text(update.NEW+'\n',encoding='utf-8')
            record['status']='DEPLOYED_AND_HEALTHY';REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            mainpath=PROJECT/'验收/战斗效果修复/发布.json';main=json.loads(mainpath.read_text(encoding='utf-8'))
            main['finalRelease']=update.NEW;mainpath.write_text(json.dumps(main,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:client.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('build','stage','activate'));args=p.parse_args()
    if args.mode=='build':build()
    else:deploy(args.mode)
