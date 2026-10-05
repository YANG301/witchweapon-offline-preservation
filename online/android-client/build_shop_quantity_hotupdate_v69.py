"""Use the exact native static-wrapper call for current shop quantity source."""
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
BASE='67-4f8423d05161b57924cf5460f7feb27fda9fd6fdce225eacfdf2ea9a93292ac2'
SEQUENCE=69
ROLLBACK_SEQUENCE=70
PREVIOUS_MARKER='ONLINE_SHOP_BATCH_READY 67'
ROLLBACK_BASE=None

def main():
    folder=ROOT/'releases'/BASE;raw=(folder/'manifest.json').read_bytes()
    assert common.sha(raw)==BASE.split('-',1)[1]
    manifest=json.loads(raw);asset=next(a for a in manifest['assets'] if a['path']==previous.LUA)
    blob=(ROOT/'blobs'/asset['sha256']).read_bytes();assert common.sha(blob)==asset['sha256']
    env=UnityPy.load(blob);before={o.path_id:common.sha(o.get_raw_data()) for o in env.objects}
    targets=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    assert len(targets)==1;target=targets[0];tree=target.read_typetree();original=tree['m_Script']
    marker='-- Restore the original ShopItemInfo slider after the offline author'
    assert original.count(marker)==1 and PREVIOUS_MARKER in original
    changed=original[:original.index(marker)]+previous.BATCH.read_text(encoding='utf-8')
    common.check_syntax(changed);tree['m_Script']=changed;target.save_typetree(tree)
    payload=env.file.save(packer='original');after=UnityPy.load(payload)
    hashes_after={o.path_id:common.sha(o.get_raw_data()) for o in after.objects}
    assert set(before)==set(hashes_after)
    assert {p for p in before if before[p]!=hashes_after[p]}=={target.path_id}
    assert next(o for o in after.objects if o.path_id==target.path_id).read_typetree()['m_Script']==changed
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
    if ROLLBACK_BASE:
        directory=ROOT/'releases'/ROLLBACK_BASE;rollback_raw=(directory/'manifest.json').read_bytes()
        assert common.sha(rollback_raw)==ROLLBACK_BASE.split('-',1)[1]
        public.verify(base64.b64decode((directory/'manifest.sig').read_bytes()),rollback_raw,padding.PKCS1v15(),hashes.SHA256())
        rollback_manifest=json.loads(rollback_raw)
    fix=signing.signed_release(snapshot,SEQUENCE,private,public);rollback=signing.signed_release(rollback_manifest,ROLLBACK_SEQUENCE,private,public)
    for name,_,_ in (fix,rollback):assert not (ROOT/'releases'/name).exists()
    path=ROOT/'blobs'/digest
    if path.exists():assert path.read_bytes()==payload
    else:path.write_bytes(payload)
    for name,m,s in (fix,rollback):
        directory=ROOT/'releases'/name;directory.mkdir()
        (directory/'manifest.json').write_bytes(m);(directory/'manifest.sig').write_bytes(s)
    print('SHOP_QUANTITY_READY',fix[0],rollback[0],digest,len(payload),flush=True)

if __name__=='__main__':main()
