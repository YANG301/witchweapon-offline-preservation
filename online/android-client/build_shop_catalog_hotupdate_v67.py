"""Restore original exchange tiers and native batch controls on signed release 65."""
import base64
import copy
import json
from pathlib import Path
import sys
import zipfile
import UnityPy
import build_task_live_hotupdate_v57 as common
import build_settlement_levelup_hotupdate as signing
from patch_exchange_shop_tables import patch_shop_level_bundle

ROOT=common.ROOT
BASE='65-945ab5e17969959c8800f4bda09a4a680c6f1f6f5213cb80c81ece69671e9da9'
LUA='assetbundle/lua/lua.ab'
SHOP='assetbundle/config/clientexel/shop.ab'
ORIGINAL=Path(r'D:\Project\魔女兵器工程恢复\原版\Android工程\assets\assetbundle\config\clientexel\shop.ab')
PRESENTATION=common.PROJECT/'android-client/lua/init-shop-presentation-local.lua'
BATCH=common.PROJECT/'android-client/lua/init-shop-batch-quantity.lua'

def patch_lua(raw):
    env=UnityPy.load(raw)
    before={o.path_id:common.sha(o.get_raw_data()) for o in env.objects}
    targets=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    assert len(targets)==1
    target=targets[0];tree=target.read_typetree();original=tree['m_Script']
    proposed=PRESENTATION.read_text(encoding='utf-8').rstrip('\n')
    old=proposed.replace("(setID == '47000005' and innerSet == '44000002')",
        "(setID == '47000005' and innerSet == '44000002') or\n            (setID == '47000024' and innerSet == '44000016')")
    assert original.count(old)==1 and 'ONLINE_SHOP_BATCH' not in original
    changed=original.replace(old,proposed)+'\n\n'+BATCH.read_text(encoding='utf-8')
    common.check_syntax(changed)
    tree['m_Script']=changed;target.save_typetree(tree)
    result=env.file.save(packer='original');after=UnityPy.load(result)
    after_hash={o.path_id:common.sha(o.get_raw_data()) for o in after.objects}
    assert set(before)==set(after_hash)
    assert {p for p in before if before[p]!=after_hash[p]}=={target.path_id}
    actual=next(o for o in after.objects if o.path_id==target.path_id).read_typetree()['m_Script']
    assert actual==changed
    for marker in ('ONLINE_TASK_LIVE_READY 65','ONLINE_FURNACE_SELECTION_GATE',
                   'ONLINE_GUILD_RECALL_REWARD','ONLINE_MAINLINE_ODD_OPEN','ONLINE_SHOP_BATCH_READY 67'):
        assert marker in actual,marker
    return result

def main():
    folder=ROOT/'releases'/BASE;raw=(folder/'manifest.json').read_bytes()
    assert common.sha(raw)==BASE.split('-',1)[1]
    manifest=json.loads(raw);assert manifest['releaseSequence']==65 and len(manifest['assets'])==74
    old={a['path']:a for a in manifest['assets']}
    def blob(path):
        a=old[path];data=(ROOT/'blobs'/a['sha256']).read_bytes()
        assert common.sha(data)==a['sha256'] and len(data)==a['size'];return data
    replacements={LUA:patch_lua(blob(LUA)),SHOP:patch_shop_level_bundle(blob(SHOP),ORIGINAL.read_bytes())}
    assert all(replacements[p]!=blob(p) for p in replacements)
    assert patch_shop_level_bundle(replacements[SHOP],ORIGINAL.read_bytes())==replacements[SHOP]
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(signing.APK) as apk:
        public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    changed=copy.deepcopy(manifest)
    for path,payload in replacements.items():
        digest=common.sha(payload)
        next(a for a in changed['assets'] if a['path']==path).update(
            url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    fix=signing.signed_release(changed,67,private,public)
    rollback=signing.signed_release(manifest,68,private,public)
    for name,_,_ in (fix,rollback):assert not (ROOT/'releases'/name).exists(),'Immutable release exists'
    for payload in replacements.values():
        path=ROOT/'blobs'/common.sha(payload)
        if path.exists():assert path.read_bytes()==payload
        else:path.write_bytes(payload)
    for name,m,s in (fix,rollback):
        directory=ROOT/'releases'/name;directory.mkdir()
        (directory/'manifest.json').write_bytes(m);(directory/'manifest.sig').write_bytes(s)
    print('SHOP_CATALOG_RELEASE_READY',fix[0],rollback[0],flush=True)
    print(json.dumps([a for a in changed['assets'] if a['path'] in replacements],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
