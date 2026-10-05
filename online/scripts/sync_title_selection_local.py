"""Build the same title fix against the separate stopped PC service baseline."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import socket
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'legacy-server/tools'))
import build_title_selection_hotfix as build

LIVE=Path(r'D:\Project\魔女兵器工程恢复\本地模式服务\程序\witchweapon-legacy.jar')
BASE_SHA='ff43a28dab5fd8caa53edffdb114f43b6c35095ba246ae422373372ef5bcc630'
CANDIDATE=ROOT/'legacy-server/build/witchweapon-local-title-selection.jar'
EVIDENCE=ROOT/'验收/称号切换修复'

def main():
    assert hashlib.sha256(LIVE.read_bytes()).hexdigest()==BASE_SHA and not CANDIDATE.exists()
    for port in (19876,19180,19896,19181):
        with socket.socket() as s:assert s.connect_ex(('127.0.0.1',port))!=0,'PC local mode is running'
    sources=[]
    for name in ('StandaloneServer',):
        path=build.production_source(name);text=path.read_text(encoding='utf-8')
        # Keep the stopped PC service's existing administrative surface and
        # directory handling. Only add the reviewed native title route.
        a=text.index('            if(path.equals("/__admin/save")')
        b=text.index('            if (path.equals("/__admin/patch"))',a)
        text=text[:a]+text[b:]
        text=text.replace('        catch (AdminDataService.ActiveBattle ex) { reply = error(409,"active_battle"); }\n','')
        a=text.index('        // The explicitly configured root may be systemd')
        b=text.index('        final FileChannel lockChannel',a)
        text=text[:a]+text[b:]
        p=build.TEMP/'local-source'/(name+'.java');p.parent.mkdir(exist_ok=True)
        p.write_text(text,encoding='utf-8');sources.append(p)
    build.BASE=LIVE
    build.verify_baseline_sources(sources)
    classes=build.TEMP/'local-classes';classes.mkdir(exist_ok=True)
    build.run([build.JAVAC,'-J-Dfile.encoding=UTF-8','-XDignore.symbol.file','-encoding','UTF-8',
        '-source','8','-target','8','-d',classes,
        ROOT/'legacy-server/tools/GraftLocalTitle.java'])
    old=build.TEMP/'pc-LocalSave.class'
    with zipfile.ZipFile(LIVE) as pc:old.write_bytes(pc.read(build.PACKAGE+'LocalSave.class'))
    donor=build.TEMP/'formal-LocalSave.class'
    with zipfile.ZipFile(build.OUTPUT) as formal:donor.write_bytes(formal.read(build.PACKAGE+'LocalSave.class'))
    target=classes/build.PACKAGE/'LocalSave.class';target.parent.mkdir(parents=True,exist_ok=True)
    build.run([build.JAVA,'-Dfile.encoding=UTF-8','-cp',classes,'GraftLocalTitle',old,
        donor,target])
    build.run([build.JAVAC,'-encoding','UTF-8','-source','8','-target','8','-cp',
        os.pathsep.join(map(str,(classes,LIVE,build.JSON))),'-d',classes,*sources])
    scope={build.PACKAGE+n+'.class' for n in build.PRODUCTION}
    with zipfile.ZipFile(LIVE) as old,zipfile.ZipFile(CANDIDATE,'x') as new:
        for info in old.infolist():
            new.writestr(info,(classes/info.filename).read_bytes() if info.filename in scope else old.read(info))
    with zipfile.ZipFile(LIVE) as old,zipfile.ZipFile(CANDIDATE) as new:
        assert set(old.namelist())==set(new.namelist())
        assert {n for n in old.namelist() if old.read(n)!=new.read(n)}==scope
    # Reuse isolated tests, with fresh storage; none read real PC player data.
    build.TEMP=build.TEMP/'local-check';build.TEMP.mkdir()
    build.http_test(CANDIDATE,True)
    testClasses=build.TEMP/'classes';testClasses.mkdir()
    build.run([build.JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',os.pathsep.join(map(str,(CANDIDATE,build.JSON))),'-d',testClasses,
        *[ROOT/('legacy-server/tests/'+build.PACKAGE+n+'.java') for n in build.TESTS]])
    cp=os.pathsep.join(map(str,(CANDIDATE,testClasses,build.JSON)))
    build.run([build.JAVA,'-Dfile.encoding=UTF-8','-cp',cp,'com.codex.witchweapon.TitleSelectionSelfTest',
        build.FIXTURE,build.TEMP/'selection-save'])
    build.run([build.JAVA,'-Dfile.encoding=UTF-8','-cp',cp,'com.codex.witchweapon.DrawPersistenceSelfTest',
        build.FIXTURE,ROOT/'legacy-server/resources/prayer_shop_catalog.json',build.TEMP/'draw-save'])
    backup=EVIDENCE/'本地服务回退.jar';assert not backup.exists()
    shutil.copyfile(LIVE,backup)
    assert hashlib.sha256(backup.read_bytes()).hexdigest()==BASE_SHA
    stage=LIVE.with_suffix('.title-next.jar');assert not stage.exists()
    shutil.copyfile(CANDIDATE,stage);os.replace(stage,LIVE)
    digest=hashlib.sha256(LIVE.read_bytes()).hexdigest()
    assert digest==hashlib.sha256(CANDIDATE.read_bytes()).hexdigest()
    result=json.loads((EVIDENCE/'发布结果.json').read_text(encoding='utf-8'))
    result['localServiceSync']={'sha256':digest,'changedClasses':sorted(scope),'rollback':str(backup),
        'playerDataUntouched':True,'existingLocalAdminPreserved':True}
    (EVIDENCE/'发布结果.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('PC_TITLE_SYNCED sha='+digest,flush=True)

if __name__=='__main__':main()
