"""Compose the complete notice image/formal agreement update on release 169."""
import base64
import copy
import json
from pathlib import Path
import sys
import zipfile

import UnityPy
import build_settlement_levelup_hotupdate as signing
import patch_notice_image_runtime as media

sys.path.insert(0, r'D:\Environment\VPS-SSH\packages313')
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

PROJECT, ROOT = signing.PROJECT, signing.ROOT
BASE = '169-65d797617e2a9d8215804a9d4193a8bd282269329717a7132aaa4306242a7ad1'
APK = PROJECT/'构建/战斗效果修复/魔女兵器-在线本地双区服-v123-测试.apk'
REPORT = PROJECT/'验收/公告图文与正式协议热更新.json'
LOGIN = 'assetbundle/assets/resources/ui/prefab/login/loginmain.ab'
LUA = 'assetbundle/lua/lua.ab'
IMAGE = Path('E:/Desktop/魔女兵器公告素材/感谢名单-测试群成员.png')


def patch_login(raw, full_text):
    body, tail = full_text.rsplit('\n\n', 1)
    assert tail.startswith('用户阅读本协议后') and '彩蛋' not in full_text
    env = UnityPy.load(raw)
    objects = {o.path_id:o for o in env.objects}
    before = {p:signing.sha(o.get_raw_data()) for p,o in objects.items()}
    main_id, footer_id, footer_go = 2125474441331690213,2402342928426932747,-6984029351694472991
    body_transform = 431296148559629588
    main = objects[main_id].read_typetree()
    assert main['mFontSize'] == 22 and main['mOverflow'] == 3
    main['mText'] = body
    objects[main_id].save_typetree(main)
    footer = objects[footer_id].read_typetree()
    assert footer['mText'] == ''
    footer.update(mText=tail, mFontSize=10, mHeight=24, mWidth=729, mPivot=0,
        mOverflow=3, mMaxLineCount=0, mEncoding=1)
    footer['topAnchor'] = dict(target=dict(m_FileID=0,m_PathID=body_transform),relative=0.0,absolute=-18)
    footer['leftAnchor'] = dict(target=dict(m_FileID=0,m_PathID=body_transform),relative=0.0,absolute=0)
    footer['rightAnchor'] = dict(target=dict(m_FileID=0,m_PathID=body_transform),relative=1.0,absolute=0)
    footer['bottomAnchor']['target']['m_PathID'] = 0
    objects[footer_id].save_typetree(footer)
    go = objects[footer_go].read_typetree()
    assert not go['m_IsActive'] and go['m_Name'] == 'noticeContent123'
    go['m_IsActive'] = True
    objects[footer_go].save_typetree(go)
    payload = env.file.save(packer='original')
    reopened = {o.path_id:o for o in UnityPy.load(payload).objects}
    assert set(reopened) == set(before)
    assert {p for p in before if before[p] != signing.sha(reopened[p].get_raw_data())} == {main_id,footer_id,footer_go}
    assert reopened[main_id].read_typetree()['mText'] == body
    assert reopened[footer_id].read_typetree() == footer
    assert reopened[footer_go].read_typetree()['m_IsActive']
    return payload, dict(changedObjects=3, bodyFontSize=22, footerFontSize=10,
        footerAnchor='body bottom, automatic height', registrationTitle='用户协议')


def build():
    raw = (ROOT/'releases'/BASE/'manifest.json').read_bytes()
    assert signing.sha(raw) == BASE.split('-',1)[1]
    with zipfile.ZipFile(APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
        public.verify(base64.b64decode((ROOT/'releases'/BASE/'manifest.sig').read_bytes()),
            raw, padding.PKCS1v15(), hashes.SHA256())
        baseline = json.loads(raw)
        original = {a['path']:a for a in baseline['assets']}
        assert len(original) == 120
        def source(path):
            if path in original:
                asset = original[path]
                data = (ROOT/'blobs'/asset['sha256']).read_bytes()
                assert signing.sha(data) == asset['sha256']
                return data
            return apk.read('assets/'+path)
        fixture = json.loads((PROJECT/'legacy-server/resources/offline_responses.json').read_text(encoding='utf-8'))
        agreement = json.loads(fixture['/Notice/gameContent']['body'])[4]['Content']
        login, login_info = patch_login(source(LOGIN), agreement)
        notice, notice_info = media.notice_prefab(source(media.NOTICE_LOGICAL))
        lua, lua_info = media.lua_bundle(source(LUA))
    texture, texture_info = media.image_bundle(APK, IMAGE)
    patches = {LOGIN:login, media.NOTICE_LOGICAL:notice, LUA:lua, media.IMAGE_LOGICAL:texture}
    snapshot = copy.deepcopy(baseline)
    changed = []
    for path, data in patches.items():
        digest = signing.sha(data)
        asset = dict(path=path,url='/updates/stable/blobs/'+digest,sha256=digest,size=len(data))
        found = next((a for a in snapshot['assets'] if a['path']==path),None)
        if found is None: snapshot['assets'].append(asset)
        else: found.update(asset)
        changed.append(asset)
    assert len(snapshot['assets']) == 122
    assert {a['path'] for a in snapshot['assets']} == set(original)|{media.NOTICE_LOGICAL,media.IMAGE_LOGICAL}
    assert all(a == original[a['path']] for a in snapshot['assets'] if a['path'] not in patches)
    private = serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    releases = (signing.signed_release(snapshot,171,private,public), signing.signed_release(baseline,172,private,public))
    for name,_,_ in releases: assert not (ROOT/'releases'/name).exists()
    for data,asset in zip(patches.values(),changed):
        blob = ROOT/'blobs'/asset['sha256']
        if blob.exists(): assert blob.read_bytes() == data
        else: blob.write_bytes(data)
    for name,manifest,signature in releases:
        folder = ROOT/'releases'/name; folder.mkdir()
        (folder/'manifest.json').write_bytes(manifest)
        (folder/'manifest.sig').write_bytes(signature)
    overrides = PROJECT/'android-client/resources-overrides'
    (overrides/'login-community-agreement.ab').write_bytes(login)
    (overrides/'notice-community-image.ab').write_bytes(notice)
    (overrides/'community-notice-image.ab').write_bytes(texture)
    record = dict(status='SIGNED_CANDIDATE',base=BASE,release=releases[0][0],rollback=releases[1][0],
        changedAssets=changed,totalAssets=122,sourceApk=str(APK),sourceImage=str(IMAGE),
        imageMembers=12,excludedMember='YANG301',deltaBytes=sum(a['size'] for a in changed),
        login=login_info,notice=notice_info,lua=lua_info,image=texture_info,
        physicalDeviceValidated=False,unchangedOtherAssets=118)
    REPORT.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False),flush=True)


if __name__ == '__main__': build()
