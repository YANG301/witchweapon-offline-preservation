"""Compile only title selection/save routes against the reviewed live binary."""
from pathlib import Path
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT/'legacy-server'
BASE=ROOT/'build/witchweapon-legacy-draw-persistence.jar'
BASE_SHA='9f371681bdc4125c709c6c921276d01b44a69665443f4fab4636d672e0803b10'
OUTPUT=ROOT/'build/witchweapon-legacy-title-selection.jar'
TEMP=Path(r'D:\Environment\Java\temp\witch-title-selection')
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe')
JAVAC=JAVA.with_name('javac.exe')
JSON=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
FIXTURE=PROJECT/'验收/抽卡与升星修复/正式基线响应.json'
EVIDENCE=PROJECT/'验收/称号切换修复'
PACKAGE='com/codex/witchweapon/'
PRODUCTION=('LocalSave','StandaloneServer')
TESTS=('TitleSelectionSelfTest','DrawPersistenceSelfTest','CosmeticUnlocksSelfTest')

def production_source(name):
    text=(ROOT/('src/'+PACKAGE+name+'.java')).read_text(encoding='utf-8')
    if name=='LocalSave':
        # Stone-slate drafts are retained in the shared source, but have never
        # been deployed in this pinned online binary. Do not include them here.
        removals=(
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
            '''            if(StoneSlateBattle.contains(stage)){
                JSONObject next=StoneSlateBattle.bundled().begin(state,stage,args,now);
                if(next!=state)commit(next);
                return seed;
            }
''')
        for block in removals:
            assert text.count(block)==1,'Unreviewed stone-slate source changed'
            text=text.replace(block,'',1)
        assert text.count('            r.set(117,r.number(117,0)|StoneSlateBattle.challengeBits(state));\n')==1
        text=text.replace('            r.set(117,r.number(117,0)|StoneSlateBattle.challengeBits(state));\n','',1)
        assert text.count('return StoneSlateBattle.bundled().progress(progress,state);')==1
        text=text.replace('return StoneSlateBattle.bundled().progress(progress,state);','return progress;',1)
        assert 'StoneSlateBattle' not in text
    path=TEMP/'source'/name/(name+'.java');path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding='utf-8')
    return path

def verify_baseline_sources(sources):
    originals=[]
    for path in sources:
        text=path.read_text(encoding='utf-8')
        if path.stem=='LocalSave':
            start=text.index('    // Original CN Title table:')
            end=text.index('    // A new profile starts',start)
            text=text[:start]+text[end:]
            start=text.index('    /** Original ChangeTitle sends')
            end=text.index('    private ProtoWire sync',start)
            text=text[:start]+text[end:]
            text=text.replace('            r.set(123,selectedCosmetic("curTitle",(int)r.number(123,0)));\n','')
        else:
            text=text.replace('''            if (path.equals("/role/head/change") || path.equals("/role/headbox/change") ||
                    path.equals("/role/title/change") || path.equals("/game/role/title/change")) {''',
                '''            if (path.equals("/role/head/change") || path.equals("/role/headbox/change")) {''')
            text=text.replace('                boolean title=path.endsWith("/title/change");\n','')
            text=text.replace('String selectedKey=title?"title":frame?"headbox":"head";',
                'String selectedKey=frame?"headbox":"head";')
            text=text.replace('''                if(title)existingSaveForAccount(accountId).changeTitle(args,roleSeed);
                else existingSaveForAccount(accountId).changeCosmetic(frame,args,roleSeed);''',
                '''                existingSaveForAccount(accountId).changeCosmetic(frame,args,roleSeed);''')
        old=TEMP/'baseline-source'/path.name;old.parent.mkdir(exist_ok=True)
        old.write_text(text,encoding='utf-8');originals.append(old)
    compiled=TEMP/'baseline-classes';compiled.mkdir(exist_ok=True)
    run([JAVAC,'-encoding','UTF-8','-source','8','-target','8','-cp',os.pathsep.join(map(str,(BASE,JSON))),
        '-d',compiled,*originals])
    javap=JAVA.with_name('javap.exe')
    for name in (path.stem for path in sources):
        method='com.codex.witchweapon.'+name
        def disassemble(cp):
            result=subprocess.run([str(javap),'-J-Dfile.encoding=UTF-8','-p','-c','-constants','-classpath',cp,method],
                capture_output=True,text=True,encoding='utf-8',errors='replace')
            assert result.returncode==0,result.stderr
            text=result.stdout.replace('com/codex/witchweapon/'+name+'.','')
            # Constant-pool indices can move without changing the resolved
            # bytecode operand; retain javap's resolved names and values.
            return re.sub(r' +//', ' //', re.sub(r'#\d+', '#', text))
        old=disassemble(str(BASE));rebuilt=disassemble(os.pathsep.join(map(str,(compiled,BASE))))
        if old!=rebuilt:
            import difflib
            diff='\n'.join(difflib.unified_diff(old.splitlines(),rebuilt.splitlines(),n=2))
            raise RuntimeError('Source differs from deployed '+name+':\n'+diff[:6000])
    print('BASELINE_METHODS_MATCH: no unrelated unpublished behavior included',flush=True)

def run(args):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,encoding='utf-8',errors='replace',
        env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP)))
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    print(result.stdout.strip(),flush=True)

