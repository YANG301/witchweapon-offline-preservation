"""Restore the original clickable CAPH shop entry without changing service rules."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import UnityPy
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release

PROJECT = Path(__file__).resolve().parent.parent
ROOT = PROJECT / '热更新测试/主线热更候选'
BASE = '123-f3817fbeff6f693bb18a7176baf65ad986c1e4038bd0b50b095a3048967a7b6a'
APK = PROJECT / '构建/入口显示修复/魔女兵器-在线本地双区服-v112-测试.apk'
REPORT = PROJECT / '验收/入口显示修复/CAPH按钮修复.json'
LUA = 'assetbundle/lua/lua.ab'
VIP = 'assetbundle/assets/resources/ui/prefab/vip/vippanel.ab'
MARKER = '-- WWR optional entry visibility v1.'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def patch_lua(raw):
    env = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    target, = [o for o in env.objects if o.type.name == 'TextAsset'
               and o.read_typetree().get('m_Name') == 'init.lua']
    tree = target.read_typetree()
    original = tree['m_Script']
    assert original.count(MARKER) == 1 and 'WWR_OPTIONAL_ENTRIES_READY 123' in original
    addition = (PROJECT/'android-client/lua/init-optional-entry-visibility.lua').read_text(encoding='utf-8')
    assert addition.startswith(MARKER) and 'WWR_OPTIONAL_ENTRIES_READY 125' in addition
    script = original.split(MARKER)[0] + addition.rstrip('\n') + '\n'
    assert 'WWR_OPTIONAL_ENTRIES_READY 123' not in script
    check_lua(script)
    tree['m_Script'] = script
    target.save_typetree(tree)
    payload = env.file.save(packer='original')
    after = {o.path_id: o for o in UnityPy.load(payload).objects}
    assert set(after) == set(before)
    assert {p for p in before if sha(after[p].get_raw_data()) != before[p]} == {target.path_id}
    assert after[target.path_id].read_typetree()['m_Script'] == script
    assert 'WWR_PRESERVED_STAGE_MANIFEST_READY' in script and 'ONLINE_TASK_LIVE_READY 65' in script
    assert 'guides(UnityEngine.Resources.FindObjectsOfTypeAll(guideType))' in script
    return payload

def patch_vip(raw):
    env = UnityPy.load(raw)
    objects = {o.path_id: o for o in env.objects}
    before = {p: sha(o.get_raw_data()) for p, o in objects.items()}
    button = objects[-448844550402408984]
    tree = button.read_typetree()
    assert tree['m_Name'] == 'GoShopbtn' and not tree['m_IsActive']
    tree['m_IsActive'] = True
    button.save_typetree(tree)
    label = objects[-6129238833096444051].read_typetree()
    caption_id = label['m_GameObject']['m_PathID']
    caption = objects[caption_id]
    tree = caption.read_typetree()
    tree['m_IsActive'] = False
    caption.save_typetree(tree)
    payload = env.file.save(packer='original')
    after = {o.path_id: o for o in UnityPy.load(payload).objects}
    assert set(after) == set(before)
    changed = {p for p in before if sha(after[p].get_raw_data()) != before[p]}
    assert -448844550402408984 in changed and changed <= {-448844550402408984, caption_id}
    assert after[-448844550402408984].read_typetree()['m_IsActive']
    assert not after[caption_id].read_typetree()['m_IsActive']
    return payload

def main():
    assert not REPORT.exists()
    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    folder = ROOT/'releases'/BASE
    raw = (folder/'manifest.json').read_bytes()
    assert sha(raw) == BASE.split('-', 1)[1]
    base = json.loads(raw)
    old = {a['path']: a for a in base['assets']}
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder/'manifest.sig').read_bytes()), raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    payloads = {}
    for logical, patch in ((LUA, patch_lua), (VIP, patch_vip)):
        original = (ROOT/'blobs'/old[logical]['sha256']).read_bytes()
        assert sha(original) == old[logical]['sha256']
        payloads[logical] = patch(original)
    snapshot = copy.deepcopy(base)
    entries = {a['path']: a for a in snapshot['assets']}
    for path, payload in payloads.items():
        digest = sha(payload)
        entries[path] = dict(path=path, url='/updates/stable/blobs/'+digest, size=len(payload), sha256=digest)
        blob = ROOT/'blobs'/digest
        if blob.exists(): assert blob.read_bytes() == payload
        else: blob.write_bytes(payload)
    assert all(entries[p] == old[p] for p in old.keys()-payloads.keys())
    snapshot['assets'] = [entries[p] for p in sorted(entries)]
    fix, rollback = signed_release(snapshot, 125, private, public), signed_release(base, 126, private, public)
    for name, data, signature in (fix, rollback):
        target = ROOT/'releases'/name
        assert not target.exists()
        target.mkdir()
        (target/'manifest.json').write_bytes(data)
        (target/'manifest.sig').write_bytes(signature)
    result = dict(status='LOCAL_VALIDATED_CANDIDATE', base=BASE, release=fix[0], rollback=rollback[0],
        changedAssets={p: entries[p] for p in payloads}, resourceCount=len(entries),
        deltaBytes=sum(len(p) for p in payloads.values()), serviceChanged=False, playerSavesReset=False,
        guideTeachingHidden=True, caphShopButtonVisible=True, caphShopNativeClickRestored=True)
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    assert json.loads(REPORT.read_text(encoding='utf-8')) == result
    print(json.dumps(result, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()
