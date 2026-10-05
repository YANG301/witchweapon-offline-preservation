"""Sign the individually verified weapon/maze repair on the live v157 baseline."""
import argparse
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import UnityPy

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT/'android-client'), r'D:\Environment\VPS-SSH\packages313']
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ROOT = PROJECT/'热更新测试/主线热更候选'
AUDIT = PROJECT/'验收/战斗效果修复'
BASE = '157-19113cb6aca17494d33d726e524f4fc01198df2aac5392c4dbe4b24a250d6f32'
BASE_FIXTURE = 'eccf65bebf75270fab64ceee2f79c698f7b8f0bb7aa22c7cbcba8de8baea881a'
BASE_JAR = '9dc190575aa4711f5e4b70836ee2054c9f9336758f282201bbe5de722ab18b18'
APK = PROJECT/'构建/战斗数据校正/魔女兵器-在线本地双区服-v121-测试.apk'

def sha(raw):return hashlib.sha256(raw).hexdigest()

def patch_lua(raw, runtime):
    env = UnityPy.load(raw)
    before = {o.path_id:sha(o.get_raw_data()) for o in env.objects}
    obj, = [o for o in env.objects if o.type.name=='TextAsset'
            and o.read_typetree().get('m_Name')=='init.lua']
    tree = obj.read_typetree();original = tree['m_Script']
    start = '-- Finish a released manual move before its queued enemy selection is lost.'
    end = "UnityEngine.Debug.LogWarning('WWR_COMBAT_RETARGET_READY 153')"
    assert original.count(start)==original.count(end)==1
    a,b = original.index(start),original.index(end)+len(end)
    patch = (PROJECT/'android-client/lua/init-combat-retarget.lua').read_text(encoding='utf-8').rstrip()
    check_lua(patch)
    script = original[:a]+patch+original[b:]
    assert original[:a]==script[:a] and script.endswith(original[b:])
    if runtime:
        text = runtime.read_text(encoding='utf-8').rstrip();check_lua(text)
        assert text not in script
        script += '\n\n'+text+'\n'
    check_lua(script)
    assert script.count('WWR_COMBAT_RETARGET_READY 159')==1
    assert 'WWR_COMBAT_RETARGET_READY 153' not in script
    tree['m_Script']=script;obj.save_typetree(tree)
    revised=env.file.save(packer='original')
    after={o.path_id:sha(o.get_raw_data()) for o in UnityPy.load(revised).objects}
    assert {p for p in before if before[p]!=after[p]}=={obj.path_id}
    return revised

def main():
    p=argparse.ArgumentParser();p.add_argument('--fixture',type=Path,required=True)
    p.add_argument('--jar',type=Path,required=True);p.add_argument('--spells',type=Path,required=True)
    p.add_argument('--runtime',type=Path);args=p.parse_args()
    assert (ROOT/'current').read_text(encoding='utf-8').strip()==BASE
    folder=ROOT/'releases'/BASE;body=(folder/'manifest.json').read_bytes()
    assert sha(body)==BASE.split('-',1)[1]
    with zipfile.ZipFile(APK) as z:public=serialization.load_der_public_key(z.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()),body,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    assert sha((PROJECT/'legacy-server/resources/offline_responses.json').read_bytes())==BASE_FIXTURE
    previous=json.loads((PROJECT/'legacy-server/resources/offline_responses.json').read_text(encoding='utf-8'))
    revised_fixture=json.loads(args.fixture.read_text(encoding='utf-8'))
    assert set(previous)==set(revised_fixture)
    assert {k for k in previous if previous[k]!=revised_fixture[k]}=={'/combat/role/info'}
    base_jar=PROJECT/'验收/战斗全面核查/候选/witchweapon-legacy.jar'
    assert sha(base_jar.read_bytes())==BASE_JAR
    with zipfile.ZipFile(base_jar) as old,zipfile.ZipFile(args.jar) as new:
        changed=[p for p in old.namelist() if old.read(p)!=new.read(p)]
        added=sorted(set(new.namelist())-set(old.namelist()))
        assert set(old.namelist()).issubset(set(new.namelist()))
        allowed={'com/codex/witchweapon/'+n+'.class' for n in ('BarrierLabyrinth','LocalSave','StandaloneServer')}
        allowed.update(p for p in set(old.namelist())|set(new.namelist())
                       if p.startswith('com/codex/witchweapon/BarrierLabyrinth$') and p.endswith('.class'))
        allowed.update({'com/codex/witchweapon/StandaloneServer$1.class',
                        'com/codex/witchweapon/StandaloneServer$2.class'})
        assert set(changed).issubset(allowed),changed
        assert set(added)=={'com/codex/witchweapon/MazeRules.class','maze_rules.json'},added
        assert sha(new.read('maze_rules.json'))=='6b61a36aac6ddbf38b72f946ce13fc31ab0a340b2e5cf4158633ee3011b3149d'
    original=json.loads(body);revised=copy.deepcopy(original);assets={a['path']:a for a in original['assets']}
    assert len(assets)==118
    payloads={'assetbundle/lua/lua.ab':patch_lua((ROOT/'blobs'/assets['assetbundle/lua/lua.ab']['sha256']).read_bytes(),args.runtime),
              'assetbundle/config/xmlconf/skill/spells.ab':args.spells.read_bytes()}
    changed_assets={}
    for path,payload in payloads.items():
        digest=sha(payload);assert assets[path]['sha256']!=digest
        blob=ROOT/'blobs'/digest
        if blob.exists():assert blob.read_bytes()==payload
        else:blob.write_bytes(payload)
        changed_assets[path]=dict(path=path,url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    revised['assets']=[changed_assets.get(a['path'],a) for a in original['assets']]
    release=signed_release(revised,159,private,public);rollback=signed_release(original,160,private,public)
    for name,data,sig in (release,rollback):
        dest=ROOT/'releases'/name;dest.mkdir()
        (dest/'manifest.json').write_bytes(data);(dest/'manifest.sig').write_bytes(sig)
    record=dict(base=BASE,release=release[0],rollback=rollback[0],changedAssets=changed_assets,resourceCount=118,
        fixture=str(args.fixture),fixtureSha256=sha(args.fixture.read_bytes()),baseFixtureSha256=BASE_FIXTURE,
        jar=str(args.jar),jarSha256=sha(args.jar.read_bytes()),baseJarSha256=BASE_JAR,
        changedClasses=changed,addedClasses=added,runtime=str(args.runtime) if args.runtime else None,
        status='LOCAL_VALIDATED_CANDIDATE',deviceValidated=False)
    (AUDIT/'发布.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('COMBAT_EFFECT_RELEASE_SIGNED',record['release'],sum(a['size'] for a in changed_assets.values()))

if __name__=='__main__':main()
