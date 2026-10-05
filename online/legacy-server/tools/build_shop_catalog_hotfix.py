"""Patch only the two reviewed shop classes and exchange catalog in live JAR."""
from pathlib import Path
import hashlib
import os
import subprocess
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/witchweapon-legacy-shop-refresh-completion.jar'
OUTPUT=ROOT/'build/witchweapon-legacy-shop-catalog.jar'
BASE_SHA='b4fa6b2494602d784e50bb37d8aeb78797c11c85df63908282bbd840eb46a44a'
TEMP=Path(r'D:\Environment\Java\temp\witch-shop-catalog')
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe')
JAVAC=JAVA.with_name('javac.exe')
JSON_JAR=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
PACKAGE='com/codex/witchweapon/'
NAMES=('OriginalShop','ResourceShop')
TESTS=('OriginalShopCatalogSelfTest','OriginalShopSelfTest','OriginalShopRefreshSelfTest',
       'ShopRefreshProtocolSelfTest','ResourceShopLayoutSelfTest')

def run(args):
    result=subprocess.run([str(a) for a in args],env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP)),
        capture_output=True,text=True,encoding='utf-8',errors='replace')
    return result

def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE_SHA,'Reviewed baseline changed'
    assert not OUTPUT.exists() and not TEMP.exists(),'Output or bounded intermediate already exists'
    TEMP.mkdir();classes=TEMP/'classes';classes.mkdir()
    sources=[ROOT/('src/'+PACKAGE+n+'.java') for n in NAMES]
    sources+=[ROOT/('tests/'+PACKAGE+n+'.java') for n in TESTS]
    compiled=run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',os.pathsep.join(map(str,(BASE,JSON_JAR))),'-d',classes,*sources])
    if compiled.returncode:raise RuntimeError(compiled.stdout+compiled.stderr)
    fixture=ROOT/'resources/offline_responses.json';catalog=ROOT/'resources/exchange_shop_catalog.json'
    baseline=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(BASE,classes,JSON_JAR))),
        'com.codex.witchweapon.OriginalShopCatalogSelfTest',fixture,catalog])
    assert baseline.returncode!=0 and 'Powder must show 13 original goods' in baseline.stderr,baseline.stderr
    print('BASELINE_REPRODUCED: Powder expands every level tier',flush=True)
    changes={}
    for path in (classes/PACKAGE).glob('*.class'):
        if any(path.name==n+'.class' or path.name.startswith(n+'$') for n in NAMES):
            changes[PACKAGE+path.name]=path.read_bytes()
    changes['exchange_shop_catalog.json']=catalog.read_bytes()
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT,'x') as new:
        assert set(changes)<=set(old.namelist()),'Unexpected new production members'
        for entry in old.infolist():new.writestr(entry,changes.get(entry.filename,old.read(entry)))
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT) as new:
        actual={n for n in new.namelist() if new.read(n)!=old.read(n)}
        assert actual<=set(changes) and len(actual)>=3 and set(old.namelist())==set(new.namelist())
        print('REVIEWED_CHANGED_MEMBERS',sorted(actual),flush=True)
    verify()

def verify():
    classes=TEMP/'classes'
    # Intermediate classes are removed after delivery. A later verification
    # compiles its own tests against the final artifact instead of retaining them.
    if not all((classes/(PACKAGE+name+'.class')).is_file() for name in TESTS):
        classes.mkdir(parents=True,exist_ok=True)
        sources=[ROOT/('tests/'+PACKAGE+name+'.java') for name in TESTS]
        compiled=run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
            '-cp',os.pathsep.join(map(str,(OUTPUT,JSON_JAR))),'-d',classes,*sources])
        if compiled.returncode:raise RuntimeError(compiled.stdout+compiled.stderr)
    fixture=ROOT/'resources/offline_responses.json';catalog=ROOT/'resources/exchange_shop_catalog.json'
    for test in TESTS:
        result=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(OUTPUT,classes,JSON_JAR))),
            'com.codex.witchweapon.'+test,fixture,*([catalog] if test=='OriginalShopCatalogSelfTest' else [])])
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)
    print('SHOP_CATALOG_JAR_VERIFIED',hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--verify']:verify()
    elif not sys.argv[1:]:main()
    else:raise ValueError('Unsupported build argument')
