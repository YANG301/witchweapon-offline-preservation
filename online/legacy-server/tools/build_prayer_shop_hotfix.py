"""Build only the prayer exchange fix on the reviewed current shop server."""
from pathlib import Path
import hashlib
import os
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'build/witchweapon-legacy-shop-catalog.jar'
BASE_SHA='2a69bcafa6b9072982b267d32693095afe7898623608116fa79fdd86d0819562'
OUTPUT=ROOT/'build/witchweapon-legacy-prayer-shop.jar'
TEMP=Path(r'D:\Environment\Java\temp\witch-prayer-shop')
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe');JAVAC=JAVA.with_name('javac.exe')
JSON_JAR=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
PACKAGE='com/codex/witchweapon/'
PRODUCTION=('OriginalShop','PrayerShop','NormalDrawRates')
TESTS=('PrayerShopSelfTest','OriginalShopCatalogSelfTest','OriginalShopSelfTest',
       'OriginalShopRefreshSelfTest','ShopRefreshProtocolSelfTest','ResourceShopLayoutSelfTest','NormalDrawRatesSelfTest')
PUBLICITY=Path(r'D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel\publicity.txt')
FIXTURE=ROOT/'resources/offline_responses.json'
EXCHANGE=ROOT/'resources/exchange_shop_catalog.json'
PRAYER=ROOT/'resources/prayer_shop_catalog.json'

def run(args):
    return subprocess.run([str(x) for x in args],capture_output=True,text=True,encoding='utf-8',errors='replace',
        env=dict(os.environ,TEMP=str(TEMP),TMP=str(TEMP)))

def compile_tests(include_production=False):
    classes=TEMP/'classes';classes.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/('tests/'+PACKAGE+x+'.java') for x in TESTS]
    if include_production:sources+=[ROOT/('src/'+PACKAGE+x+'.java') for x in PRODUCTION]
    dependency=BASE if include_production else OUTPUT
    result=run([JAVAC,'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',os.pathsep.join(map(str,(dependency,JSON_JAR))),'-d',classes,*sources])
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return classes

def arguments(test):
    if test=='PrayerShopSelfTest':return [FIXTURE,EXCHANGE,PRAYER]
    if test=='OriginalShopCatalogSelfTest':return [FIXTURE,EXCHANGE]
    if test=='NormalDrawRatesSelfTest':return [FIXTURE,PUBLICITY]
    return [FIXTURE]

def verify():
    classes=TEMP/'classes'
    if not all((classes/(PACKAGE+x+'.class')).is_file() for x in TESTS):classes=compile_tests()
    for test in TESTS:
        result=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(OUTPUT,classes,JSON_JAR))),
            'com.codex.witchweapon.'+test,*arguments(test)])
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        print(result.stdout.strip(),flush=True)
    print('PRAYER_SHOP_JAR_VERIFIED',hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),flush=True)

def build():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==BASE_SHA,'Reviewed baseline changed'
    assert not OUTPUT.exists(),'Candidate already exists'
    classes=compile_tests(True)
    baseline=run([JAVA,'-Dfile.encoding=UTF-8','-cp',os.pathsep.join(map(str,(BASE,classes,JSON_JAR))),
        'com.codex.witchweapon.PrayerShopSelfTest',*arguments('PrayerShopSelfTest'),'--baseline'])
    assert baseline.returncode!=0 and 'Prayer must return witch/weapon pair instead of voucher item' in baseline.stderr,baseline.stderr
    print('PRAYER_BASELINE_REPRODUCED: Exchange grants voucher instead of weapon',flush=True)
    changes={PACKAGE+p.name:p.read_bytes() for p in (classes/PACKAGE).glob('*.class')
        if any(p.name==name+'.class' or p.name.startswith(name+'$') for name in PRODUCTION)}
    changes['prayer_shop_catalog.json']=PRAYER.read_bytes()
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT,'x') as new:
        for entry in old.infolist():new.writestr(entry,changes.get(entry.filename,old.read(entry)))
        for name,raw in changes.items():
            if name not in old.namelist():new.writestr(name,raw)
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUTPUT) as new:
        added=set(new.namelist())-set(old.namelist())
        changed={name for name in old.namelist() if old.read(name)!=new.read(name)}
        assert added<={PACKAGE+'PrayerShop.class','prayer_shop_catalog.json'}
        assert not set(old.namelist())-set(new.namelist()) and changed<=set(changes)
        assert PACKAGE+'OriginalShop.class' in changed and PACKAGE+'NormalDrawRates.class' in changed
        print('REVIEWED_PRAYER_CHANGED_MEMBERS',sorted(added|changed),flush=True)
    verify()

if __name__=='__main__':
    if sys.argv[1:]==['--verify']:verify()
    elif not sys.argv[1:]:build()
    else:raise ValueError('Unsupported build argument')
