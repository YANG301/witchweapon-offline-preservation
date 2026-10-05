"""Restart the original reward background from its opening rather than stale closing time."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import UnityPy
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'热更新测试/主线热更候选'
REPORT=PROJECT/'验收/任务系统完整修复/发布.json'
LOGICAL='assetbundle/lua/lua.ab'

def main():
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    report=json.loads(REPORT.read_text(encoding='utf-8'))
    base_name=report['clientFollowup']['release'];assert base_name.startswith('129-')
    raw=(ROOT/'releases'/base_name/'manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()==base_name.split('-',1)[1]
    with zipfile.ZipFile(PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk') as apk:
        public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/base_name/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    base=json.loads(raw);entry=next(a for a in base['assets'] if a['path']==LOGICAL)
    env=UnityPy.load((ROOT/'blobs'/entry['sha256']).read_bytes())
    target,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    before={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
    tree=target.read_typetree();old=tree['m_Script']
    stale="                local time = background:GetCurrentAnimatorStateInfo(0).normalizedTime\n                background:Play('box_' .. tostring(math.max(1, math.min(5, count(list)))), 0, time)"
    fixed="                -- OpenPanel may still expose the previous box_N_down state\n                -- (speed -4). Its normalizedTime is not this opening's progress.\n                background:Play('box_' .. tostring(math.max(1, math.min(5, count(list)))), 0, 0)"
    assert old.count(stale)==1 and old.count('ONLINE_TASK_LOOT_READY 127')==1
    script=old.replace(stale,fixed).replace('ONLINE_TASK_LOOT_READY 127','ONLINE_TASK_LOOT_READY 131')
    assert (PROJECT/'android-client/lua/init-task-loot-display.lua').read_text(encoding='utf-8').rstrip() in script
    assert 'ONLINE_TASK_LIVE_READY 129' in script and 'ONLINE_TASK_LOOT_READY 131' in script
    check_lua(script);tree['m_Script']=script;target.save_typetree(tree)
    payload=env.file.save(packer='original')
    after={o.path_id:hashlib.sha256(o.get_raw_data()).hexdigest() for o in UnityPy.load(payload).objects}
    assert {p for p in before if before[p]!=after[p]}=={target.path_id}
    digest=hashlib.sha256(payload).hexdigest();blob=ROOT/'blobs'/digest
    if blob.exists():assert blob.read_bytes()==payload
    else:blob.write_bytes(payload)
    asset=dict(path=LOGICAL,url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    changed=copy.deepcopy(base);changed['assets']=[asset if a['path']==LOGICAL else a for a in changed['assets']]
    release=signed_release(changed,131,private,public);rollback=signed_release(base,132,private,public)
    for name,data,signature in (release,rollback):
        folder=ROOT/'releases'/name;assert not folder.exists();folder.mkdir()
        (folder/'manifest.json').write_bytes(data);(folder/'manifest.sig').write_bytes(signature)
    report['clientPreviousFollowup']=report['clientFollowup']
    report['clientFollowup']=dict(base=base_name,release=release[0],rollback=rollback[0],changedAssets={LOGICAL:asset},status='LOCAL_VALIDATED_CANDIDATE')
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report['clientFollowup'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
