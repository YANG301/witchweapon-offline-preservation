"""Correct whole-page star refresh, cube selection, and timed event products."""
import hashlib
import zipfile
import build_prayer_shop_hotfix as build

build.BASE=build.ROOT/'build/witchweapon-legacy-star-shop-time.jar'
build.BASE_SHA='0cedb5b465c0d1a0f3d253f6221d241ed9e8f48309e51be6d79377dd75e35b73'
build.OUTPUT=build.ROOT/'build/witchweapon-legacy-star-shop-rotation.jar'
build.TEMP=build.Path(r'D:\Environment\Java\temp\witch-star-shop-rotation')
build.PRODUCTION=('OriginalShop','StarShopPolicy','StarShopEvents','CaphActivityAccess')
build.TESTS=('StarShopRotationSelfTest','StarShopSelfTest','StarShopTimeDataSelfTest','CaphActivityAccessSelfTest',
             'PrayerShopSelfTest','OriginalShopCatalogSelfTest','OriginalShopSelfTest','OriginalShopRefreshSelfTest','ShopRefreshProtocolSelfTest')
old_arguments=build.arguments
build.arguments=lambda test:[build.FIXTURE,build.EXCHANGE] if test in ('StarShopRotationSelfTest','StarShopSelfTest') else [] if test in ('StarShopTimeDataSelfTest','CaphActivityAccessSelfTest') else old_arguments(test)

def main():
    assert hashlib.sha256(build.BASE.read_bytes()).hexdigest()==build.BASE_SHA
    assert not build.OUTPUT.exists(),'Immutable candidate already exists'
    classes=build.compile_tests(True)
    baseline=build.run([build.JAVA,'-Dfile.encoding=UTF-8','-cp',build.os.pathsep.join(map(str,(build.BASE,classes,build.JSON_JAR))),
        'com.codex.witchweapon.StarShopRotationSelfTest',build.FIXTURE,build.EXCHANGE])
    assert baseline.returncode!=0 and 'Cube shelf must expose exactly five devices' in baseline.stderr,baseline.stderr
    print('STAR_ROTATION_BASELINE_REPRODUCED',flush=True)
    changes={build.PACKAGE+p.name:p.read_bytes() for p in (classes/build.PACKAGE).glob('*.class')
        if any(p.name==name+'.class' or p.name.startswith(name+'$') for name in build.PRODUCTION)}
    changes['exchange_shop_catalog.json']=build.EXCHANGE.read_bytes()
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT,'x') as new:
        for item in old.infolist():new.writestr(item,changes.get(item.filename,old.read(item)))
        for name,raw in changes.items():
            if name not in old.namelist():new.writestr(name,raw)
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT) as new:
        assert not set(old.namelist())-set(new.namelist())
        assert set(new.namelist())-set(old.namelist())=={build.PACKAGE+'StarShopEvents.class'}
        assert {name for name in old.namelist() if old.read(name)!=new.read(name)}<=set(changes)
    build.verify()

if __name__=='__main__':
    if build.sys.argv[1:]==['--verify']:build.verify()
    elif not build.sys.argv[1:]:main()
    else:raise ValueError('Unsupported argument')
