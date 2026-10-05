"""Build the reviewed CAPH-closure service overlay and guide-entry hot update."""
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
BASE = '121-54bd72d245c2a929e880632a61c53a41075d2cf1b38d51a73cf80986eea41da2'
APK = PROJECT / '构建/原始关卡候选/魔女兵器-在线本地双区服-v111-测试.apk'
BASE_JAR = PROJECT / '构建/原始关卡候选/正式服原始关卡发射器修正.jar'
BASE_JAR_SHA = '41f1dc0cf62f3ba307b2c0f98da59091ca98fd62ba3150e7810a2378bce4c249'
CLASSES = Path(r'D:\Environment\Java\temp\witch-optional-entries\classes')
JAR = PROJECT / '服务端候选/CAPH活动关闭修复.jar'
REPORT = PROJECT / '验收/入口显示修复/发布.json'
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
    assert MARKER not in original
    addition = (PROJECT / 'android-client/lua/init-optional-entry-visibility.lua').read_text(encoding='utf-8')
    script = original.rstrip('\n') + '\n\n' + addition.rstrip('\n') + '\n'
    check_lua(script)
    tree['m_Script'] = script
    target.save_typetree(tree)
    payload = env.file.save(packer='original')
    after = {o.path_id: o for o in UnityPy.load(payload).objects}
    assert set(after) == set(before)
    assert {p for p in before if sha(after[p].get_raw_data()) != before[p]} == {target.path_id}
    assert after[target.path_id].read_typetree()['m_Script'] == script
    assert 'WWR_PRESERVED_STAGE_MANIFEST_READY' in script and 'ONLINE_TASK_LIVE_READY 65' in script
    return payload

def patch_vip(raw):
    env = UnityPy.load(raw)
    objects = {o.path_id: o for o in env.objects}
    before = {p: sha(o.get_raw_data()) for p, o in objects.items()}
    button = objects[-448844550402408984]
    tree = button.read_typetree()
    assert tree['m_Name'] == 'GoShopbtn'
    tree['m_IsActive'] = False
    button.save_typetree(tree)
    label = objects[-6129238833096444051]
    tree = label.read_typetree()
    assert tree.get('mText')
    tree['m_Enabled'], tree['mColor']['a'] = 1, 1.0
    label.save_typetree(tree)
    payload = env.file.save(packer='original')
    after = {o.path_id: o for o in UnityPy.load(payload).objects}
    changed = {p for p in before if sha(after[p].get_raw_data()) != before[p]}
    assert changed and changed <= {-448844550402408984, -6129238833096444051}
    assert not after[-448844550402408984].read_typetree()['m_IsActive']
    assert after[-6129238833096444051].read_typetree()['m_Enabled'] == 1
    return payload

def build_jar():
    assert sha(BASE_JAR.read_bytes()) == BASE_JAR_SHA
    names = ['com/codex/witchweapon/CaphActivityAccess.class',
             'com/codex/witchweapon/VipShop.class',
             'com/codex/witchweapon/VipShop$Action.class']
    payload = {n: (CLASSES / n).read_bytes() for n in names}
    assert not JAR.exists()
    with zipfile.ZipFile(BASE_JAR) as old, zipfile.ZipFile(JAR, 'x') as new:
        new.comment = old.comment
        for entry in old.infolist(): new.writestr(entry, payload.get(entry.filename, old.read(entry.filename)))
    with zipfile.ZipFile(BASE_JAR) as old, zipfile.ZipFile(JAR) as new:
        assert old.namelist() == new.namelist()
        changed = [n for n in old.namelist() if old.read(n) != new.read(n)]
        assert set(changed) <= set(names) and names[0] in changed and names[1] in changed
        assert old.read('preserved_battle_catalog.json') == new.read('preserved_battle_catalog.json')
    return changed

def main():
    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    folder = ROOT / 'releases' / BASE
    raw = (folder / 'manifest.json').read_bytes()
    assert sha(raw) == BASE.split('-', 1)[1]
    base = json.loads(raw)
    old = {a['path']: a for a in base['assets']}
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
        vip = apk.read('assets/' + VIP) if VIP not in old else (ROOT / 'blobs' / old[VIP]['sha256']).read_bytes()
    public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw, padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key((PROJECT / '.local/热更新密钥/签名私钥.pem').read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    lua = (ROOT / 'blobs' / old[LUA]['sha256']).read_bytes()
    assert sha(lua) == old[LUA]['sha256']
    payloads = {LUA: patch_lua(lua), VIP: patch_vip(vip)}
    snapshot = copy.deepcopy(base)
    entries = {a['path']: a for a in snapshot['assets']}
    for path, payload in payloads.items():
        digest = sha(payload)
        entries[path] = dict(path=path, url='/updates/stable/blobs/' + digest, size=len(payload), sha256=digest)
        blob = ROOT / 'blobs' / digest
        if blob.exists(): assert blob.read_bytes() == payload
        else: blob.write_bytes(payload)
    assert all(entries[p] == old[p] for p in old.keys() - payloads.keys())
    snapshot['assets'] = [entries[p] for p in sorted(entries)]
    fix, rollback = signed_release(snapshot, 123, private, public), signed_release(base, 124, private, public)
    for name, data, signature in (fix, rollback):
        target = ROOT / 'releases' / name
        assert not target.exists()
        target.mkdir()
        (target / 'manifest.json').write_bytes(data)
        (target / 'manifest.sig').write_bytes(signature)
    classes = build_jar()
    result = dict(status='LOCAL_VALIDATED_CANDIDATE', base=BASE, release=fix[0], rollback=rollback[0],
        changedAssets={p: entries[p] for p in payloads}, resourceCount=len(entries),
        deltaBytes=sum(len(p) for p in payloads.values()), jar=str(JAR), jarSha256=sha(JAR.read_bytes()),
        baseJarSha256=BASE_JAR_SHA, changedJarEntries=classes, playerSavesReset=False,
        stageCatalogUnchanged=True, tests=['CaphActivityAccessSelfTest','StarShopTimeDataSelfTest','VipShopSelfTest'])
    REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert json.loads(REPORT.read_text(encoding='utf-8')) == result
    print(json.dumps(result, ensure_ascii=False), flush=True)

if __name__ == '__main__': main()
