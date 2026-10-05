"""Patch only ShopRefresh parameter readers in the tested production JAR."""
from pathlib import Path
import hashlib
import os
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/witchweapon-legacy.jar'
OUTPUT=ROOT/'build/witchweapon-legacy-shop-refresh.jar'
BASE_SHA='9c1a7899df1b3f7575dea932bf05880bc28b89741ef64c210ff68e9da77d7126'
TEMP=Path(r'D:\Environment\Java\temp\witch-shop-refresh')
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe')
JAVAC=JAVA.with_name('javac.exe')
JSON_JAR=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
PACKAGE='com/codex/witchweapon/'
NAMES=('ResourceShop','OriginalShop')
TESTS=('ShopRefreshProtocolSelfTest','OriginalShopRefreshSelfTest','ResourceShopLayoutSelfTest')
REGRESSION_MESSAGE='Native setid must select the sundry route'

def run(args):
    return subprocess.run([str(a) for a in args],env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP)),
        capture_output=True,text=True,encoding='utf-8',errors='replace')

def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest()!=BASE_SHA:
        raise ValueError('Reviewed live baseline changed')
    if OUTPUT.exists() or TEMP.exists():raise FileExistsError('Candidate or bounded temporary directory exists')
    TEMP.mkdir();classes=TEMP/'classes';classes.mkdir()
    sources=[ROOT/('src/'+PACKAGE+n+'.java') for n in NAMES]
    sources+=[ROOT/('tests/'+PACKAGE+n+'.java') for n in TESTS]
    result=run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
                '-cp',os.pathsep.join(map(str,(BASE,JSON_JAR))),'-d',classes,*sources])
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    fixture=ROOT/'resources/offline_responses.json'
    baseline=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(BASE,classes,JSON_JAR))),
                  'com.codex.witchweapon.ShopRefreshProtocolSelfTest',fixture])
    if baseline.returncode==0 or REGRESSION_MESSAGE not in baseline.stderr:
        raise AssertionError('Regression did not reproduce on the live baseline')
    print('BASELINE_REPRODUCED: '+REGRESSION_MESSAGE,flush=True)
    changed={PACKAGE+n+'.class':(classes/(PACKAGE+n+'.class')).read_bytes() for n in NAMES}
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT,'x') as new:
        for entry in old.infolist():new.writestr(entry,changed.pop(entry.filename,old.read(entry)))
        if changed:raise AssertionError('Reviewed classes are missing from the baseline')
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT) as new:
        actual={n for n in new.namelist() if n not in old.namelist() or new.read(n)!=old.read(n)}
        if actual!={PACKAGE+n+'.class' for n in NAMES} or set(old.namelist())!=set(new.namelist()):
            raise AssertionError('Unexpected JAR changes outside the two refresh readers')
    for test in TESTS:
        result=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(OUTPUT,classes,JSON_JAR))),
                    'com.codex.witchweapon.'+test,fixture])
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)
    print('SHOP_REFRESH_JAR_VERIFIED',hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)

if __name__=='__main__':main()
