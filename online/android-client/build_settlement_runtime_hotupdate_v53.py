"""Replace the failed v51 initializer, explicitly loading Unity engine types."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import UnityPy
import build_settlement_levelup_hotupdate as releases

PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / '热更新测试' / '主线热更候选'
BASE = '51-0ed2268b1acb2083800325d7a6afaf9bf03045d5fc7b0d4aa7d108ea4f06a15f'
BASE49 = '49-95f15190fea3574af622231512b3fd48451ac8295f76c28d85df08b01dcb5e52'
OLD_LUA = '4b7aa18a3cf14eb881a033e0e4dfd9ae2549062274a19fcf827dd4c5996c2f7a'
OLD49_LUA = '572248ed513061d912862fdf4caaa8ddf7e5516727313b56c5268a1e6ba9d683'
SOURCE = PROJECT / 'android-client' / 'lua' / 'init-settlement-effect-order.lua'
LOGICAL = 'assetbundle/lua/lua.ab'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def init(bundle):
    targets = [o for o in bundle.objects if o.type.name == 'TextAsset'
               and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1
    return targets[0]

def main():
    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(releases.APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    for name in (BASE, BASE49):
        folder = ROOT / 'releases' / name
        raw = (folder / 'manifest.json').read_bytes()
        assert sha(raw) == name.split('-', 1)[1]
        public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw,
                      padding.PKCS1v15(), hashes.SHA256())
    manifest = json.loads((ROOT / 'releases' / BASE / 'manifest.json').read_bytes())
    assert manifest['releaseSequence'] == 51 and len(manifest['assets']) == 74
    asset = next(a for a in manifest['assets'] if a['path'] == LOGICAL)
    assert asset['sha256'] == OLD_LUA
    raw = (ROOT / 'blobs' / OLD_LUA).read_bytes()
    raw49 = (ROOT / 'blobs' / OLD49_LUA).read_bytes()
    assert sha(raw) == OLD_LUA and sha(raw49) == OLD49_LUA
    bundle, baseline = UnityPy.load(raw), UnityPy.load(raw49)
    target, old = init(bundle), init(baseline)
    before = {o.path_id: sha(o.get_raw_data()) for o in bundle.objects}
    tree = target.read_typetree()
    original_script = old.read_typetree()['m_Script']
    prefix = original_script.rstrip('\n') + '\n\n'
    assert tree['m_Script'].startswith(prefix)
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER_READY 51' in tree['m_Script'][len(prefix):]
    addition = SOURCE.read_text(encoding='utf-8')
    assert "tolua.loadassembly('UnityEngine.CoreModule')" in addition
    assert "tolua.loadassembly('UnityEngine.ParticleSystemModule')" in addition
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER_READY 53' in addition
    tree['m_Script'] = prefix + addition.rstrip('\n') + '\n'
    target.save_typetree(tree)
    patched = bundle.file.save(packer='original')
    after = {o.path_id: sha(o.get_raw_data()) for o in UnityPy.load(patched).objects}
    assert set(before) == set(after) and {pid for pid in before if before[pid] != after[pid]} == {target.path_id}
    assert init(UnityPy.load(patched)).read_typetree()['m_Script'] == tree['m_Script']
    private = serialization.load_pem_private_key(releases.KEY.read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    proposed = copy.deepcopy(manifest)
    new_asset = next(a for a in proposed['assets'] if a['path'] == LOGICAL)
    digest = sha(patched)
    new_asset.update(url='/updates/stable/blobs/' + digest, sha256=digest, size=len(patched))
    fix = releases.signed_release(proposed, 53, private, public)
    rollback = releases.signed_release(manifest, 54, private, public)
    for name, _, _ in (fix, rollback):
        if (ROOT / 'releases' / name).exists(): raise FileExistsError(name)
    blob = ROOT / 'blobs' / digest
    if blob.exists(): assert blob.read_bytes() == patched
    else: blob.write_bytes(patched)
    for name, data, signature in (fix, rollback):
        directory = ROOT / 'releases' / name
        directory.mkdir()
        (directory / 'manifest.json').write_bytes(data)
        (directory / 'manifest.sig').write_bytes(signature)
    print('SETTLEMENT_ENGINE_TYPES_READY', fix[0], rollback[0], digest, len(patched), flush=True)

if __name__ == '__main__': main()
