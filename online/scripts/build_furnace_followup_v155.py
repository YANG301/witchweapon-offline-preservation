"""Replace only the furnace Lua after correcting a reflected type name."""
import base64
import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path
import UnityPy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'android-client'), r'D:\Environment\VPS-SSH\packages313']
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
ROOT = PROJECT / '热更新测试/主线热更候选'
REPORT = PROJECT / '验收/战斗修复/发布.json'

if __name__ == '__main__':
    record = json.loads(REPORT.read_text(encoding='utf-8'))
    base_name = record['release']
    assert base_name == (ROOT / 'current').read_text(encoding='utf-8').strip()
    assert base_name.startswith('153-')
    folder = ROOT / 'releases' / base_name
    raw = (folder / 'manifest.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == base_name.split('-', 1)[1]
    with zipfile.ZipFile(PROJECT / '构建/运行性能修复/魔女兵器-在线本地双区服-v119-测试.apk') as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw, padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key((PROJECT / '.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    base = json.loads(raw)
    updated = copy.deepcopy(base)
    asset = next(a for a in base['assets'] if a['path'] == 'assetbundle/lua/lua.ab')
    env = UnityPy.load((ROOT / 'blobs' / asset['sha256']).read_bytes())
    before = {o.path_id: hashlib.sha256(o.get_raw_data()).hexdigest() for o in env.objects}
    obj, = [o for o in env.objects if o.type.name == 'TextAsset' and o.read_typetree().get('m_Name') == 'init.lua']
    tree = obj.read_typetree()
    marker = '-- Furnace only: distinct purchase identities and a direct final-slot completion.'
    old = tree['m_Script']
    assert old.count(marker) == 1
    patch = (PROJECT / 'android-client/lua/init-furnace-reward-choice.lua').read_text(encoding='utf-8')
    assert 'ONLINE_FURNACE_REWARD_CHOICE_READY 155' in patch
    assert "kind('dataType', 'WaterBell.ProjX.View.Panel.UIDataBase')" in patch
    tree['m_Script'] = old[:old.index(marker)] + patch
    check_lua(tree['m_Script'])
    obj.save_typetree(tree)
    payload = env.file.save(packer='original')
    after = {o.path_id: hashlib.sha256(o.get_raw_data()).hexdigest() for o in UnityPy.load(payload).objects}
    assert {p for p in before if before[p] != after[p]} == {obj.path_id}
    sha = hashlib.sha256(payload).hexdigest()
    blob = ROOT / 'blobs' / sha
    if blob.exists(): assert blob.read_bytes() == payload
    else: blob.write_bytes(payload)
    new = dict(path=asset['path'], url='/updates/stable/blobs/' + sha, size=len(payload), sha256=sha)
    updated['assets'] = [new if a['path'] == asset['path'] else a for a in base['assets']]
    release = signed_release(updated, 155, private, public)
    rollback = signed_release(base, 156, private, public)
    for name, data, sig in (release, rollback):
        directory = ROOT / 'releases' / name
        directory.mkdir()
        (directory / 'manifest.json').write_bytes(data)
        (directory / 'manifest.sig').write_bytes(sig)
    record['clientFollowup'] = dict(base=base_name,release=release[0],rollback=rollback[0],
        changedAssets={asset['path']:new},status='LOCAL_VALIDATED_CANDIDATE')
    REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('FURNACE_FOLLOWUP_READY', release[0], len(payload), flush=True)
