"""Correct only the visible agreement name in the previously published prefab."""
import base64
import copy
import json
from pathlib import Path
import sys
import zipfile

import UnityPy
import build_settlement_levelup_hotupdate as signing

sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

PROJECT, ROOT = signing.PROJECT, signing.ROOT
BASE = '167-5d6e6ed6dd7d20ee89f4e8e029fd84ac47e2ed7ca927e2918a3083c08d7ca6fb'
REPORT = PROJECT/'验收/用户协议名称修正热更新.json'
APK = PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
LOGICAL = 'assetbundle/assets/resources/ui/prefab/login/loginmain.ab'


def main():
    raw = (ROOT/'releases'/BASE/'manifest.json').read_bytes()
    assert signing.sha(raw) == BASE.split('-',1)[1]
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/BASE/'manifest.sig').read_bytes()),raw,
        padding.PKCS1v15(),hashes.SHA256())
    baseline = json.loads(raw)
    original_asset = next(a for a in baseline['assets'] if a['path']==LOGICAL)
    original = (ROOT/'blobs'/original_asset['sha256']).read_bytes()
    assert signing.sha(original)==original_asset['sha256']
    env = UnityPy.load(original)
    before = {o.path_id:signing.sha(o.get_raw_data()) for o in env.objects}
    changed = set()
    for obj in env.objects:
        if obj.type.name!='MonoBehaviour':continue
        tree = obj.read_typetree()
        text = tree.get('mText')
        if not isinstance(text,str):continue
        revised = text.replace('新丰洲君子约定','用户协议').replace('君子约定','用户协议')
        revised = revised.replace('用户阅读本约定后','用户阅读本协议后')
        if text!=revised:
            tree['mText']=revised
            obj.save_typetree(tree)
            changed.add(obj.path_id)
    assert len(changed)==15
    payload = env.file.save(packer='original')
    reopened = UnityPy.load(payload)
    after = {o.path_id:signing.sha(o.get_raw_data()) for o in reopened.objects}
    assert set(before)==set(after) and {p for p in before if before[p]!=after[p]}==changed
    texts = [o.read_typetree().get('mText','') for o in reopened.objects if o.type.name=='MonoBehaviour']
    assert not any('君子约定' in t for t in texts)
    assert texts.count('用户协议')==1 and sum('用户阅读本协议后' in t for t in texts)==1
    digest=signing.sha(payload)
    snapshot=copy.deepcopy(baseline)
    asset=next(a for a in snapshot['assets'] if a['path']==LOGICAL)
    asset.update(url='/updates/stable/blobs/'+digest,sha256=digest,size=len(payload))
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    releases=(signing.signed_release(snapshot,169,private,public),signing.signed_release(baseline,170,private,public))
    for name,_,_ in releases:assert not (ROOT/'releases'/name).exists()
    blob=ROOT/'blobs'/digest
    if blob.exists():assert blob.read_bytes()==payload
    else:blob.write_bytes(payload)
    for name,manifest,signature in releases:
        folder=ROOT/'releases'/name;folder.mkdir()
        (folder/'manifest.json').write_bytes(manifest);(folder/'manifest.sig').write_bytes(signature)
    override=PROJECT/'android-client/resources-overrides/login-community-agreement.ab'
    override.write_bytes(payload)
    record=dict(status='SIGNED_CANDIDATE',base=BASE,release=releases[0][0],rollback=releases[1][0],
        changedAsset=asset,changedAssets=[LOGICAL],deltaBytes=len(payload),sourceApk=str(APK),
        changedObjects=len(changed),visibleName='用户协议',physicalDeviceValidated=False)
    REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False))


if __name__=='__main__':main()
