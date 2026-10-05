"""Sign a bounded UI lookup and pooled-task observer repair on the active release."""
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
REPORT=PROJECT/'验收/运行性能/发布.json'
APK=PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk'
SOURCES=PROJECT/'android-client/lua'

def swap_block(script,start,end,source):
    first=script.index(start);last=script.index(end,first) if end else len(script)
    return script[:first]+(SOURCES/source).read_text(encoding='utf-8').rstrip()+'\n\n'+script[last:]

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('version',type=int)
    version=parser.parse_args().version
    base_name=(ROOT/'current').read_text(encoding='utf-8').strip()
    assert version>int(base_name.split('-')[0])
    raw=(ROOT/'releases'/base_name/'manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==base_name.split('-',1)[1]
    with zipfile.ZipFile(APK) as apk:public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/base_name/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    base=json.loads(raw);updated=json.loads(raw);changed={}
    for logical,text_name in [('assetbundle/lua/lua.ab','init.lua'),('assetbundle/lua/lua_projx_patch.ab','TaskItemPatch.lua')]:
        asset=next(a for a in base['assets'] if a['path']==logical)
        env=UnityPy.load((ROOT/'blobs'/asset['sha256']).read_bytes())
        before={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
        obj,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')==text_name]
        tree=obj.read_typetree();old=tree['m_Script']
        if text_name=='init.lua':
            helper='-- Cache scene lookups used by our UI repairs, without replacing Unity\'s API.'
            marker='-- Original campaign UI restored; availability follows server progress.'
            if helper in old:
                first=old.index(helper);last=old.index(marker,first)
                old=old[:first]+old[last:]
            script=old.replace('UnityEngine.Object.FindObjectOfType(', '(WWRRuntimeUI or UnityEngine.Object).FindObjectOfType(')
            script=swap_block(script,'-- WWR optional entry visibility v1.',None,'init-optional-entry-visibility.lua')
            script=swap_block(script,'-- Local test client only.','-- Guild UI is created','init-shop-presentation-local.lua')
            script=swap_block(script,'-- Restore the original ShopItemInfo slider','-- Public settings identity','init-shop-batch-quantity.lua')
            script=swap_block(script,'-- Refresh every original task entry','-- The preserved ARM64 UserInfoHelper','init-task-live-refresh.lua')
            script=swap_block(script,marker,'-- Local test client only.','init-campaign-background.lua')
            script=swap_block(script,'-- Restore the original guild recall award panel','-- Require a visible weapon selection','init-guild-recall-reward.lua')
            index=script.index(marker)
            script=script[:index]+(SOURCES/'init-runtime-ui-probes.lua').read_text(encoding='utf-8')+'\n\n'+script[index:]
            assert 'ONLINE_TASK_LOOT_READY 139' in script and 'ONLINE_TASK_LIVE_READY 143' in script
        else:
            assert old.strip().startswith('-- Repaint the preserved quest row')
            script=(SOURCES/'TaskItemPatch-online-v6.lua').read_text(encoding='utf-8')
        check_lua(script)
        if script==old:continue
        tree['m_Script']=script;obj.save_typetree(tree);payload=env.file.save(packer='original')
        after={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in UnityPy.load(payload).objects}
        assert {p for p in before if before[p]!=after[p]}=={obj.path_id}
        sha=hashlib.sha256(payload).hexdigest();blob=ROOT/'blobs'/sha
        if blob.exists():assert blob.read_bytes()==payload
        else:blob.write_bytes(payload)
        changed[logical]={'path':logical,'url':'/updates/stable/blobs/'+sha,'size':len(payload),'sha256':sha}
    updated['assets']=[changed.get(a['path'],a) for a in base['assets']]
    assert len(updated['assets'])==117
    release=signed_release(updated,version,private,public);rollback=signed_release(base,version+1,private,public)
    for name,data,sig in (release,rollback):
        directory=ROOT/'releases'/name;directory.mkdir();(directory/'manifest.json').write_bytes(data);(directory/'manifest.sig').write_bytes(sig)
    previous=json.loads(REPORT.read_text(encoding='utf-8')) if REPORT.exists() else None
    report={'base':base_name,'release':release[0],'rollback':rollback[0],'changedAssets':changed,'status':'LOCAL_VALIDATED_CANDIDATE',
        'scope':['Bounded authored UI lookup cache','One task-row observer; hidden rows skipped; reflection handles reused','Cached guide renderer suppression','Shop exception backoff before expensive work'],
        'unchanged':['Server programs and player saves','Frame-rate limit, resolution, quality and combat','Task goals/rewards and native loot animation']}
    if previous:report['previousIteration']=previous
    REPORT.parent.mkdir(exist_ok=True);REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(release[0],flush=True)
if __name__=='__main__':main()
