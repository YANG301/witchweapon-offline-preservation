"""Replace the original registration contract in the preserved login prefab."""
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

PROJECT = signing.PROJECT
ROOT = signing.ROOT
BASE = '165-095173115a22dba291638276cf0aa16a5c03eb621d65c6a8f4234ba07a196535'
APK = PROJECT / '构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
LOGICAL = 'assetbundle/assets/resources/ui/prefab/login/loginmain.ab'
SOURCE_SHA = '34060106ab5f4e93c2b4336d1fe980ea6fcbefe79688f2fb66a6dcea6d26ea15'
OVERRIDE = PROJECT / 'android-client/resources-overrides/login-community-agreement.ab'
REPORT = PROJECT / '验收/社区约定热更新.json'
SEQUENCE = 167
SEGMENTS = ('noticeContent0', 'noticeContent123', 'noticeContent45', 'noticeContent67',
    'noticeContent8910', 'noticeContent11', 'noticeContent1213', 'noticeContent1415',
    'noticeContent16', 'noticeContent17', 'noticeContent181920', 'noticeContent212223',
    'noticeContent24252627', 'noticeContent2833', 'noticeContent34')
BODY_ROOT = 'LoginMain/GameClauseView/Center/NoticeContainer/ContentArea/Panel/GameObject/'


def patch(raw, notice):
    assert signing.sha(raw) == SOURCE_SHA
    env = UnityPy.load(raw)
    objects = {obj.path_id: obj for obj in env.objects}
    before = {pid: signing.sha(obj.get_raw_data()) for pid, obj in objects.items()}
    gos = {pid: obj.read_typetree() for pid, obj in objects.items() if obj.type.name == 'GameObject'}
    transforms = {pid: obj.read_typetree() for pid, obj in objects.items() if obj.type.name == 'Transform'}
    go_transforms = {t['m_GameObject']['m_PathID']: t for t in transforms.values()}

    def path(gid):
        t = go_transforms.get(gid)
        parent = t['m_Father']['m_PathID'] if t else 0
        prefix = path(transforms[parent]['m_GameObject']['m_PathID']) + '/' if parent in transforms else ''
        return prefix + gos[gid]['m_Name']

    labels = {}
    changed = set()
    title_found = False
    binding_found = False
    checkbox_count = 0
    for obj in env.objects:
        if obj.type.name != 'MonoBehaviour':
            continue
        tree = obj.read_typetree()
        gid = tree.get('m_GameObject', {}).get('m_PathID')
        if gid not in gos:
            continue
        node = path(gid)
        if 'mText' in tree and node.startswith(BODY_ROOT) and gos[gid]['m_Name'] in SEGMENTS:
            name = gos[gid]['m_Name']
            assert name not in labels and tree['mFontSize'] == 22 and tree['mWidth'] == 729
            assert tree['mOverflow'] == 3 and tree['mEncoding'] == 1 and tree['mMaxLineCount'] == 0
            labels[name] = (obj.path_id, gid)
            tree['mText'] = notice['Content'] if name == 'noticeContent0' else ''
            obj.save_typetree(tree)
            changed.add(obj.path_id)
        elif 'mText' in tree and node == 'LoginMain/GameClauseView/Center/NoticeContainer/noticeTitle':
            tree['mText'] = notice['Title']
            obj.save_typetree(tree)
            changed.add(obj.path_id)
            title_found = True
        elif node == 'LoginMain/GameClauseView' and 'noticeContent' in tree:
            assert tree['noticeContent']['m_PathID'] == 2402342928426932747
            tree['noticeContent']['m_PathID'] = 2125474441331690213
            obj.save_typetree(tree)
            changed.add(obj.path_id)
            binding_found = True
        elif 'mText' in tree and '游戏使用条款' in tree['mText']:
            assert 'GameClauseView/' not in node
            tree['mText'] = tree['mText'].replace('游戏使用条款', '用户协议')
            obj.save_typetree(tree)
            changed.add(obj.path_id)
            checkbox_count += 1
    assert set(labels) == set(SEGMENTS) and title_found and binding_found
    assert labels['noticeContent0'][0] == 2125474441331690213
    assert checkbox_count == 13, checkbox_count
    for name in SEGMENTS[1:]:
        gid = labels[name][1]
        assert gos[gid]['m_IsActive'] is True
        gos[gid]['m_IsActive'] = False
        objects[gid].save_typetree(gos[gid])
        changed.add(gid)
    result = env.file.save(packer='original')
    after = {obj.path_id: obj for obj in UnityPy.load(result).objects}
    assert set(after) == set(before)
    assert {pid for pid in before if before[pid] != signing.sha(after[pid].get_raw_data())} == changed
    assert after[labels['noticeContent0'][0]].read_typetree()['mText'] == notice['Content']
    for name in SEGMENTS[1:]:
        label, gid = labels[name]
        assert not after[gid].read_typetree()['m_IsActive']
        assert after[label].read_typetree()['mText'] == ''
    return result, dict(changedObjects=len(changed), hiddenOldContractSegments=14,
        bodyFontSize=22, bodyOverflow='ResizeHeight', easterEggFontScale=0.75,
        preservedScrollView=True, changedRegistrationLabels=checkbox_count)