def http_test(jar,patched):
    data=TEMP/('http-new' if patched else 'http-old')
    account='TitleTestAccount123456'
    assert len(account)==22
    folder=data/('users/'+account);folder.mkdir(parents=True)
    save=folder/'offline_save_v1.json'
    original={'version':1,'starterProfile':1,'roleCreated':True,'legacyRoleId':101,'name':'TitleTest',
        'gold':1000,'rmb':0,'exp':0,'saveRevision':1,'roleUnlocks':{'3':{'9':True,'10':True}}}
    save.write_text(json.dumps(original),encoding='utf-8')
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    secret='title-selection-http-test-secret-not-production'
    env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP),WW_LEGACY_PROXY_SECRET=secret)
    cp=os.pathsep.join(map(str,(jar,JSON)))
    process=subprocess.Popen([str(JAVA),'-Dfile.encoding=UTF-8','-cp',cp,'com.codex.witchweapon.StandaloneServer',
        '--port',str(port),'--data-dir',str(data),'--responses',str(FIXTURE)],
        env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    origin='http://127.0.0.1:'+str(port)
    def request(path,body=None,content_type='application/x-www-form-urlencoded'):
        headers={'X-WW-Proxy-Secret':secret,'X-WW-Account-ID':account,'Content-Type':content_type}
        req=urllib.request.Request(origin+path,None if body is None else body.encode(),headers)
        try:
            with urllib.request.urlopen(req,timeout=4) as r:return r.status,r.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    try:
        deadline=time.monotonic()+12
        while time.monotonic()<deadline:
            if process.poll() is not None:raise RuntimeError('Isolated title server exited')
            try:
                with urllib.request.urlopen(origin+'/health',timeout=1) as r:
                    if r.status==200:break
            except (OSError,urllib.error.URLError):time.sleep(.1)
        else:raise RuntimeError('Isolated title server did not become ready')
        body='roleid=101&title=9'
        status,reply=request('/role/title/change',body)
        if not patched:
            assert status==404 and json.loads(save.read_text())==original,(status,reply)
            print('BASELINE_REPRODUCED: /role/title/change is missing',flush=True)
            return
        assert status==200 and reply==b'\x0a\x02ok',(status,reply)
        assert json.loads(save.read_text())['curTitle']==9
        status,reply=request('/game/role/title/change','roleid=101&title=10')
        assert status==200 and reply==b'\x0a\x02ok'
        prior=save.read_bytes()
        assert request('/role/title/change','roleid=101&title=10')[0]==200 and save.read_bytes()==prior
        for path,body,status,ctype in (
            ('/role/title/change','roleid=102&title=9',422,'application/x-www-form-urlencoded'),
            ('/role/title/change','roleid=101&title=1',422,'application/x-www-form-urlencoded'),
            ('/role/title/change','roleid=101&title=25',422,'application/x-www-form-urlencoded'),
            ('/role/title/change','roleid=101&title=hello',422,'application/x-www-form-urlencoded'),
            ('/role/title/change','roleid=101',400,'application/x-www-form-urlencoded'),
            ('/role/title/change','roleid=101&title=9&unexpected=1',400,'application/x-www-form-urlencoded'),
            ('/role/title/change',None,405,'application/x-www-form-urlencoded'),
            ('/role/title/change?title=9','roleid=101&title=9',405,'application/x-www-form-urlencoded'),
            ('/role/title/change','{}',415,'application/json')):
            actual=request(path,body,ctype)[0]
            assert actual==status,(path,actual,status)
            assert save.read_bytes()==prior,'Rejected HTTP request modified the account'
        assert request('/role/title/change',
            'roleid=101&title=9&enc=0&idempotency=test&hwid=test&time=1&sign=test')[0]==200
        assert json.loads(save.read_text())['curTitle']==9
        print('TITLE_HTTP_PASS: original CommonInfo, both route forms, ownership, isolation and retries',flush=True)
    finally:
        process.terminate();process.wait(timeout=8)

def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE_SHA
    assert not OUTPUT.exists()
    classes=TEMP/'classes';classes.mkdir(parents=True,exist_ok=True)
    sources=[production_source(n) for n in PRODUCTION]
    verify_baseline_sources(sources)
    sources += [ROOT/('tests/'+PACKAGE+n+'.java') for n in TESTS]
    run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',os.pathsep.join(map(str,(BASE,JSON))),'-d',classes,*sources])
    # Existing nested classes only have changed source line numbers; keep the
    # exact deployed bytes and replace only the two classes with new behavior.
    changes={PACKAGE+n+'.class':(classes/PACKAGE/(n+'.class')).read_bytes() for n in PRODUCTION}
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT,'x') as new:
        assert set(changes)<=set(old.namelist())
        for info in old.infolist():new.writestr(info,changes.get(info.filename,old.read(info)))
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT) as new:
        changed={n for n in old.namelist() if old.read(n)!=new.read(n)}
        assert changed=={PACKAGE+n+'.class' for n in PRODUCTION},changed
    http_test(BASE,False)
    http_test(OUTPUT,True)
    cp=os.pathsep.join(map(str,(OUTPUT,classes,JSON)))
    for test,args in (
        ('TitleSelectionSelfTest',[FIXTURE,TEMP/'selection-save']),
        ('DrawPersistenceSelfTest',[FIXTURE,ROOT/'resources/prayer_shop_catalog.json',TEMP/'draw-save']),
        ('CosmeticUnlocksSelfTest',[FIXTURE])):
        run([JAVA,'-Dfile.encoding=UTF-8','-cp',cp,'com.codex.witchweapon.'+test,*args])
    result={'baseSha256':BASE_SHA,'candidateSha256':hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),
        'changedClasses':sorted(changed),'nativeRoute':'/role/title/change','wireKey':'title',
        'roleSelectedField':123,'ownershipField':3,'tests':['old route 404 reproduced','title selection/persistence',
        'native HTTP routes and validation','draw persistence regression','cosmetic ownership regression']}
    EVIDENCE.mkdir(exist_ok=True)
    (EVIDENCE/'构建与校验结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('TITLE_CANDIDATE_VERIFIED sha='+result['candidateSha256'],flush=True)

if __name__=='__main__':main()
