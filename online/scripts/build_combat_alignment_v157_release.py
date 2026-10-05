"""Sign only the validated combat XML delta, preserving every other resource."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT/'android-client'),r'D:\Environment\VPS-SSH\packages313']
from build_settlement_levelup_hotupdate import signed_release
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

ROOT = PROJECT/'热更新测试/主线热更候选'
AUDIT = PROJECT/'验收/战斗全面核查'


def sha(raw):return hashlib.sha256(raw).hexdigest()


def main():
    candidate=json.loads((AUDIT/'候选/candidate.json').read_text(encoding='utf-8'))
    verification=json.loads((AUDIT/'候选/verification.json').read_text(encoding='utf-8'))
    base=candidate['base']
    assert (ROOT/'current').read_text(encoding='utf-8').strip()==base
    raw=(ROOT/'releases'/base/'manifest.json').read_bytes()
    assert sha(raw)==base.split('-',1)[1]
    with zipfile.ZipFile(PROJECT/'构建/战斗修复/魔女兵器-在线本地双区服-v120-测试.apk') as apk:
        public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/base/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    original=json.loads(raw); revised=copy.deepcopy(original)
    blob=(AUDIT/'候选/spells.ab').read_bytes();digest=sha(blob)
    assert digest==candidate['candidateSpellSha256']
    path='assetbundle/config/xmlconf/skill/spells.ab'
    new=dict(path=path,url='/updates/stable/blobs/'+digest,size=len(blob),sha256=digest)
    assert sum(a['path']==path for a in original['assets'])==1
    revised['assets']=[new if a['path']==path else a for a in original['assets']]
    assert len(revised['assets'])==118
    dest=ROOT/'blobs'/digest
    if dest.exists():assert dest.read_bytes()==blob
    else:dest.write_bytes(blob)
    release=signed_release(revised,157,private,public)
    rollback=signed_release(original,158,private,public)
    for name,body,sig in (release,rollback):
        folder=ROOT/'releases'/name
        folder.mkdir()
        (folder/'manifest.json').write_bytes(body);(folder/'manifest.sig').write_bytes(sig)
    report=dict(base=base,release=release[0],rollback=rollback[0],changedAssets={path:new},resourceCount=118,
        fixture=str(AUDIT/'候选/offline_responses.json'),fixtureSha256=candidate['candidateFixtureSha256'],
        baseFixtureSha256=candidate['baseFixtureSha256'],jar=str(AUDIT/'候选/witchweapon-legacy.jar'),
        jarSha256=verification['candidateJarSha256'],baseJarSha256=verification['baseJarSha256'],
        status='LOCAL_VALIDATED_CANDIDATE',deviceValidated=False,
        tests=verification['testResults'],changes=candidate,
        unchanged=['关卡布局与刷怪','引擎代码','玩家存档','缺失原服实参的系数及全队合成权重'])
    (AUDIT/'发布.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT_ALIGNMENT_SIGNED',release[0],len(blob))


if __name__=='__main__':main()
