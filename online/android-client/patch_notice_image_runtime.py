"""Build the original announcement image plus a genuine 10px agreement footer.

No server data or release pointer is changed here. The release composer supplies
reviewed APK/bundle bytes and signs the returned assets with its usual key.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import zipfile

from PIL import Image
import UnityPy

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'lua/init-notice-image-runtime.lua'
IMAGE_LOGICAL = 'assetbundle/config/community_notice_image.ab'
NOTICE_LOGICAL = 'assetbundle/assets/resources/ui/prefab/uiprefab/uiannouncement.ab'
TEXTURE_NAME = 'assets/community/notice_thanks_avatars.png'
TEMPLATE = 'assets/assetbundle/assets/resources/ui/uiimage/guide/1800_1200_white.ab'
MARKER = "local KEY = '__WWRCommunityNoticeImageV1'"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def image_bundle(apk_path: Path, image_path: Path) -> tuple[bytes, dict]:
    """Put the supplied final avatar collage in an independent Texture2D AB."""
    with zipfile.ZipFile(apk_path) as apk:
        raw = apk.read(TEMPLATE)
    env = UnityPy.load(raw)
    objects = list(env.objects)
    assert len(objects) == 2 and {o.type.name for o in objects} == {'Texture2D', 'AssetBundle'}
    texture_obj = next(o for o in objects if o.type.name == 'Texture2D')
    bundle_obj = next(o for o in objects if o.type.name == 'AssetBundle')
    with Image.open(image_path) as opened:
        image = opened.convert('RGBA')
    assert 1 <= image.width <= 2048 and 1 <= image.height <= 4096
    texture = texture_obj.read()
    texture.m_Name = 'notice_thanks_avatars'
    texture.set_image(image, target_format=4, mipmap_count=1)
    texture.m_IsReadable = False
    texture.m_TextureSettings.m_WrapU = 1
    texture.m_TextureSettings.m_WrapV = 1
    texture.save()
    tree = bundle_obj.read_typetree()
    container = tree['m_Container'][0][1]
    tree['m_Container'] = [(TEXTURE_NAME, container)]
    tree['m_Name'] = IMAGE_LOGICAL.removeprefix('assetbundle/')
    tree['m_AssetBundleName'] = tree['m_Name'].removesuffix('.ab')
    tree['m_Dependencies'] = []
    bundle_obj.save_typetree(tree)
    # Direct loading avoids GLoader dependencies. Give the serialized CAB a
    # different identity so Unity never mistakes it for the white template.
    old_cab = texture_obj.assets_file.name
    new_cab = 'CAB-' + sha(image.tobytes())[:32]
    assert old_cab in env.file.files
    env.file.files[new_cab] = env.file.files.pop(old_cab)
    texture_obj.assets_file.name = new_cab
    result = env.file.save(packer='original')
    reopened = UnityPy.load(result)
    restored = next(o for o in reopened.objects if o.type.name == 'Texture2D').read()
    assert restored.image.convert('RGBA').tobytes() == image.tobytes()
    assert list(reopened.container) == [TEXTURE_NAME]
    return result, dict(width=image.width, height=image.height, texture='RGBA32',
        sha256=sha(result), size=len(result), logical=IMAGE_LOGICAL)


def notice_prefab(raw: bytes) -> tuple[bytes, dict]:
    """Add one small original-font label under the existing scrolling panel."""
    env = UnityPy.load(raw)
    objects = {o.path_id: o for o in env.objects}
    before = {pid: sha(o.get_raw_data()) for pid, o in objects.items()}
    body_go_id, body_t_id, body_label_id = -2021124163472946654, -5517638454805760851, -638330929342339070
    parent_id = 6962217885552415901
    assert objects[body_go_id].read_typetree()['m_Name'] == 'label'
    assert objects[body_t_id].read_typetree()['m_Father']['m_PathID'] == parent_id
    assert objects[body_label_id].read_typetree()['mFontSize'] == 28
    new_ids = (7000000000000000171, 7000000000000000172, 7000000000000000173)
    assert not any(pid in objects for pid in new_ids)
    go_id, trans_id, label_id = new_ids
    cloned_go = copy.deepcopy(objects[body_go_id].read_typetree())
    cloned_go.update(m_Name='UserAgreementFinePrint', m_IsActive=False,
        m_Component=[{'component': {'m_FileID': 0, 'm_PathID': trans_id}},
            {'component': {'m_FileID': 0, 'm_PathID': label_id}}])
    cloned_t = copy.deepcopy(objects[body_t_id].read_typetree())
    cloned_t['m_GameObject']['m_PathID'] = go_id
    cloned_t['m_LocalPosition']['y'] = -1000.0
    cloned_label = copy.deepcopy(objects[body_label_id].read_typetree())
    cloned_label['m_GameObject']['m_PathID'] = go_id
    cloned_label.update(mText='', mFontSize=10, mDepth=2, mHeight=40,
        mWidth=911, mOverflow=3, mEncoding=1, mSpacingY=2,
        autoResizeBoxCollider=0, mMaxLineCount=0, mPivot=0)
    cloned_label['mColor'] = dict(r=0.74, g=0.79, b=0.83, a=1.0)
    # Native UIRect follows the body widget's bottom edge as ResizeHeight updates
    # its size. Keep the bottom anchor empty to preserve ResizeHeight, rather
    # than continuously searching/repositioning the agreement through Lua.
    for name, relative, absolute in (('leftAnchor', 0.0, 0),
            ('rightAnchor', 1.0, 0), ('topAnchor', 0.0, -18)):
        cloned_label[name] = dict(target={'m_FileID': 0, 'm_PathID': body_t_id},
            relative=relative, absolute=absolute)
    cloned_label['bottomAnchor']['target']['m_PathID'] = 0
    cloned_label['updateAnchors'] = 1
    for source_id, target_id, tree in ((body_go_id, go_id, cloned_go),
            (body_t_id, trans_id, cloned_t), (body_label_id, label_id, cloned_label)):
        cloned = copy.copy(objects[source_id])
        cloned.path_id = target_id
        cloned.assets_file.objects[target_id] = cloned
        cloned.save_typetree(tree)
    parent = objects[parent_id].read_typetree()
    parent['m_Children'].append({'m_FileID': 0, 'm_PathID': trans_id})
    objects[parent_id].save_typetree(parent)
    image_id = -6757030237541819559
    image = objects[image_id].read_typetree()
    assert image['mPivot'] == 0 and image['mWidth'] == 946
    image['keepAspectRatio'] = 0
    objects[image_id].save_typetree(image)
    bundle_obj = next(o for o in env.objects if o.type.name == 'AssetBundle')
    tree = bundle_obj.read_typetree()
    assert len(tree['m_Container']) == 1
    tree['m_PreloadTable'].extend({'m_FileID': 0, 'm_PathID': pid} for pid in new_ids)
    tree['m_Container'][0][1]['preloadSize'] += len(new_ids)
    bundle_obj.save_typetree(tree)
    result = env.file.save(packer='original')
    reopened = {o.path_id: o for o in UnityPy.load(result).objects}
    assert set(reopened) == set(before) | set(new_ids)
    assert {pid for pid in before if before[pid] != sha(reopened[pid].get_raw_data())} == {parent_id, image_id, bundle_obj.path_id}
    assert reopened[label_id].read_typetree()['mFontSize'] == 10
    assert reopened[go_id].read_typetree()['m_Name'] == 'UserAgreementFinePrint'
    return result, dict(addedObjects=3, changedOriginalObjects=3, footerFontSize=10,
        originalImageControlPreserved=True, sha256=sha(result), size=len(result), logical=NOTICE_LOGICAL)


def lua_bundle(raw: bytes) -> tuple[bytes, dict]:
    """Append the image/footer handler, preserving every prior runtime fix."""
    env = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    targets = [o for o in env.objects if o.type.name == 'TextAsset'
        and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1
    target = targets[0]
    tree = target.read_typetree()
    source = tree['m_Script']
    block = SCRIPT.read_text(encoding='utf-8').rstrip('\n')
    assert MARKER in block and source.count(MARKER) == 0
    tree['m_Script'] = source.rstrip('\n') + '\n\n' + block + '\n'
    target.save_typetree(tree)
    result = env.file.save(packer='original')
    reopened = list(UnityPy.load(result).objects)
    assert {o.path_id for o in reopened} == set(before)
    assert {o.path_id for o in reopened if before[o.path_id] != sha(o.get_raw_data())} == {target.path_id}
    assert next(o for o in reopened if o.path_id == target.path_id).read_typetree()['m_Script'] == tree['m_Script']
    return result, dict(changedObjects=1, priorLuaPreserved=True, sha256=sha(result), size=len(result))


def append_agreement_lua(raw: bytes, fulltext: str) -> tuple[bytes, dict]:
    """Update the APK-owned login contract through Lua, never hotload LoginMain."""
    text = fulltext.strip()
    at = text.rfind('\n用户阅读本协议后')
    assert at > 0, 'The agreement requires one plain final fine-print line'
    body, footer = text[:at].rstrip(), text[at + 1:].strip()
    assert '\n' not in footer and footer.startswith('用户阅读本协议后')
    assert '彩蛋' not in footer and '[sub]' not in footer

    def lua_string(value: str) -> str:
        level = '='
        while ']' + level + ']' in value:
            level += '='
        return '[' + level + '[' + value + ']' + level + ']'

    block = (HERE / 'lua/init-user-agreement-runtime.lua').read_text(encoding='utf-8')
    block = block.replace('@@AGREEMENT_BODY@@', lua_string(body))
    block = block.replace('@@AGREEMENT_FOOTER@@', lua_string(footer)).rstrip('\n')
    assert '@@AGREEMENT_' not in block
    marker = "local KEY = '__WWRUserAgreementRuntimeV1'"
    assert marker in block and 'FindObjectOfType' not in block
    env = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    targets = [o for o in env.objects if o.type.name == 'TextAsset'
        and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1
    target = targets[0]
    tree = target.read_typetree()
    source = tree['m_Script']
    assert marker not in source
    tree['m_Script'] = source.rstrip('\n') + '\n\n' + block + '\n'
    target.save_typetree(tree)
    result = env.file.save(packer='original')
    reopened = list(UnityPy.load(result).objects)
    assert {o.path_id for o in reopened} == set(before)
    assert {o.path_id for o in reopened if before[o.path_id] != sha(o.get_raw_data())} == {target.path_id}
    restored = next(o for o in reopened if o.path_id == target.path_id).read_typetree()['m_Script']
    assert restored == tree['m_Script'] and body in restored and footer in restored
    return result, dict(changedObjects=1, priorLuaPreserved=True, bodyFontSize=22,
        footerFontSize=10, hiddenOldContractSegments=13, usesStaticLoginInstance=True,
        loginAssetHotload=False, agreementCharacters=len(text), sha256=sha(result), size=len(result))


def replace_notice_runtime(raw: bytes) -> tuple[bytes, dict]:
    """Replace the terminal notice/protocol blocks, preserving the prior fixes."""
    env = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    targets = [o for o in env.objects if o.type.name == 'TextAsset'
        and o.read_typetree().get('m_Name') == 'init.lua']
    assert len(targets) == 1
    target = targets[0]
    tree = target.read_typetree()
    source = tree['m_Script']
    header = '-- Reuse the original announcement image and scrolling content.'
    assert source.count(MARKER) == 1 and source.count(header) == 1
    start = source.index(header)
    prefix, previous = source[:start], source[start:]
    assert prefix.endswith('\n\n') and previous.endswith('\nend\n')
    assert previous.count("__WWRUserAgreementRuntimeV1") <= 1
    assert previous.count('do\n') >= 1 and 'tolua.loadassembly(\'UnityEngine.AssetBundleModule\')' in previous
    revised = SCRIPT.read_text(encoding='utf-8').rstrip('\n') + '\n'
    assert MARKER in revised and "pcall(function() tolua.loadassembly('UnityEngine.AssetBundleModule') end)" in revised
    tree['m_Script'] = prefix + revised
    target.save_typetree(tree)
    result = env.file.save(packer='original')
    reopened = list(UnityPy.load(result).objects)
    assert {o.path_id for o in reopened} == set(before)
    assert {o.path_id for o in reopened if before[o.path_id] != sha(o.get_raw_data())} == {target.path_id}
    restored = next(o for o in reopened if o.path_id == target.path_id).read_typetree()['m_Script']
    assert restored == tree['m_Script'] and restored[:start] == prefix
    return result, dict(changedObjects=1, replacedTerminalNoticeBlock=True,
        prefixBytesPreserved=len(prefix.encode('utf-8')), optionalUnityAssemblyModules=True,
        sha256=sha(result), size=len(result))


def append_login_email_lua(raw: bytes) -> tuple[bytes, dict]:
    """Reuse the bounded UTF-8 JSON parser, adding nested error-object support."""
    settings = (HERE/'lua/init-settings-profile.lua').read_text(encoding='utf-8')
    start = settings.index('    local function decodeEmailJson(body)')
    end = settings.index('    local function emailObject(', start)
    decoder = settings[start:end].strip().replace('local function decodeEmailJson(body)', 'function(body)', 1)
    start = decoder.index("        whitespace()\n        if body:sub(position, position) ~= '{'")
    decoder = decoder[:start] + '''        local readObject
        local function readValue(depth)
            whitespace()
            local first = body:sub(position, position)
            if first == '"' then return readString() end
            if first == '{' then return readObject(depth + 1) end
            if body:sub(position, position + 3) == 'true' then position = position + 4; return true end
            if body:sub(position, position + 4) == 'false' then position = position + 5; return false end
            if body:sub(position, position + 3) == 'null' then position = position + 4; return nil end
            return readNumber()
        end
        readObject = function(depth)
            if depth > 4 then error('JSON object nesting limit') end
            if body:sub(position, position) ~= '{' then error('Expected email JSON object') end
            position = position + 1
            whitespace()
            local result, seen = {}, {}
            if body:sub(position, position) == '}' then position = position + 1; return result end
            while true do
                local key = readString()
                if seen[key] then error('Duplicate email JSON key') end
                seen[key] = true
                whitespace()
                if body:sub(position, position) ~= ':' then error('Expected JSON colon') end
                position = position + 1
                result[key] = readValue(depth)
                whitespace()
                local separator = body:sub(position, position)
                position = position + 1
                if separator == '}' then return result end
                if separator ~= ',' then error('Expected JSON object separator') end
                whitespace()
            end
        end
        whitespace()
        local result = readObject(0)
        whitespace()
        if position ~= length + 1 then error('Unexpected trailing JSON data') end
        return result
    end'''
    block = (HERE/'lua/init-login-email-recovery.lua').read_text(encoding='utf-8')
    assert block.count('@@EMAIL_JSON_DECODER@@') == 1
    block = block.replace('@@EMAIL_JSON_DECODER@@', decoder).rstrip('\n')
    env = UnityPy.load(raw)
    target, = [o for o in env.objects if o.type.name == 'TextAsset'
        and o.read_typetree().get('m_Name') == 'init.lua']
    tree = target.read_typetree()
    assert '__WWRLoginEmailRecoveryV1' not in tree['m_Script']
    before = {o.path_id: sha(o.get_raw_data()) for o in env.objects}
    script = tree['m_Script'].rstrip('\n')+'\n\n'+block+'\n'
    from build_preserved_stage_assets import check_lua
    check_lua(script)
    tree['m_Script'] = script
    target.save_typetree(tree)
    result = env.file.save(packer='original')
    reopened = {o.path_id: o for o in UnityPy.load(result).objects}
    assert set(reopened) == set(before)
    assert {p for p in before if sha(reopened[p].get_raw_data()) != before[p]} == {target.path_id}
    assert reopened[target.path_id].read_typetree()['m_Script'] == script
    return result, dict(luaSyntaxVerified=True, originalLoginPrefabPreserved=True,
        emailRecovery=True, phoneEntriesHidden=True, agreementDefaultChecked=True,
        agreementClosingClick=114, agreementSilentClicks=[14,113], size=len(result), sha256=sha(result))
