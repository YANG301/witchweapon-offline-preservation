"""Compose the latest complete snapshot with notice, agreement and account UI."""
import base64
import copy
import json
from pathlib import Path
import zipfile
import build_notice_runtime_compat_hotupdate as prior
import patch_notice_image_runtime as media
import notice_update_history as history

PROJECT, ROOT, REPORT = prior.PROJECT, prior.ROOT, prior.REPORT


def build(sequence=183, notes=()):
    release_notes = history.pending(sequence, notes)
    previous = json.loads(REPORT.read_text(encoding='utf-8'))
    assert previous['status'] in ('LIVE_AND_VERIFIED','SIGNED_CANDIDATE')
    base = previous['release'] if previous['status']=='LIVE_AND_VERIFIED' else previous['base']
    assert sequence > int(base.split('-',1)[0])
    with zipfile.ZipFile(prior.APK) as apk:
        public = prior.serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    folder = ROOT/'releases'/base
    raw = (folder/'manifest.json').read_bytes()
    assert prior.signing.sha(raw) == base.split('-',1)[1]
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,
        prior.padding.PKCS1v15(),prior.hashes.SHA256())
    baseline = json.loads(raw)
    snapshot = copy.deepcopy(baseline)
    old_lua = next(a for a in baseline['assets'] if a['path']==prior.LUA)
    payload, notice = media.replace_notice_runtime((ROOT/'blobs'/old_lua['sha256']).read_bytes())
    payload, agreement = media.append_agreement_lua(payload,
        (PROJECT/'legacy-server/resources/community_agreement.txt').read_text(encoding='utf-8'))
    payload, login = media.append_login_email_lua(payload)
    image_path = Path('E:/Desktop/魔女兵器公告素材/感谢名单-测试群成员.png')
    image, image_info = media.image_bundle(prior.APK,image_path)
    changed = []
    for logical, content in ((prior.LUA,payload),(media.IMAGE_LOGICAL,image)):
        digest = prior.signing.sha(content)
        asset = next(a for a in snapshot['assets'] if a['path']==logical)
        if digest == asset['sha256']:
            assert len(content) == asset['size']
            continue
        asset.update(sha256=digest,size=len(content),url='/updates/stable/blobs/'+digest)
        blob=ROOT/'blobs'/digest
        if blob.exists(): assert blob.read_bytes()==content
        else: blob.write_bytes(content)
        changed.append(asset)
    assert len(snapshot['assets']) == len(baseline['assets']) == 121
    assert prior.LUA in {a['path'] for a in changed}
    assert not {'assetbundle/assets/resources/ui/prefab/login/loginmain.ab',
        'assetbundle/scene/loginfromal.ab'}.intersection(a['path'] for a in snapshot['assets'])
    private=prior.serialization.load_pem_private_key(prior.signing.KEY.read_bytes(),password=None)
    assert public.public_numbers()==private.public_key().public_numbers()
    releases=[prior.signing.signed_release(m,n,private,public)
        for m,n in ((snapshot,sequence),(baseline,sequence+1))]
    assert all(not (ROOT/'releases'/name).exists() for name,_,_ in releases)
    for name, manifest, signature in releases:
        destination=ROOT/'releases'/name
        destination.mkdir()
        (destination/'manifest.json').write_bytes(manifest)
        (destination/'manifest.sig').write_bytes(signature)
    history.sync(release_notes)
    record=dict(status='SIGNED_CANDIDATE',base=base,release=releases[0][0],
        rollback=releases[1][0],rollbackReference=base,changedAssets=changed,
        sourceApk=str(prior.APK),totalAssets=121,deltaBytes=sum(a['size'] for a in changed),
        notice=notice,agreement=agreement,login=login,image=image_info,imageMembers=12,
        excludedMember='YANG301',sourceImage=str(image_path),physicalDeviceValidated=False,
        protectedLoginAssetsExcluded=True, playerUpdateHistoryEntries=len(release_notes),
        thanksDuplicateHeadingHidden=True, thanksImageTextGap=0)
    REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sequence',type=int,default=183)
    parser.add_argument('--note',action='append',default=[])
    args = parser.parse_args()
    build(args.sequence, args.note)
