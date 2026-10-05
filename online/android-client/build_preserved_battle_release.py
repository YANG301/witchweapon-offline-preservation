"""Sign the reviewed original-stage overlay and its complete rollback snapshot."""
from pathlib import Path
import base64
import copy
import hashlib
import json
import sys
import zipfile
import build_settlement_levelup_hotupdate as signing

ROOT = signing.ROOT
PLAN = signing.PROJECT / '热更新测试/原始关卡候选/patch-plan.json'
BASE = '119-b238404543a1718a7090e2e00d116d42ca98dcca071449510620983ae708c899'

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def build(sequence=121):
    sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(signing.APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    folder = ROOT / 'releases' / BASE
    raw = (folder / 'manifest.json').read_bytes()
    assert digest(raw) == BASE.split('-', 1)[1]
    public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw,
                  padding.PKCS1v15(), hashes.SHA256())
    original = json.loads(raw)
    plan = json.loads(PLAN.read_text(encoding='utf-8'))
    assert plan['baseReleaseSha256'] == digest(raw)
    assert plan['preservedStages'] == 247 and plan['unchangedMissingStages'] == 50
    assert len(plan['assets']) == 42 and not plan['maps']['unresolvedArchiveReferences']
    private = serialization.load_pem_private_key(signing.KEY.read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    snapshot = copy.deepcopy(original)
    entries = {item['path']: item for item in snapshot['assets']}
    old = {item['path']: item for item in original['assets']}
    changed = set()
    for item in plan['assets']:
        payload = Path(item['candidatePath']).read_bytes()
        assert digest(payload) == item['sha256'] and len(payload) == item['size']
        path = item['path']
        assert path.startswith('assetbundle/') and path.endswith('.ab') and '..' not in path
        entries[path] = dict(path=path, url='/updates/stable/blobs/' + item['sha256'],
                             size=item['size'], sha256=item['sha256'])
        target = ROOT / 'blobs' / item['sha256']
        if target.exists():
            assert target.read_bytes() == payload
        else:
            target.write_bytes(payload)
        changed.add(path)
    assert all(entries[p] == old[p] for p in old.keys() - changed)
    snapshot['assets'] = [entries[p] for p in sorted(entries)]
    assert len(entries) < 256 and sum(i['size'] for i in entries.values()) < 512 * 1024**2
    fix = signing.signed_release(snapshot, sequence, private, public)
    rollback = signing.signed_release(original, sequence + 1, private, public)
    for name, manifest, signature in (fix, rollback):
        directory = ROOT / 'releases' / name
        directory.mkdir(exist_ok=True)
        for part, payload in (('manifest.json', manifest), ('manifest.sig', signature)):
            path = directory / part
            if path.exists():
                assert path.read_bytes() == payload
            else:
                path.write_bytes(payload)
    result = dict(status='signed_candidate_not_published', base=BASE, release=fix[0],
                  rollback=rollback[0], changedAssets=sorted(changed),
                  resourceCount=len(entries), deltaBytes=plan['payloadBytes'])
    report = signing.PROJECT / '验收/原始关卡恢复/签名资源.json'
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert json.loads(report.read_text(encoding='utf-8')) == result
    print(json.dumps(result, ensure_ascii=False))
    return result

if __name__ == '__main__':
    build()
