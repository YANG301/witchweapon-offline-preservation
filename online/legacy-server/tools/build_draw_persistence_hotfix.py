"""Patch the live baseline only: valid permanent rewards and persisted decomposition."""
from pathlib import Path
import hashlib
import os
import subprocess
import zipfile

PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT/'legacy-server'
EVIDENCE=PROJECT/'验收/抽卡与升星修复'
BASE=EVIDENCE/'正式基线.jar'
BASE_SHA='0ad22bfec44846bc1c317956d26ecbfbc27b86c29a90c55347bef21a1cec36b4'
OUTPUT=ROOT/'build/witchweapon-legacy-draw-persistence.jar'
TEMP=Path(r'D:\Environment\Java\temp\witch-draw-persistence')
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe')
JAVAC=JAVA.with_name('javac.exe')
JSON_JAR=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
PACKAGE='com/codex/witchweapon/'
PRODUCTION=('LocalEconomy','PrayerShop','NormalDrawRates')
TESTS=('DrawPersistenceSelfTest','NormalDrawRatesSelfTest','GoldDrawRatesSelfTest',
       'OnlineDrawSelfTest','GuideDrawSelfTest','PrayerShopSelfTest')
FIXTURE=EVIDENCE/'正式基线响应.json'
PUBLICITY=Path(r'D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel\publicity.txt')

def run(args):
    return subprocess.run([str(x) for x in args],capture_output=True,text=True,encoding='utf-8',errors='replace',
        env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP)))

def arguments(test,suffix):
    if test=='DrawPersistenceSelfTest':return [FIXTURE,ROOT/'resources/prayer_shop_catalog.json',TEMP/('save-'+suffix)]
    if test=='NormalDrawRatesSelfTest':return [FIXTURE,PUBLICITY]
    if test=='GuideDrawSelfTest':
        directory=TEMP/('guide-'+suffix);directory.mkdir(exist_ok=False);return [directory,FIXTURE]
    if test=='PrayerShopSelfTest':return [FIXTURE,ROOT/'resources/exchange_shop_catalog.json',ROOT/'resources/prayer_shop_catalog.json']
    return [FIXTURE]

def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE_SHA,'Reviewed live baseline changed'
    classes=TEMP/'classes';classes.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/('src/'+PACKAGE+n+'.java') for n in PRODUCTION]
    sources += [ROOT/('tests/'+PACKAGE+n+'.java') for n in TESTS]
    result=run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',os.pathsep.join(map(str,(BASE,JSON_JAR))),'-d',classes,*sources])
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    baseline=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(BASE,classes,JSON_JAR))),
        'com.codex.witchweapon.DrawPersistenceSelfTest',*arguments('DrawPersistenceSelfTest','baseline')])
    assert baseline.returncode and 'Authoritative duplicate reward missing' in baseline.stderr,baseline.stdout+baseline.stderr
    print('BASELINE_REPRODUCED: duplicate materials are visible but not credited',flush=True)
    changes={PACKAGE+p.name:p.read_bytes() for p in (classes/PACKAGE).glob('*.class')
        if any(p.name==n+'.class' or p.name.startswith(n+'$') for n in PRODUCTION)}
    if not OUTPUT.exists():
        with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT,'x') as new:
            for entry in old.infolist():new.writestr(entry,changes.get(entry.filename,old.read(entry)))
            for name,raw in changes.items():
                if name not in old.namelist():new.writestr(name,raw)
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT) as new:
        assert set(old.namelist())==set(new.namelist())
        changed={n for n in old.namelist() if old.read(n)!=new.read(n)}
        assert changed==set(changes),changed
        assert all(new.read(n)==data for n,data in changes.items()),'Existing candidate differs from newly compiled sources'
        print('CHANGED_JAR_ENTRIES',sorted(changed),flush=True)
    for test in TESTS:
        result=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(OUTPUT,classes,JSON_JAR))),
            'com.codex.witchweapon.'+test,*arguments(test,'candidate')])
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)
    print('DRAW_PERSISTENCE_VERIFIED sha='+hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)

if __name__=='__main__':main()
