"""Restore native star tabs and balance without touching other published assets."""
import base64
import copy
import json
import sys
import zipfile
import UnityPy
import build_shop_catalog_hotupdate_v67 as previous
common=previous.common
signing=previous.signing
ROOT=previous.ROOT
BASE='77-cc2fc6d7adcf1f56374c8e31026af14190d941a1f8f8948406a4ea19aa316675'

def main(sequence=79,rollback_base=None):
    folder=ROOT/'releases'/BASE;raw=(folder/'manifest.json').read_bytes()
    assert common.sha(raw)==BASE.split('-',1)[1]
    manifest=json.loads(raw);asset=next(a for a in manifest['assets'] if a['path']==previous.LUA)
    blob=(ROOT/'blobs'/asset['sha256']).read_bytes();assert common.sha(blob)==asset['sha256']
    env=UnityPy.load(blob);before={o.path_id:common.sha(o.get_raw_data()) for o in env.objects}
    target,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree=target.read_typetree();original=tree['m_Script']
    begin='-- Local test client only. This block is appended to the already-running'
    tail="        UnityEngine.Debug.LogError('LOCAL_SHOP_PRESENTATION init_error ' .. tostring(err))\n    end\nend"
    assert original.count(begin)==1 and original.count(tail)==1
    start=original.index(begin);end=original.index(tail,start)+len(tail)
    old=original[start:end];assert 'hiddenSubTabs[path]' in old and 'ONLINE_SHOP_BATCH_READY 77' not in old
    replacement=previous.PRESENTATION.read_text(encoding='utf-8').rstrip('\n')
    assert 'star_ready '+str(sequence) in replacement
    changed=original[:start]+replacement+original[end:]
    assert original[:start]==changed[:start] and changed[start+len(replacement):]==original[end:]
    common.check_syntax(changed);tree['m_Script']=changed;target.save_typetree(tree)
    payload=env.file.save(packer='original');after=UnityPy.load(payload)
    hashes_after={o.path_id:common.sha(o.get_raw_data()) for o in after.objects}
    assert set(before)==set(hashes_after)
    assert {p for p in before if before[p]!=hashes_after[p]}=={target.path_id}
    assert next(o for o in after.objects if o.path_id==target.path_id).read_typetree()['m_Script']==changed
    for marker in ('ONLINE_TASK_LIVE_READY 65','ONLINE_FURNACE_SELECTION_GATE',
                   'ONLINE_GUILD_RECALL_REWARD','ONLINE_MAINLINE_ODD_OPEN','ONLINE_SHOP_BATCH_READY 77'):
        assert marker in changed,marker
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(signing.APK) as apk:public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    snapshot=copy.deepcopy(manifest);digest=common.sha(payload)
    next(a for a in snapshot['assets'] if a['path']==previous.LUA).update(url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    rollback_manifest=manifest
    if rollback_base is not None:
        rollback_folder=ROOT/'releases'/rollback_base
        rollback_raw=(rollback_folder/'manifest.json').read_bytes()
        assert common.sha(rollback_raw)==rollback_base.split('-',1)[1]
        public.verify(base64.b64decode((rollback_folder/'manifest.sig').read_bytes()),rollback_raw,padding.PKCS1v15(),hashes.SHA256())
        rollback_manifest=json.loads(rollback_raw)
    fix=signing.signed_release(snapshot,sequence,private,public);rollback=signing.signed_release(rollback_manifest,sequence+1,private,public)
    for name,_,_ in (fix,rollback):assert not (ROOT/'releases'/name).exists()
    path=ROOT/'blobs'/digest
    if path.exists():assert path.read_bytes()==payload
    else:path.write_bytes(payload)
    for name,m,s in (fix,rollback):
        directory=ROOT/'releases'/name;directory.mkdir()
        (directory/'manifest.json').write_bytes(m);(directory/'manifest.sig').write_bytes(s)
    print('STAR_SHOP_READY',fix[0],rollback[0],digest,len(payload),flush=True)

if __name__=='__main__':main()
