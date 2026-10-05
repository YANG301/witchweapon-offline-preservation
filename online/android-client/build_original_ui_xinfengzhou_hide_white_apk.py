"""Remove the obsolete white launch notice from the signed Xinfengzhou APK.

The original APK is pinned and never overwritten. Only the four textual fields
of /Notice/fetchContent in assets/offline_responses.json become empty strings.
The blue in-game announcement, account fixtures, assets and code stay intact.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import zipfile

from build_original_ui_xinfengzhou_apk import copy_compressed_entry, run, sha256, stream_digest


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'build'
SOURCE = OUTPUT / 'witchweapon-online-original-ui-xinfengzhou-v1-test.apk'
SOURCE_SHA256 = '610822788650f1fd747f6848534601fe99bbae357c6d20cd4fa3aef825f83c3a'
RESULT = OUTPUT / 'witchweapon-online-original-ui-xinfengzhou-hide-white-v2-test.apk'
REPORT = OUTPUT / '原版登录新丰洲移除白色公告候选包验收.json'
FIXTURE = 'assets/offline_responses.json'
NOTICE = '/Notice/fetchContent'
PACKAGE = 'com.codex.witchweapon.online.originalui.test'
LAUNCHER = 'com.shuiqinling.ww.android.LingGameActivity'
SIGNATURE = re.compile(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', re.I)
JAVA = Path(r'D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe')
TOOLS = Path(r'D:\Environment\Android\build-tools\35.0.0')
KEY = Path(r'D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks')
TEMP = Path(r'D:\Environment\Android\temp\witch-online-xinfengzhou-hide-white-v2')


def record(path):
    return {'path': str(path), 'bytes': path.stat().st_size, 'sha256': sha256(path)}


def read_source():
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError('Pinned Xinfengzhou v1 APK is missing or changed')
    for path in (JAVA, TOOLS / 'zipalign.exe', TOOLS / 'lib/apksigner.jar',
                 TOOLS / 'aapt.exe', KEY):
        if not path.is_file():
            raise ValueError('Portable APK signing tool or local test key is missing: ' + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or FIXTURE not in names:
            raise ValueError('Invalid Xinfengzhou APK entry set')
        return apk.read(FIXTURE)


def patch_fixture(raw):
    before = json.loads(raw.decode('utf-8'))
    item = before[NOTICE]
    if item.get('type') != 'application/json' or set(item) != {'type', 'body'}:
        raise ValueError('Unexpected launch-notice route metadata')
    notice = json.loads(item['body'])
    if (set(notice) != {'Title', 'Content', 'Ecode', 'Value'}
            or set(notice['Value']) != {'Title', 'Content'}
            or notice['Ecode'] != ''
            or not isinstance(notice['Title'], str)
            or not isinstance(notice['Content'], str)
            or not notice['Title'].strip()
            or not notice['Content'].strip()
            or notice['Value']['Title'] != notice['Title']
            or notice['Value']['Content'] != notice['Content']):
        raise ValueError('Pinned launch-notice response differs from expected shape')
    old_title = notice['Title'].encode('utf-8')
    old_content = notice['Content'].encode('utf-8')
    if (old_title in old_content or old_content in old_title
            or raw.count(old_title) != 2 or raw.count(old_content) != 2):
        raise ValueError('Notice text is not confined to its four expected fields')
    result = raw.replace(old_title, b'').replace(old_content, b'')
    after = json.loads(result.decode('utf-8'))
    expected = copy.deepcopy(before)
    expected_notice = copy.deepcopy(notice)
    expected_notice['Title'] = ''
    expected_notice['Content'] = ''
    expected_notice['Value']['Title'] = ''
    expected_notice['Value']['Content'] = ''
    expected[NOTICE]['body'] = json.dumps(expected_notice, ensure_ascii=False)
    if set(after) != set(before):
        raise ValueError('Fixture route set changed')
    for route in before:
        if route == NOTICE:
            if (after[route]['type'] != before[route]['type']
                    or json.loads(after[route]['body']) != expected_notice):
                raise ValueError('Launch notice changed beyond its four text fields')
        elif after[route] != before[route]:
            raise ValueError('Unrelated fixture route changed: ' + route)
    return result, {'beforeTitle': notice['Title'],
                    'beforeContent': notice['Content']}


def verify_payload(path, expected_fixture):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {n for n in old.namelist() if not SIGNATURE.fullmatch(n)}
        new_names = {n for n in new.namelist() if not SIGNATURE.fullmatch(n)}
        if (new_names != old_names or len(new.namelist()) != len(set(new.namelist()))
                or new.read(FIXTURE) != expected_fixture):
            raise ValueError('Signed APK has unexpected payload members')
        verified = 0
        for name in sorted(old_names - {FIXTURE}):
            with old.open(name) as left, new.open(name) as right:
                if stream_digest(left) != stream_digest(right):
                    raise ValueError('Unrelated APK member changed: ' + name)
            verified += 1
    return verified


def build(fixture, old_notice):
    unsigned = OUTPUT / 'xinfengzhou-hide-white-v2-unsigned.apk'
    aligned = OUTPUT / 'xinfengzhou-hide-white-v2-aligned.apk'
    candidate = OUTPUT / 'witchweapon-online-original-ui-xinfengzhou-hide-white-v2-test.next.apk'
    next_report = OUTPUT / 'xinfengzhou-hide-white-v2-report.next.json'
    sidecar = Path(str(candidate) + '.idsig')
    if any(p.exists() for p in (RESULT, REPORT, unsigned, aligned,
                                candidate, next_report, sidecar)):
        raise ValueError('Versioned output or intermediate already exists')
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(
            unsigned, 'x', allowZip64=False) as target:
        for info in source.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == FIXTURE:
                target.writestr(copy.copy(info), fixture)
            else:
                copy_compressed_entry(source, target, info)
    run([TOOLS / 'zipalign.exe', '-p', '4', unsigned, aligned])
    env = os.environ.copy()
    env['TEMP'] = str(TEMP)
    env['TMP'] = str(TEMP)
    env['WITCH_TEST_KEYPASS'] = 'local-stage1'
    signer = [JAVA, '-jar', TOOLS / 'lib/apksigner.jar']
    run([*signer, 'sign', '--ks', KEY, '--ks-key-alias', 'local',
         '--ks-pass', 'env:WITCH_TEST_KEYPASS',
         '--key-pass', 'env:WITCH_TEST_KEYPASS', '--out', candidate, aligned], env)
    signature = run([*signer, 'verify', '--verbose', '--print-certs', candidate], env)
    alignment = run([TOOLS / 'zipalign.exe', '-c', '-p', '4', candidate])
    alias = TEMP / 'xinfengzhou-hide-white-v2-aapt-probe.apk'
    try:
        if alias.exists():
            raise ValueError('Previous aapt probe exists')
        os.link(candidate, alias)
        badging = run([TOOLS / 'aapt.exe', 'dump', 'badging', alias])
        xml = run([TOOLS / 'aapt.exe', 'dump', 'xmltree', alias,
                   'AndroidManifest.xml'])
    finally:
        if alias.exists():
            alias.unlink()
    if (("package: name='" + PACKAGE + "'") not in badging
            or ("launchable-activity: name='" + LAUNCHER + "'") not in badging
            or "launchable-activity: name='com.codex.witchweapon.OnlineLoginActivity'" in badging
            or 'android:exported(0x01010010)=(type 0x12)0x1' not in xml):
        raise ValueError('Original Unity launcher or package changed')
    verified = verify_payload(candidate, fixture)
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError('Pinned Xinfengzhou v1 APK changed during build')
    report = {
        'status': 'signed_static_validation_only',
        'source': record(SOURCE),
        'testApk': record(candidate),
        'package': PACKAGE,
        'launcher': LAUNCHER,
        'noticeRoute': NOTICE,
        'noticeType': 'application/json',
        'noticeEcode': '',
        'noticeTitle': '',
        'noticeContent': '',
        'previousNotice': old_notice,
        'changedPayloadMembers': [FIXTURE],
        'verifiedUnchangedPayloadMembers': verified,
        'signatureVerification': signature,
        'alignmentVerification': alignment,
        'notInstalled': True,
        'runtimeValidated': False,
    }
    report['testApk']['path'] = str(RESULT)
    next_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    if not sidecar.is_file():
        raise ValueError('Signed APK sidecar is missing')
    os.replace(candidate, RESULT)
    os.replace(sidecar, Path(str(RESULT) + '.idsig'))
    os.replace(next_report, REPORT)
    if sha256(RESULT) != report['testApk']['sha256']:
        raise ValueError('Final APK differs from verified candidate')
    for intermediate in (unsigned, aligned):
        if intermediate.resolve().parent != OUTPUT.resolve():
            raise ValueError('Unexpected intermediate location')
        intermediate.unlink()
    try:
        TEMP.rmdir()
    except OSError:
        pass
    return RESULT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--build', action='store_true')
    args = parser.parse_args()
    fixture, old_notice = patch_fixture(read_source())
    if args.check:
        print('XINFENGZHOU_HIDE_WHITE_STATIC_CHECK_OK', hashlib.sha256(fixture).hexdigest())
    else:
        result = build(fixture, old_notice)
        print('XINFENGZHOU_HIDE_WHITE_TEST_APK_BUILT', result, sha256(result))


if __name__ == '__main__':
    main()
