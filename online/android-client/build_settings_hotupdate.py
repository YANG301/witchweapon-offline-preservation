"""Append settings runtime and restore the original settings prefab in a signed snapshot."""
import argparse,base64,copy,json,sys,zipfile
import UnityPy
import build_task_live_hotupdate_v57 as common
import build_settlement_levelup_hotupdate as signing
import build_settings_prefab as prefab
BASE='99-8b5d23970ef70b86ab6fe759ab1d10ec85ff26685c17ba94bcb236b142452aeb'
ROOT=common.ROOT
LUA='assetbundle/lua/lua.ab'
SOURCE=common.PROJECT/'android-client/lua/init-settings-profile.lua'
def main(sequence=107):
    folder=ROOT/'releases'/BASE;raw=(folder/'manifest.json').read_bytes()
    assert common.sha(raw)==BASE.split('-',1)[1]
    manifest=json.loads(raw);assert len(manifest['assets'])==74
    asset=next(a for a in manifest['assets'] if a['path']==LUA)
    blob=(ROOT/'blobs'/asset['sha256']).read_bytes();assert common.sha(blob)==asset['sha256']
    env=UnityPy.load(blob);before={o.path_id:common.sha(o.get_raw_data()) for o in env.objects}
    target,=[o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree=target.read_typetree();original=tree['m_Script'];assert 'ONLINE_SETTINGS_PROFILE_READY' not in original
    changed=original.rstrip('\n')+'\n\n'+SOURCE.read_text(encoding='utf-8')
    for marker in ('ONLINE_TASK_LIVE_READY 65','ONLINE_GUILD_RECALL_REWARD','ONLINE_SHOP_BATCH_READY 77','star_ready 99'):
        assert marker in changed,marker
    common.check_syntax(changed);tree['m_Script']=changed;target.save_typetree(tree)
    payload=env.file.save(packer='original');after=UnityPy.load(payload)
    after_hash={o.path_id:common.sha(o.get_raw_data()) for o in after.objects}
    assert set(before)==set(after_hash)
    assert {p for p in before if before[p]!=after_hash[p]}=={target.path_id}
    assert next(o for o in after.objects if o.path_id==target.path_id).read_typetree()['m_Script']==changed
    settings=prefab.patch(prefab.SOURCE_BUNDLE.read_bytes())
    snapshot=copy.deepcopy(manifest)
    assert not any(a['path']==prefab.ASSET_PATH for a in snapshot['assets'])
    digest=common.sha(payload)
    next(a for a in snapshot['assets'] if a['path']==LUA).update(url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    settings_digest=common.sha(settings)
    snapshot['assets'].append(dict(path=prefab.ASSET_PATH,url='/updates/stable/blobs/'+settings_digest,size=len(settings),sha256=settings_digest))
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(signing.APK) as apk:public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    rollback_snapshot=copy.deepcopy(manifest)
    rollback_original=prefab.SOURCE_BUNDLE.read_bytes()
    rollback_digest=common.sha(rollback_original)
    rollback_snapshot['assets'].append(dict(path=prefab.ASSET_PATH,url='/updates/stable/blobs/'+rollback_digest,size=len(rollback_original),sha256=rollback_digest))
    fix=signing.signed_release(snapshot,sequence,private,public);rollback=signing.signed_release(rollback_snapshot,sequence+1,private,public)
    for name,_,_ in (fix,rollback):assert not (ROOT/'releases'/name).exists()
    for data in (payload,settings,rollback_original):
        path=ROOT/'blobs'/common.sha(data)
        if path.exists():assert path.read_bytes()==data
        else:path.write_bytes(data)
    for name,m,s in (fix,rollback):
        directory=ROOT/'releases'/name;directory.mkdir()
        (directory/'manifest.json').write_bytes(m);(directory/'manifest.sig').write_bytes(s)
    print('SETTINGS_RELEASE_READY',fix[0],rollback[0],digest,settings_digest,flush=True)
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--sequence',type=int,default=107)
    main(parser.parse_args().sequence)
