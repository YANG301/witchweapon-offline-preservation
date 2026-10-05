"""Build the reviewed task-only Java overlay and original reward-flow Lua release."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import UnityPy
from build_preserved_stage_assets import check_lua
from build_settlement_levelup_hotupdate import signed_release

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT/'热更新测试/主线热更候选'
BASE = '125-4aac6ed62f4a83c4efa0f421f9fe9314c851911f0602450a2b6f765363082832'
BASE_JAR = PROJECT/'服务端候选/CAPH活动关闭修复.jar'
BASE_JAR_SHA = '08741e03fc5a0301d8b489b015622feba21c4d1b60190001da0440ffec989e4a'
APK = PROJECT/'构建/入口显示修复/魔女兵器-在线本地双区服-v113-测试.apk'
JAR = PROJECT/'服务端候选/任务系统完整修复.jar'
REPORT = PROJECT/'验收/任务系统完整修复/发布.json'
CLASSES = Path(r'D:\Environment\Java\temp\witch-task-v127\classes')
JAVA = Path(r'D:\Environment\Java\jdk8\bin')
JSON_JAR = Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
CLASS_NAMES = ('LocalDaily','ProgressionTasks','CosmeticAchievements','TaskRewards',
               'LocalSave','GuildStore','StandaloneServer')
LOGICAL = 'assetbundle/lua/lua.ab'
LIVE_MARKER = '-- Refresh every original task entry and serialize single/batch reward clicks.'
LOOT_MARKER = '-- The preserved ARM64 UserInfoHelper.LootToDrawResultData emits LootGuildInc'
NEXT_MARKER = '-- Restore the original ShopItemInfo slider after the offline'

def sha(raw): return hashlib.sha256(raw).hexdigest()

def released_local_save(source):
    # The working source also contains an unreleased stone-slate prototype.
    # It is absent from the pinned live JAR; do not activate it in a task fix.
    blocks = [
        '''        // A late unsettled CSC request must not close or reward a newly
        // entered stone slate. Already committed CSC retries above are read-only.
        if(state.optBoolean("active",false) &&
            StoneSlateBattle.contains(state.optLong("activeStage",0)))
            throw new IOException("Maze settlement superseded by stone slate");
''',
        '''        if(path.equals("/challenge/combat/victory") || path.equals("/challenge/combat/cancel")){
            StoneSlateBattle.Settlement settlement=StoneSlateBattle.bundled().settle(state,args,now,
                path.equals("/challenge/combat/cancel"));
            if(settlement.next!=null)commit(settlement.next);
            return settlement.response;
        }
''',
        '''            if(path.equals("/challenge/combat/role/info") &&
                StoneSlateBattle.contains(state.optLong("activeStage",0)))
                return StoneSlateBattle.bundled().role(state,args,seed,catalog);
''',
        '''            r.set(117,r.number(117,0)|StoneSlateBattle.challengeBits(state));
''',
        '''            if(StoneSlateBattle.contains(stage)){
                JSONObject next=StoneSlateBattle.bundled().begin(state,stage,args,now);
                if(next!=state)commit(next);
                return seed;
            }
''']
    for block in blocks:
        assert source.count(block)==1
        source=source.replace(block,'')
    source=source.replace('return StoneSlateBattle.bundled().progress(progress,state);','return progress;')
    assert 'StoneSlateBattle' not in source
    return source

def build_jar():
    assert sha(BASE_JAR.read_bytes()) == BASE_JAR_SHA and not JAR.exists()
    CLASSES.mkdir(parents=True, exist_ok=True)
    sources = [PROJECT/'legacy-server/src/com/codex/witchweapon'/f'{n}.java' for n in CLASS_NAMES]
    source_folder=CLASSES.parent/'source';source_folder.mkdir(exist_ok=True)
    local_save=source_folder/'LocalSave.java'
    local_save.write_text(released_local_save(sources[4].read_text(encoding='utf-8')),encoding='utf-8')
    sources[4]=local_save
    subprocess.run([str(JAVA/'javac.exe'),'-J-Dfile.encoding=UTF-8','-encoding','UTF-8',
        '-source','8','-target','8','-cp',str(BASE_JAR)+';'+str(JSON_JAR),'-d',str(CLASSES),
        *map(str,sources)],check=True)
    payload = {}
    for path in CLASSES.rglob('*.class'):
        relative = path.relative_to(CLASSES).as_posix()
        assert relative.startswith('com/codex/witchweapon/')
        assert relative.split('/')[-1].split('$')[0].split('.')[0] in CLASS_NAMES
        payload[relative] = path.read_bytes()
    assert all('com/codex/witchweapon/'+n+'.class' in payload for n in CLASS_NAMES)
    with zipfile.ZipFile(BASE_JAR) as old, zipfile.ZipFile(JAR,'x') as new:
        new.comment = old.comment
        original = set(old.namelist())
        for entry in old.infolist(): new.writestr(entry,payload.get(entry.filename,old.read(entry.filename)))
        for name in sorted(payload.keys()-original): new.writestr(name,payload[name])
    with zipfile.ZipFile(BASE_JAR) as old, zipfile.ZipFile(JAR) as new:
        changed = [n for n in new.namelist() if n not in original or old.read(n)!=new.read(n)]
        assert set(changed) <= payload.keys()
        assert old.read('preserved_battle_catalog.json') == new.read('preserved_battle_catalog.json')
    return changed

def patch_lua(raw):
    env = UnityPy.load(raw)
    before = {o.path_id:sha(o.get_raw_data()) for o in env.objects}
    target, = [o for o in env.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    tree = target.read_typetree(); original = tree['m_Script']
    for marker in (LIVE_MARKER,LOOT_MARKER,NEXT_MARKER): assert original.count(marker)==1
    start, middle, end = [original.index(m) for m in (LIVE_MARKER,LOOT_MARKER,NEXT_MARKER)]
    assert start < middle < end
    live = (PROJECT/'android-client/lua/init-task-live-refresh.lua').read_text(encoding='utf-8')
    loot = (PROJECT/'android-client/lua/init-task-loot-display.lua').read_text(encoding='utf-8')
    script = original[:start]+live.rstrip()+'\n\n'+loot.rstrip()+'\n\n'+original[end:]
    assert 'ONLINE_TASK_LIVE_READY 65' not in script and 'ONLINE_TASK_LOOT_READY 65' not in script
    for marker in ('ONLINE_TASK_LIVE_READY 127','ONLINE_TASK_LOOT_READY 127',
                   'WWR_OPTIONAL_ENTRIES_READY 125','WWR_PRESERVED_STAGE_MANIFEST_READY'):
        assert marker in script
    check_lua(script)
    tree['m_Script']=script;target.save_typetree(tree)
    payload=env.file.save(packer='original')
    after={o.path_id:o for o in UnityPy.load(payload).objects}
    assert set(after)==set(before)
    assert {p for p in before if sha(after[p].get_raw_data())!=before[p]}=={target.path_id}
    assert after[target.path_id].read_typetree()['m_Script']==script
    return payload

def main():
    assert not REPORT.exists()
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    raw=(ROOT/'releases'/BASE/'manifest.json').read_bytes()
    assert sha(raw)==BASE.split('-',1)[1]
    base=json.loads(raw); entries={a['path']:a for a in base['assets']}
    with zipfile.ZipFile(APK) as apk:
        public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((ROOT/'releases'/BASE/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key((PROJECT/'.local/热更新密钥/签名私钥.pem').read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    changed_classes=build_jar()
    original=(ROOT/'blobs'/entries[LOGICAL]['sha256']).read_bytes()
    assert sha(original)==entries[LOGICAL]['sha256']
    payload=patch_lua(original);digest=sha(payload)
    blob=ROOT/'blobs'/digest
    if blob.exists(): assert blob.read_bytes()==payload
    else: blob.write_bytes(payload)
    snapshot=copy.deepcopy(base)
    change=dict(path=LOGICAL,url='/updates/stable/blobs/'+digest,size=len(payload),sha256=digest)
    snapshot['assets']=[change if a['path']==LOGICAL else a for a in snapshot['assets']]
    fix=signed_release(snapshot,127,private,public); rollback=signed_release(base,128,private,public)
    for name,data,signature in (fix,rollback):
        folder=ROOT/'releases'/name;assert not folder.exists();folder.mkdir()
        (folder/'manifest.json').write_bytes(data);(folder/'manifest.sig').write_bytes(signature)
    result=dict(status='LOCAL_VALIDATED_CANDIDATE',base=BASE,release=fix[0],rollback=rollback[0],
        jar=str(JAR),jarSha256=sha(JAR.read_bytes()),baseJarSha256=BASE_JAR_SHA,
        changedClasses=changed_classes,changedAssets={LOGICAL:change},resourceCount=len(entries),
        dailyTasks=15,permanentAchievements=50,originalStoryTasks=106,deltaBytes=len(payload))
    REPORT.parent.mkdir(parents=True,exist_ok=True)
    REPORT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__': main()
