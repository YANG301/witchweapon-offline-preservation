"""Remove reviewed feature/campaign entry gates from the working simple APK."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

import build_original_ui_quest_refresh_v6_apk as base
from build_original_ui_lottery_lua_input_probe_apk import cert_digest
from build_online_apk import patch_index
import patch_all_campaign_unlocked as mainline
import patch_feature_access_unlocked as features

HERE = Path(__file__).resolve().parent
SOURCE = HERE / 'build/witchweapon-online-original-ui-simple-campaign-v1.apk'
SOURCE_SHA = 'df8f35e8f7bf574ec7bb768633c5505862358c13b63469ff3acacdf199c0559e'
RESULT = HERE / 'build/witchweapon-online-original-ui-open-access-v1.apk'
REPORT = HERE / 'build/全关卡与玩法入口开放验收.json'
TEMP = Path(r'D:\Environment\Android\temp\witch-online-open-access')
INDEX = 'assets/m.assets_list.txt'


def prepare():
    if base.sha256(SOURCE) != SOURCE_SHA:
        raise ValueError('Working simple-campaign APK baseline changed')
    changes = {}
    native = {}
    with zipfile.ZipFile(SOURCE) as z:
        for table, first, second in (
            ('instance', mainline.patch_instance_bundle, features.patch_instance_bundle),
            ('instanceset', mainline.patch_instance_set_bundle, features.patch_instance_set_bundle)):
            name = 'assets/assetbundle/config/clientexel/' + table + '.ab'
            raw = z.read(name)
            patched = second(first(raw))
            if patched != raw:
                changes[name] = patched
        for abi in ('armeabi-v7a', 'arm64-v8a'):
            name = 'lib/' + abi + '/libil2cpp.so'
            raw = z.read(name)
            patched, count = features.patch_native_entry_gates(raw, abi)
            if count != 2:
                raise ValueError('Unexpected native entry gate count')
            changes[name] = patched
            native[name] = dict(sourceSha256=hashlib.sha256(raw).hexdigest(),
                                sha256=hashlib.sha256(patched).hexdigest(), gateCount=count)
        changes[INDEX] = patch_index(z.read(INDEX), {
            '/' + n[len('assets/assetbundle/'):]: b for n, b in changes.items()
            if n.startswith('assets/assetbundle/')})
    return changes, native


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    changes, native = prepare()
    if not args.build:
        print('OPEN_ACCESS_PATCH_CHECK_OK', len(changes))
        return
    if TEMP.exists():
        raise ValueError('Unexpected previous open-access build temporary directory')
    base.SOURCE, base.SOURCE_SHA256, base.TEMP = SOURCE, SOURCE_SHA, TEMP
    try:
        report = base.build(changes, RESULT, REPORT)
        signer = [base.JAVA, '-jar', base.TOOLS / 'lib/apksigner.jar']
        before = cert_digest(base.run([*signer, 'verify', '--print-certs', SOURCE], base.signer_env()))
        after = cert_digest(base.run([*signer, 'verify', '--print-certs', RESULT], base.signer_env()))
        if before != after:
            raise ValueError('Signing identity changed')
        preserved = {}
        with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(RESULT) as new:
            for name in old.namelist():
                if name in ('AndroidManifest.xml', 'classes.dex', 'classes2.dex',
                            'assets/assetbundle/config/clientexel/lessontrigger.ab') or name.startswith('lib/'):
                    expected = changes.get(name, old.read(name))
                    if new.read(name) != expected:
                        raise ValueError('Critical APK payload differs: ' + name)
                    if name not in changes:
                        preserved[name] = hashlib.sha256(expected).hexdigest()
        for key in ('changedUnityTextAsset', 'originalUnityTextAssetSha256',
                    'preservesV4TaskItemPatch', 'nativeRefreshClass'):
            report.pop(key, None)
        report.update(campaignProfile='simple-campaign-v1', allMainlineUnlocked=True,
                      changedUnityAssets=['Instance entry gates', 'InstanceSet feature entry gates'],
                      reviewedNativeFixes=native, signerCertificateSha256=after,
                      criticalInheritedPayloadSha256=preserved,
                      realWinAndFirstRewardRecordsPreserved=True, runtimeValidated=False)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print('OPEN_ACCESS_APK_READY', report['testApk']['sha256'])
    finally:
        if TEMP.exists():
            resolved = TEMP.resolve()
            if resolved.parent != Path(r'D:\Environment\Android\temp').resolve() or resolved.name != 'witch-online-open-access':
                raise ValueError('Unsafe build temporary cleanup')
            shutil.rmtree(resolved)


if __name__ == '__main__':
    main()
