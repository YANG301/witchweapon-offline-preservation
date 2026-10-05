"""Hide only the four settlement XP level-up particle effects.

Build from the original v110 settlement, undo the prior experimental ordering
changes, and remove only their init.lua block from the current resource release.
"""
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
BASE = '53-630901fbe582b948adf5eafc711de04c391a5f5c8e337209c0ccf406194a90ac'
BASE_LUA = '7f930fe0c4230155eda114bb05330aa716367a223e461d1c7b984fe018025774'
CLEAN_LUA = '572248ed513061d912862fdf4caaa8ddf7e5516727313b56c5268a1e6ba9d683'
SETTLEMENT = 'assetbundle/assets/resources/ui/prefab/settlement.ab'
LUA = 'assetbundle/lua/lua.ab'
OVERRIDE = PROJECT / 'android-client' / 'resources-overrides' / 'settlement-levelup-hidden.ab'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def hide_particles(original):
    assert sha(original) == releases.APK_BUNDLE_SHA
    bundle = UnityPy.load(original)
    objects = {o.path_id: o for o in bundle.objects}
    before = {pid: sha(obj.get_raw_data()) for pid, obj in objects.items()}
    assert len(before) == 833
    transforms = {o.path_id: o.read_typetree() for o in bundle.objects if o.type.name == 'Transform'}
    go_transform = {t['m_GameObject']['m_PathID']: pid for pid, t in transforms.items()}
    roots = set()
    for obj in bundle.objects:
        if obj.type.name != 'MonoBehaviour': continue
        tree = obj.read_typetree()
        if 'levelUpAnim' not in tree or 'expBar' not in tree: continue
        reference = tree['levelUpAnim']
        assert reference['m_FileID'] == 0
        transform = transforms[reference['m_PathID']]
        assert objects[transform['m_GameObject']['m_PathID']].read_typetree()['m_Name'] == 'LVup_BARall_00'
        roots.add(reference['m_PathID'])
    assert len(roots) == 4
    def below_effect(go):
        current = go_transform[go]
        while current in transforms:
            if current in roots: return True
            current = transforms[current]['m_Father']['m_PathID']
        return False
    scoped, changed, original_trees = set(), set(), {}
    for obj in bundle.objects:
        if obj.type.name != 'ParticleSystemRenderer': continue
        tree = obj.read_typetree()
        if not below_effect(tree['m_GameObject']['m_PathID']): continue
        scoped.add(obj.path_id)
        if tree['m_Enabled'] == 0: continue
        assert tree['m_Enabled'] == 1
        original_trees[obj.path_id] = copy.deepcopy(tree)
        tree['m_Enabled'] = 0
        obj.save_typetree(tree)
        changed.add(obj.path_id)
    assert len(scoped) == 24 and len(changed) == 20
    patched = bundle.file.save(packer='original')
    reopened = UnityPy.load(patched)
    after = {o.path_id: sha(o.get_raw_data()) for o in reopened.objects}
    assert set(before) == set(after)
    assert {pid for pid in before if before[pid] != after[pid]} == changed
    for obj in reopened.objects:
        if obj.path_id in scoped:
            tree = obj.read_typetree()
            assert tree['m_Enabled'] == 0
            if obj.path_id in changed:
                restored = copy.deepcopy(tree)
                restored['m_Enabled'] = 1
                assert restored == original_trees[obj.path_id]
    # Every other object is byte-identical: XP widgets, labels, animation
    # references, transforms, material queues and scripts remain original.
    return patched

def verify_clean_lua():
    dirty = (ROOT / 'blobs' / BASE_LUA).read_bytes()
    clean = (ROOT / 'blobs' / CLEAN_LUA).read_bytes()
    assert sha(dirty) == BASE_LUA and sha(clean) == CLEAN_LUA
    original, baseline = UnityPy.load(dirty), UnityPy.load(clean)
    before = {o.path_id: sha(o.get_raw_data()) for o in original.objects}
    after = {o.path_id: sha(o.get_raw_data()) for o in baseline.objects}
    assert set(before) == set(after)
    targets = [o for o in original.objects if o.type.name == 'TextAsset' and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1
    target = targets[0]
    assert {pid for pid in before if before[pid] != after[pid]} == {target.path_id}
    clean_init = next(o for o in baseline.objects if o.path_id == target.path_id).read_typetree()['m_Script']
    dirty_init = target.read_typetree()['m_Script']
    prefix = clean_init.rstrip('\n') + '\n\n'
    assert dirty_init.startswith(prefix)
    assert dirty_init[len(prefix):].startswith('-- Keep the original witch level-up particles below')
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER_READY 53' in dirty_init[len(prefix):]
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER' not in clean_init
    for marker in ('ONLINE_MAINLINE_ODD_OPEN', 'ONLINE_GUILD_RECALL_REWARD', 'ONLINE_FURNACE_SELECTION_GATE'):
        assert marker in clean_init
    return clean

def main():
    folder = ROOT / 'releases' / BASE
    raw = (folder / 'manifest.json').read_bytes()
    assert sha(raw) == BASE.split('-', 1)[1]
    manifest = json.loads(raw)
    assert manifest['releaseSequence'] == 53 and len(manifest['assets']) == 74
    assert next(a for a in manifest['assets'] if a['path'] == LUA)['sha256'] == BASE_LUA
    with zipfile.ZipFile(releases.APK) as apk:
        patched = hide_particles(apk.read(releases.APK_MEMBER))
        public_der = apk.read('assets/update_public_key.der')
    clean = verify_clean_lua()
    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    public = serialization.load_der_public_key(public_der)
    public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(releases.KEY.read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    proposed = copy.deepcopy(manifest)
    for logical, data in ((SETTLEMENT, patched), (LUA, clean)):
        digest = sha(data)
        asset = next(a for a in proposed['assets'] if a['path'] == logical)
        asset.update(url='/updates/stable/blobs/' + digest, size=len(data), sha256=digest)
        blob = ROOT / 'blobs' / digest
        if blob.exists(): assert blob.read_bytes() == data
        else: blob.write_bytes(data)
    fix = releases.signed_release(proposed, 55, private, public)
    rollback = releases.signed_release(manifest, 56, private, public)
    for name, _, _ in (fix, rollback):
        if (ROOT / 'releases' / name).exists(): raise FileExistsError(name)
    if OVERRIDE.exists(): assert OVERRIDE.read_bytes() == patched
    else: OVERRIDE.write_bytes(patched)
    for name, data, signature in (fix, rollback):
        directory = ROOT / 'releases' / name
        directory.mkdir()
        (directory / 'manifest.json').write_bytes(data)
        (directory / 'manifest.sig').write_bytes(signature)
    print('SETTLEMENT_PARTICLES_HIDDEN_READY', fix[0], rollback[0], sha(patched), len(patched), flush=True)

if __name__ == '__main__': main()
