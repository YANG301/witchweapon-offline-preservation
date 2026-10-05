"""Keep local login assets in the APK; update protocol text and images via Lua."""
import base64
import copy
import json
import sys
import zipfile

import build_settlement_levelup_hotupdate as signing
import patch_notice_image_runtime as media

sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import padding

PROJECT,ROOT = signing.PROJECT,signing.ROOT
REPORT = PROJECT/'验收/公告图文与正式协议最终热更新.json'
APK = PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
LUA = 'assetbundle/lua/lua.ab'


def build(sequence=175):
    prior_path = REPORT if sequence > 175 else PROJECT/'验收/公告图文热更旧版兼容.json'
    prior = json.loads(prior_path.read_text(encoding='utf-8'))
    assert prior['status'] == 'LIVE_AND_VERIFIED'
    # Once account recovery is present, rebuilding the older notice-only tail
    # would silently remove it. Route later revisions through the complete builder.
    if sequence > 175 and int(prior['release'].split('-',1)[0]) >= 183:
        from build_account_notice_hotupdate import build as complete_build
        return complete_build(sequence)
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    def load(name):
        folder=ROOT/'releases'/name;raw=(folder/'manifest.json').read_bytes()
        assert signing.sha(raw)==name.split('-',1)[1]
        public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
        return json.loads(raw)
    baseline,rollback = load(prior['release']),load(prior['rollback'])
    assert len(baseline['assets'])==121 and len(rollback['assets'])==119
    source = next(a for a in baseline['assets'] if a['path']==LUA)
    raw = (ROOT/'blobs'/source['sha256']).read_bytes()
    assert signing.sha(raw)==source['sha256']
    fixed,notice_info = media.replace_notice_runtime(raw)
    payload,agreement_info = media.append_agreement_lua(fixed,
        (PROJECT/'legacy-server/resources/community_agreement.txt').read_text(encoding='utf-8'))
    digest=signing.sha(payload)
    snapshot=copy.deepcopy(baseline)
    asset=next(a for a in snapshot['assets'] if a['path']==LUA)
    asset.update(sha256=digest,size=len(payload),url='/updates/stable/blobs/'+digest)
    forbidden={'assetbundle/assets/resources/ui/prefab/login/loginmain.ab','assetbundle/scene/loginfromal.ab'}
    assert not forbidden.intersection(a['path'] for a in snapshot['assets'])
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert public.public_numbers()==private.public_key().public_numbers()
    assert sequence > int(prior['release'].split('-', 1)[0])
    releases=(signing.signed_release(snapshot,sequence,private,public),signing.signed_release(rollback,sequence+1,private,public))
    for name,_,_ in releases:assert not (ROOT/'releases'/name).exists()
    blob=ROOT/'blobs'/digest
    if blob.exists():assert blob.read_bytes()==payload
    else:blob.write_bytes(payload)
    for name,manifest,signature in releases:
        folder=ROOT/'releases'/name;folder.mkdir()
        (folder/'manifest.json').write_bytes(manifest);(folder/'manifest.sig').write_bytes(signature)
    record=dict(status='SIGNED_CANDIDATE',base=prior['release'],release=releases[0][0],rollback=releases[1][0],
        rollbackReference=prior['rollback'],changedAssets=[asset],sourceApk=str(APK),totalAssets=121,
        deltaBytes=len(payload),notice=notice_info,agreement=agreement_info,imageMembers=12,
        excludedMember='YANG301',sourceImage='E:/Desktop/魔女兵器公告素材/感谢名单-测试群成员.png',
        physicalDeviceValidated=False,protectedLoginAssetsExcluded=True)
    REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sequence',type=int,default=175)
    build(parser.parse_args().sequence)
