"""Expose the pure initialization observation in release-device logs."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import UnityPy

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'android-client'),str(PROJECT/'deploy'),r'D:\Environment\VPS-SSH\packages313']
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
import publish_settlement_runtime_v51_vps as update

ROOT=PROJECT/'热更新测试/主线热更候选'
AUDIT=PROJECT/'验收/战斗效果修复'
REPORT=AUDIT/'诊断发布.json'
APK=PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'
BASE='159-659e485ee2ada34ef741d1d013a5df65032079d60842edc93f7710aa490726ae'
LOGICAL='assetbundle/lua/lua.ab'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def build():
    assert (ROOT/'current').read_text(encoding='utf-8').strip()==BASE
    folder=ROOT/'releases'/BASE;body=(folder/'manifest.json').read_bytes()
    with zipfile.ZipFile(APK) as z: public=update.serialization.load_der_public_key(z.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),body,update.padding.PKCS1v15(),update.hashes.SHA256())
    private=update.serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    original=json.loads(body);previous=next(a for a in original['assets'] if a['path']==LOGICAL)
    env=UnityPy.load((ROOT/'blobs'/previous['sha256']).read_bytes())
    before={o.path_id:sha(o.get_raw_data()) for o in env.objects}
    obj,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree=obj.read_typetree();script=tree['m_Script']
    old="local function log(text) UnityEngine.Debug.Log('WWR_EFFECT_READY '..text) end"
    new="local function log(text) UnityEngine.Debug.LogWarning('WWR_EFFECT_READY '..text) end"
    assert script.count(old)==1 and new not in script
    script=script.replace(old,new);check_lua(script);tree['m_Script']=script;obj.save_typetree(tree)
    raw=env.file.save(packer='original');after={o.path_id:sha(o.get_raw_data()) for o in UnityPy.load(raw).objects}
    assert {p for p in before if before[p]!=after[p]}=={obj.path_id}
    blob=ROOT/'blobs'/sha(raw)
    if blob.exists(): assert blob.read_bytes()==raw
    else: blob.write_bytes(raw)
    asset=dict(path=LOGICAL,url='/updates/stable/blobs/'+sha(raw),size=len(raw),sha256=sha(raw))
    revised=copy.deepcopy(original);revised['assets']=[asset if a['path']==LOGICAL else a for a in original['assets']]
    release=signed_release(revised,161,private,public);rollback=signed_release(original,162,private,public)
    for name,data,sig in (release,rollback):
        dest=ROOT/'releases'/name;dest.mkdir();(dest/'manifest.json').write_bytes(data);(dest/'manifest.sig').write_bytes(sig)
    REPORT.write_text(json.dumps(dict(base=BASE,release=release[0],rollback=rollback[0],changedAssets={LOGICAL:asset},status='SIGNED'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT_READY_DIAGNOSTIC_SIGNED',release[0])

def deploy(mode):
    record=json.loads(REPORT.read_text(encoding='utf-8'))
    update.OLD,update.NEW,update.ROLLBACK=record['base'],record['release'],record['rollback']
    update.PATCH_ASSETS=record['changedAssets'];update.APK=APK
    update.BACKUP=update.base.CURRENT+'.before-combat-ready-v161'
    def inventory():
        with zipfile.ZipFile(APK) as z: public=update.serialization.load_der_public_key(z.read('assets/update_public_key.der'))
        data={}
        for name in (update.OLD,update.NEW,update.ROLLBACK):
            folder=ROOT/'releases'/name;raw=(folder/'manifest.json').read_bytes();assert sha(raw)==name.split('-',1)[1]
            public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,update.padding.PKCS1v15(),update.hashes.SHA256())
            data[name]={a['path']:a for a in json.loads(raw)['assets']}
        assert len(data[update.OLD])==len(data[update.NEW])==118
        assert data[update.ROLLBACK]==data[update.OLD]
        assert {p for p in data[update.OLD] if data[update.OLD][p]!=data[update.NEW][p]}=={LOGICAL}
    update.inventory=inventory
    client=update.base.connect(Path(r'E:\Desktop\密码.txt'))
    try:
        if mode=='stage': update.stage(client)
        else:
            update.activate(client);update.verify(client)
            (ROOT/'current').write_text(update.NEW+'\n',encoding='utf-8')
            record['status']='DEPLOYED_AND_HEALTHY';REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    finally:client.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('build','stage','activate'));args=p.parse_args()
    if args.mode=='build': build()
    else: deploy(args.mode)
