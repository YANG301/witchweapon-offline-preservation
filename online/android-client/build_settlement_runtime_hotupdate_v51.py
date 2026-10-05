"""Add the runtime XP/particle draw-order repair to signed release 49."""
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
BASE = '49-95f15190fea3574af622231512b3fd48451ac8295f76c28d85df08b01dcb5e52'
SOURCE = PROJECT / 'android-client' / 'lua' / 'init-settlement-effect-order.lua'
LUA_PATH = 'assetbundle/lua/lua.ab'
OLD_LUA = '572248ed513061d912862fdf4caaa8ddf7e5516727313b56c5268a1e6ba9d683'
OLD_OBJECT = 'dcf956859d1aa6d32faf9c3e2cf60dafaed3582af37312333f7f89d3e5d72d18'
OLD_SCRIPT = '68cf4dc373c34b20a4dae34930de253187f12d99d06d3a9c62a01b32057a37c4'

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def main() -> None:
    source_dir = ROOT / 'releases' / BASE
    raw = (source_dir / 'manifest.json').read_bytes()
    assert sha(raw) == BASE.split('-', 1)[1]
    manifest = json.loads(raw)
    assert manifest['releaseSequence'] == 49 and len(manifest['assets']) == 74
    lua = next(a for a in manifest['assets'] if a['path'] == LUA_PATH)
    assert lua['sha256'] == OLD_LUA
    original = (ROOT / 'blobs' / OLD_LUA).read_bytes()
    assert sha(original) == OLD_LUA
    bundle = UnityPy.load(original)
    before = {o.path_id: sha(o.get_raw_data()) for o in bundle.objects}
    targets = [o for o in bundle.objects if o.type.name == 'TextAsset'
               and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1 and before[targets[0].path_id] == OLD_OBJECT
    target = targets[0]
    tree = target.read_typetree()
    assert sha(tree['m_Script'].encode('utf-8')) == OLD_SCRIPT
    addition = SOURCE.read_text(encoding='utf-8')
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER' not in tree['m_Script']
    assert 'LateUpdateBeat:Add' in addition and 'dynamicMaterial' in addition
    script = tree['m_Script'].rstrip('\n') + '\n\n' + addition.rstrip('\n') + '\n'
    tree['m_Script'] = script
    target.save_typetree(tree)
    patched = bundle.file.save(packer='original')
    reopened = UnityPy.load(patched)
    after = {o.path_id: sha(o.get_raw_data()) for o in reopened.objects}
    assert set(before) == set(after)
    assert {pid for pid in before if before[pid] != after[pid]} == {target.path_id}
    assert next(o for o in reopened.objects if o.path_id == target.path_id).read_typetree()['m_Script'] == script
    for marker in ('ONLINE_MAINLINE_ODD_OPEN', 'ONLINE_GUILD_RECALL_REWARD', 'ONLINE_FURNACE_SELECTION_GATE'):
        assert marker in script

    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(releases.APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((source_dir / 'manifest.sig').read_bytes()), raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(releases.KEY.read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    blob_sha = sha(patched)
    candidate = copy.deepcopy(manifest)
    asset = next(a for a in candidate['assets'] if a['path'] == LUA_PATH)
    asset.update(url='/updates/stable/blobs/' + blob_sha, size=len(patched), sha256=blob_sha)
    fix = releases.signed_release(candidate, 51, private, public)
    rollback = releases.signed_release(manifest, 52, private, public)
    for name, _, _ in (fix, rollback):
        if (ROOT / 'releases' / name).exists():
            raise FileExistsError('Signed release already exists: ' + name)
    path = ROOT / 'blobs' / blob_sha
    if path.exists():
        assert path.read_bytes() == patched
    else:
        path.write_bytes(patched)
    for name, data, signature in (fix, rollback):
        directory = ROOT / 'releases' / name
        directory.mkdir()
        (directory / 'manifest.json').write_bytes(data)
        (directory / 'manifest.sig').write_bytes(signature)
    print('SETTLEMENT_RUNTIME_READY', fix[0], rollback[0], blob_sha, len(patched), flush=True)

if __name__ == '__main__':
    main()
