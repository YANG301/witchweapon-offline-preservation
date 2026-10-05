"""Replace only the original task-reward Lua module in the current signed release."""
import argparse,base64,hashlib,json,sys,zipfile
from pathlib import Path
import UnityPy
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'android-client'))
sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding
ROOT=PROJECT/'热更新测试/主线热更候选'
REPORT=PROJECT/'验收/任务系统完整修复/发布.json'
APK=PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk'
LOGICAL='assetbundle/lua/lua.ab'
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('version',type=int)
    v=parser.parse_args().version
    report=json.loads(REPORT.read_text(encoding='utf-8'));baseName=report['clientFollowup']['release']
    assert v>int(baseName.split('-')[0])
    raw=(ROOT/'releases'/baseName/'manifest.json').read_bytes();assert hashlib.sha256(raw).hexdigest()==baseName.split('-',1)[1]
    with zipfile.ZipFile(APK) as apk:public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/baseName/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    base=json.loads(raw);a=next(a for a in base['assets'] if a['path']==LOGICAL)
    env=UnityPy.load((ROOT/'blobs'/a['sha256']).read_bytes())
    before={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
    obj,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree=obj.read_typetree();old=tree['m_Script']
    start=old.index('-- The preserved ARM64 UserInfoHelper.LootToDrawResultData emits LootGuildInc')
    end=old.index('-- Restore the original ShopItemInfo slider after the offline',start)
    module=(PROJECT/'android-client/lua/init-task-loot-display.lua').read_text(encoding='utf-8').rstrip()
    assert 'ONLINE_TASK_LOOT_READY '+str(v) in module
    script=old[:start]+module+'\n\n'+old[end:];check_lua(script)
    assert 'ONLINE_TASK_LIVE_READY 129' in script
    tree['m_Script']=script;obj.save_typetree(tree);payload=env.file.save(packer='original')
    after={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in UnityPy.load(payload).objects}
    assert {p for p in before if before[p]!=after[p]}=={obj.path_id}
    sha=hashlib.sha256(payload).hexdigest();blob=ROOT/'blobs'/sha
    if blob.exists():assert blob.read_bytes()==payload
    else:blob.write_bytes(payload)
    changed=json.loads(raw);asset={'path':LOGICAL,'url':'/updates/stable/blobs/'+sha,'size':len(payload),'sha256':sha}
    changed['assets']=[asset if a['path']==LOGICAL else a for a in changed['assets']]
    release=signed_release(changed,v,private,public);rollback=signed_release(base,v+1,private,public)
    for name,data,sig in (release,rollback):
        folder=ROOT/'releases'/name;folder.mkdir();(folder/'manifest.json').write_bytes(data);(folder/'manifest.sig').write_bytes(sig)
    report.setdefault('clientHistory',[]).append(report['clientFollowup'])
    report['clientFollowup']={'base':baseName,'release':release[0],'rollback':rollback[0],'changedAssets':{LOGICAL:asset},'status':'LOCAL_VALIDATED_CANDIDATE'}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(release[0],flush=True)
if __name__=='__main__':main()
