"""Append original task-page live sync and guarded native claims to release 55."""
from __future__ import annotations
import base64
import copy
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import zipfile
import UnityPy
import build_settlement_levelup_hotupdate as signing

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT / '热更新测试/主线热更候选'
BASE = '55-ddd5c7ab571e0d220bae149560b490e844b6c29b5168e114392b37f1b046e6e6'
LOGICAL = 'assetbundle/lua/lua.ab'
SOURCE = PROJECT / 'android-client/lua/init-task-live-refresh.lua'
SOURCES = (SOURCE,)
SEQUENCE = 57
ROLLBACK_SEQUENCE = 58
DLL = Path(r'D:\Project\魔女兵器工程恢复\原版\Unity恢复\ExportedProject\Assets\Plugins\x86_64\tolua.dll')

def sha(raw): return hashlib.sha256(raw).hexdigest()

def check_syntax(source):
    dll = ctypes.CDLL(str(DLL))
    dll.luaL_newstate.restype = ctypes.c_void_p
    dll.luaL_loadbuffer.argtypes = [ctypes.c_void_p,ctypes.c_char_p,ctypes.c_size_t,ctypes.c_char_p]
    dll.luaL_loadbuffer.restype = ctypes.c_int
    dll.lua_close.argtypes = [ctypes.c_void_p]
    state = dll.luaL_newstate()
    try:
        raw = source.encode('utf-8')
        if dll.luaL_loadbuffer(state,raw,len(raw),b'init.lua') != 0:
            raise ValueError('Combined init.lua failed original ToLua syntax validation')
    finally: dll.lua_close(state)

def patch(raw):
    bundle = UnityPy.load(raw)
    before = {o.path_id: sha(o.get_raw_data()) for o in bundle.objects}
    targets = [o for o in bundle.objects if o.type.name=='TextAsset' and o.read_typetree().get('m_Name')=='init.lua']
    assert len(targets)==1
    target=targets[0]; tree=target.read_typetree(); original=tree['m_Script']
    assert 'ONLINE_TASK_LIVE_READY' not in original
    assert 'ONLINE_SETTLEMENT_EFFECT_ORDER' not in original
    script='\n\n'.join(p.read_text(encoding='utf-8') for p in SOURCES)
    proposed=original.rstrip('\n')+'\n\n'+script
    check_syntax(proposed)
    tree['m_Script']=proposed; target.save_typetree(tree)
    result=bundle.file.save(packer='original')
    reopened=UnityPy.load(result)
    after={o.path_id:sha(o.get_raw_data()) for o in reopened.objects}
    assert set(before)==set(after)
    assert {p for p in before if before[p]!=after[p]}=={target.path_id}
    actual=next(o for o in reopened.objects if o.path_id==target.path_id).read_typetree()['m_Script']
    assert actual==proposed
    for marker in ('ONLINE_FURNACE_SELECTION_GATE','ONLINE_GUILD_RECALL_REWARD','ONLINE_MAINLINE_ODD_OPEN'):
        assert marker in actual
    return result

def main():
    directory=ROOT/'releases'/BASE
    raw=(directory/'manifest.json').read_bytes()
    assert sha(raw)==BASE.split('-',1)[1]
    manifest=json.loads(raw)
    assert manifest['releaseSequence']==55 and len(manifest['assets'])==74
    baseline=next(a for a in manifest['assets'] if a['path']==LOGICAL)
    original=(ROOT/'blobs'/baseline['sha256']).read_bytes()
    assert sha(original)==baseline['sha256']
    data=patch(original); digest=sha(data)
    sys.path.insert(0,r'D:\Environment\VPS-SSH\packages313')
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    with zipfile.ZipFile(signing.APK) as apk:
        public=serialization.load_der_public_key(apk.read('assets/update_public_key.der'))
    public.verify(base64.b64decode((directory/'manifest.sig').read_bytes()),raw,padding.PKCS1v15(),hashes.SHA256())
    private=serialization.load_pem_private_key(signing.KEY.read_bytes(),password=None)
    assert private.public_key().public_numbers()==public.public_numbers()
    changed=copy.deepcopy(manifest)
    next(a for a in changed['assets'] if a['path']==LOGICAL).update(
        url='/updates/stable/blobs/'+digest,size=len(data),sha256=digest)
    fix=signing.signed_release(changed,SEQUENCE,private,public)
    rollback=signing.signed_release(manifest,ROLLBACK_SEQUENCE,private,public)
    for name,_,_ in (fix,rollback):
        assert not (ROOT/'releases'/name).exists(), 'Immutable release already exists'
    blob=ROOT/'blobs'/digest
    if blob.exists(): assert blob.read_bytes()==data
    else: blob.write_bytes(data)
    for name,m,s in (fix,rollback):
        folder=ROOT/'releases'/name; folder.mkdir()
        (folder/'manifest.json').write_bytes(m); (folder/'manifest.sig').write_bytes(s)
    print('TASK_LIVE_READY',fix[0],rollback[0],digest,len(data),flush=True)

if __name__=='__main__': main()