def build():
    notices = json.loads(json.loads((PROJECT/'legacy-server/resources/offline_responses.json').read_text(
        encoding='utf-8'))['/Notice/gameContent']['body'])
    notice = notices[-1]
    assert notice['ID'] == 5 and '[sub]彩蛋小字：' in notice['Content']
    with zipfile.ZipFile(APK) as apk:
        original = apk.read('assets/' + LOGICAL)
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    candidate, patch_info = patch(original, notice)
    raw = (ROOT/'releases'/BASE/'manifest.json').read_bytes()
    assert signing.sha(raw) == BASE.split('-', 1)[1]
    public.verify(base64.b64decode((ROOT/'releases'/BASE/'manifest.sig').read_bytes()), raw,
        padding.PKCS1v15(), hashes.SHA256())
    baseline = json.loads(raw)
    assert len(baseline['assets']) == 119 and not any(a['path'] == LOGICAL for a in baseline['assets'])
    private = serialization.load_pem_private_key(signing.KEY.read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    snapshots = []
    assets = []
    for offset, payload in enumerate((candidate, original)):
        digest = signing.sha(payload)
        asset = dict(path=LOGICAL, url='/updates/stable/blobs/' + digest,
                     size=len(payload), sha256=digest)
        snapshot = copy.deepcopy(baseline)
        snapshot['assets'].append(asset)
        snapshots.append(signing.signed_release(snapshot, SEQUENCE + offset, private, public))
        assets.append(asset)
    for name, _, _ in snapshots:
        assert not (ROOT/'releases'/name).exists()
    for payload, asset in zip((candidate, original), assets):
        blob = ROOT/'blobs'/asset['sha256']
        if blob.exists():
            assert blob.read_bytes() == payload
        else:
            blob.write_bytes(payload)
    for name, manifest, signature in snapshots:
        folder = ROOT/'releases'/name
        folder.mkdir()
        (folder/'manifest.json').write_bytes(manifest)
        (folder/'manifest.sig').write_bytes(signature)
    OVERRIDE.write_bytes(candidate)
    report = dict(status='SIGNED_CANDIDATE', base=BASE, release=snapshots[0][0],
        rollback=snapshots[1][0], changedAssets=[LOGICAL], changedAsset=assets[0],
        rollbackAsset=assets[1], deltaBytes=len(candidate), override=str(OVERRIDE),
        sourceBundleSha256=SOURCE_SHA, sourceApk=str(APK), agreementNoticeId=5,
        originalScrollLayoutPreserved=True, physicalDeviceValidated=False, **patch_info)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert json.loads(REPORT.read_text(encoding='utf-8')) == report
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    build()
