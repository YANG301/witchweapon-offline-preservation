"""Restore missing native product clocks on the verified star-shop server."""
import hashlib
import zipfile
import build_prayer_shop_hotfix as build

build.BASE=build.ROOT/'build/witchweapon-legacy-star-shop.jar'
build.BASE_SHA='5e816da86d67aa63f30d6683ed993c7d5098c05a3e3f2f5c1b17fffbe927227d'
build.OUTPUT=build.ROOT/'build/witchweapon-legacy-star-shop-time.jar'
build.TEMP=build.Path(r'D:\Environment\Java\temp\witch-star-shop-time')
build.PRODUCTION=('CaphActivityAccess',)
build.TESTS=('StarShopTimeDataSelfTest','CaphActivityAccessSelfTest','StarShopSelfTest')
build.arguments=lambda test:[build.FIXTURE,build.EXCHANGE] if test=='StarShopSelfTest' else []

def main():
    assert hashlib.sha256(build.BASE.read_bytes()).hexdigest()==build.BASE_SHA
    assert not build.OUTPUT.exists(),'Immutable candidate already exists'
    classes=build.compile_tests(True)
    baseline=build.run([build.JAVA,'-cp',build.os.pathsep.join(map(str,(build.BASE,classes,build.JSON_JAR))),
        'com.codex.witchweapon.StarShopTimeDataSelfTest'])
    assert baseline.returncode!=0 and 'Missing original star product clock 1010008' in baseline.stderr,baseline.stderr
    print('STAR_PRODUCT_CLOCK_BASELINE_REPRODUCED',flush=True)
    name=build.PACKAGE+'CaphActivityAccess.class'
    replacement=(classes/name).read_bytes()
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT,'x') as new:
        for item in old.infolist():new.writestr(item,replacement if item.filename==name else old.read(item))
    with zipfile.ZipFile(build.BASE) as old,zipfile.ZipFile(build.OUTPUT) as new:
        assert set(old.namelist())==set(new.namelist())
        assert {name for name in old.namelist() if old.read(name)!=new.read(name)}=={build.PACKAGE+'CaphActivityAccess.class'}
    build.verify()

if __name__=='__main__':
    if build.sys.argv[1:]==['--verify']:build.verify()
    elif not build.sys.argv[1:]:main()
    else:raise ValueError('Unsupported argument')
