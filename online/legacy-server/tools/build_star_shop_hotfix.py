"""Incrementally build the original star-shop calendar and purchase rules."""
import build_prayer_shop_hotfix as build
import hashlib
import zipfile

build.BASE=build.ROOT/'build/witchweapon-legacy-prayer-shop.jar'
build.BASE_SHA='aa72f1de063f38ba3e5c4c9badca792494ee61986f0583429ebc80b35fd1cbbd'
build.OUTPUT=build.ROOT/'build/witchweapon-legacy-star-shop.jar'
build.TEMP=build.Path(r'D:\Environment\Java\temp\witch-star-shop')
build.PRODUCTION=('OriginalShop','StarShopPolicy')
build.TESTS=('StarShopSelfTest','PrayerShopSelfTest','OriginalShopCatalogSelfTest',
    'OriginalShopSelfTest','OriginalShopRefreshSelfTest','ShopRefreshProtocolSelfTest')
old_arguments=build.arguments
build.arguments=lambda test:[build.FIXTURE,build.EXCHANGE] if test=='StarShopSelfTest' else old_arguments(test)

def main():
    assert hashlib.sha256(build.BASE.read_bytes()).hexdigest()==build.BASE_SHA
    assert not build.OUTPUT.exists(),'Immutable candidate already exists'
    classes=build.compile_tests(True)
    baseline=build.run([build.JAVA,'-Dfile.encoding=UTF-8','-cp',build.os.pathsep.join(map(str,(build.BASE,classes,build.JSON_JAR))),
        'com.codex.witchweapon.StarShopSelfTest',build.FIXTURE,build.EXCHANGE])
    assert baseline.returncode!=0 and 'Cube device shelves use daily reset' in baseline.stderr,baseline.stderr
    print('STAR_BASELINE_BUG_REPRODUCED',flush=True)
    changes={build.PACKAGE+p.name:p.read_bytes() for p in (classes/build.PACKAGE).glob('*.class')
        if any(p.name==name+'.class' or p.name.startswith(name+'$') for name in build.PRODUCTION)}
    changes['exchange_shop_catalog.json']=build.EXCHANGE.read_bytes()
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT,'x') as new:
        for entry in old.infolist():new.writestr(entry,changes.get(entry.filename,old.read(entry)))
        for name,raw in changes.items():
            if name not in old.namelist():new.writestr(name,raw)
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT) as new:
        changed={name for name in old.namelist() if old.read(name)!=new.read(name)}
        added=set(new.namelist())-set(old.namelist())
        assert not set(old.namelist())-set(new.namelist()) and changed|added<=set(changes)
        assert added=={build.PACKAGE+'StarShopPolicy.class'}
        print('STAR_CHANGED_MEMBERS',sorted(changed|added),flush=True)
    build.verify()

if __name__=='__main__':
    if build.sys.argv[1:]==['--verify']:build.verify()
    elif not build.sys.argv[1:]:main()
    else:raise ValueError('Unsupported argument')
