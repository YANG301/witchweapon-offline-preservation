"""Create a signed combat candidate, preserving the active resource snapshot."""
import base64
import copy
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import UnityPy

PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'android-client'), str(PROJECT / 'tools'),
               r'D:\Environment\VPS-SSH\packages313']
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import build_combat_weapon_repair as weapon

ROOT = PROJECT / '热更新测试/主线热更候选'
REPORT = PROJECT / '验收/战斗修复/发布.json'
BASE = weapon.BASE_SEQUENCE
VERSION = 153
LUA_PATH = 'assetbundle/lua/lua.ab'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_asset(logical, payload):
    sha = digest(payload)
    target = ROOT / 'blobs' / sha
    if target.exists():
        assert target.read_bytes() == payload
    else:
        target.write_bytes(payload)
    return dict(path=logical, url='/updates/stable/blobs/' + sha,
                size=len(payload), sha256=sha)


def main():
    assert (ROOT / 'current').read_text(encoding='utf-8').strip() == BASE
    folder = ROOT / 'releases' / BASE
    raw = (folder / 'manifest.json').read_bytes()
    assert digest(raw) == BASE.split('-', 1)[1]
    with zipfile.ZipFile(weapon.APK) as apk:
        public = serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((folder / 'manifest.sig').read_bytes()), raw,
                  padding.PKCS1v15(), hashes.SHA256())
    private = serialization.load_pem_private_key(
        (PROJECT / '.local/热更新密钥/签名私钥.pem').read_bytes(), password=None)
    assert private.public_key().public_numbers() == public.public_numbers()
    base = json.loads(raw)
    assert len(base['assets']) == 117
    updated = copy.deepcopy(base)
    asset = next(a for a in base['assets'] if a['path'] == LUA_PATH)
    env = UnityPy.load((ROOT / 'blobs' / asset['sha256']).read_bytes())
    before = {o.path_id: digest(o.get_raw_data()) for o in env.objects}
    obj, = [o for o in env.objects if o.type.name == 'TextAsset'
            and o.read_typetree().get('m_Name') == 'init.lua']
    tree = obj.read_typetree()
    script = tree['m_Script']
    assert 'WWR_COMBAT_RETARGET_READY' not in script
    assert 'ONLINE_FURNACE_REWARD_CHOICE_FAILED' not in script
    for name in ('init-combat-retarget.lua', 'init-furnace-reward-choice.lua'):
        patch = (PROJECT / 'android-client/lua' / name).read_text(encoding='utf-8')
        check_lua(patch)
        script += '\n\n' + patch.rstrip() + '\n'
    check_lua(script)
    for marker in ('WWR_RUNTIME_UI_READY 151', 'ONLINE_TASK_LIVE_READY 143',
                   'ONLINE_TASK_LOOT_READY 139', 'WWR_COMBAT_RETARGET_READY 153'):
        assert marker in script, marker
    tree['m_Script'] = script
    obj.save_typetree(tree)
    lua = env.file.save(packer='original')
    reread = UnityPy.load(lua)
    after = {o.path_id: digest(o.get_raw_data()) for o in reread.objects}
    assert {p for p in before if before[p] != after[p]} == {obj.path_id}
    changed = {LUA_PATH: write_asset(LUA_PATH, lua)}
    candidate = PROJECT / '验收/战斗修复/武器候选'
    spec = json.loads((candidate / 'combat-weapon-patch.json').read_text(encoding='utf-8'))
    spells = (candidate / 'spells.ab').read_bytes()
    assert digest(spells) == spec['candidateSpellSha256']
    changed[weapon.SPELL_PATH] = write_asset(weapon.SPELL_PATH, spells)
    updated['assets'] = [changed.get(a['path'], a) for a in base['assets']]
    assert not any(a['path'] == weapon.SPELL_PATH for a in base['assets'])
    updated['assets'].append(changed[weapon.SPELL_PATH])
    assert len(updated['assets']) == 118
    release = signed_release(updated, VERSION, private, public)
    rollback = signed_release(base, VERSION + 1, private, public)
    for name, data, sig in (release, rollback):
        target = ROOT / 'releases' / name
        target.mkdir()
        (target / 'manifest.json').write_bytes(data)
        (target / 'manifest.sig').write_bytes(sig)

    # Change one fixture response only. Saves and account/catalog data are not
    # inputs. Retain the former argument slots for clients awaiting this update.
    source = PROJECT / '验收/战斗修复/服务端基线/offline_responses.json'
    responses = json.loads(source.read_text(encoding='utf-8-sig'))
    assert digest(source.read_bytes()) == 'ad083d0024227bf3237cc282189641525b0195bfaa5b63fdd2af86f04d586b01'
    original = copy.deepcopy(responses)
    route = '/combat/role/info'
    old_role = base64.b64decode(responses[route]['base64'], validate=True)
    assert digest(old_role) == spec['baselineRoleSha256']
    cls = weapon.role_class()
    message = cls()
    message.ParseFromString(old_role)
    role, patches = weapon.repair_role(message)
    assert digest(role) == spec['candidateRoleSha256']
    responses[route]['base64'] = base64.b64encode(role).decode('ascii')
    assert {k for k in responses if responses[k] != original[k]} == {route}
    output = PROJECT / '构建/战斗修复/offline_responses.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(responses, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert json.loads(output.read_text(encoding='utf-8')) == responses
    report = dict(base=BASE, release=release[0], rollback=rollback[0],
                  changedAssets=changed, resourceCount=118,
                  fixture=str(output), fixtureSha256=digest(output.read_bytes()),
                  baseFixtureSha256=digest(source.read_bytes()),
                  status='LOCAL_VALIDATED_CANDIDATE',
                  weaponSpecification=spec,
                  deviceValidated=False)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('COMBAT_RELEASE_READY', release[0], 'delta', sum(a['size'] for a in changed.values()), flush=True)


if __name__ == '__main__':
    main()
