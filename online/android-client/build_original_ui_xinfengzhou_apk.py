"""Make an isolated Xinfengzhou zone APK from the signed remember-v1 APK.

The previous signed APK is pinned and never overwritten. This version changes
only five account-response ZoneName values. The existing local notice, game
code, account endpoints, saved-login support and other assets are copied.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / 'build'
SOURCE = OUTPUT / 'witchweapon-online-original-ui-remember-v1-test.apk'
SOURCE_SHA256 = '42bf2043ba34efca1b7405d42a356ca4fc4dbfc912aee8281eadbaeaef36b30c'
RESULT = OUTPUT / 'witchweapon-online-original-ui-xinfengzhou-v1-test.apk'
REPORT = OUTPUT / '原版登录新丰洲区服候选包验收.json'
FIXTURE = 'assets/offline_responses.json'
ENDPOINT_ASSET = 'assets/online_endpoint.txt'
MODE_ASSET = 'assets/original_ui_auth.txt'
ROLE_ASSET = 'assets/original_ui_role_summary.txt'
MODE_VALUE = b'original-ui-v1\n'
ROLE_VALUE = b'role-summary-v1\n'
ORIGIN = 'https://212.192.15.11:18443'
LOOPBACK = 'http://127.0.0.1:19878'
PACKAGE = 'com.codex.witchweapon.online.originalui.test'
LAUNCHER = 'com.shuiqinling.ww.android.LingGameActivity'
SIGNATURE = re.compile(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', re.I)
JAVA = Path(r'D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe')
TOOLS = Path(r'D:\Environment\Android\build-tools\35.0.0')
KEY = Path(r'D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks')
NOTICE = '/Notice/fetchContent'
ACCOUNT_ROUTES = frozenset({
    '/account/user/regist', '/account/user/login',
    '/account/user/tokenlogin', '/account/user/token/get',
    '/account/user/getZone',
})

OLD_TITLE = '在线保存版（测试）'
OLD_CONTENT = '使用邮箱登录，进度保存在服务器；目前仅限受控模拟器。'
OLD_ZONE = '在线保存区'
ZONE = '新丰洲'
TEMP = Path(r'D:\Environment\Android\temp\witch-online-xinfengzhou-v1')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def stream_digest(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.digest()


def record(path):
    return {'path': str(path), 'bytes': Path(path).stat().st_size,
            'sha256': sha256(path)}


def run(command, env=None):
    completed = subprocess.run([str(piece) for piece in command],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               env=env, timeout=900)
    output = completed.stdout.decode('utf-8', errors='replace').strip()
    if completed.returncode:
        raise RuntimeError('Command failed: ' + str(command[0]) + '\n' + output[-4000:])
    return output


def copy_compressed_entry(source, target, info):
    """Copy unchanged ZIP members without decompressing the large game assets."""
    if info.file_size >= 0xffffffff or info.compress_size >= 0xffffffff:
        raise ValueError('Unexpected ZIP64 member')
    source.fp.seek(info.header_offset)
    header = source.fp.read(30)
    if header[:4] != b'PK\x03\x04':
        raise ValueError('Invalid source ZIP member')
    names, extra = struct.unpack_from('<HH', header, 26)
    size = 30 + names + extra + info.compress_size
    if info.flag_bits & 8:
        source.fp.seek(info.header_offset + size)
        size += 16 if source.fp.read(4) == b'PK\x07\x08' else 12
    copied = copy.copy(info)
    target.fp.seek(target.start_dir)
    copied.header_offset = target.fp.tell()
    target._writecheck(copied)
    target._didModify = True
    source.fp.seek(info.header_offset)
    remaining = size
    while remaining:
        chunk = source.fp.read(min(1048576, remaining))
        if not chunk:
            raise ValueError('Truncated source ZIP member')
        target.fp.write(chunk)
        remaining -= len(chunk)
    target.start_dir = target.fp.tell()
    target.filelist.append(copied)
    target.NameToInfo[copied.filename] = copied


def read_source():
    if not SOURCE.is_file() or sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError('Pinned remember-v1 APK is missing or changed')
    required_tools = (JAVA, TOOLS / 'zipalign.exe', TOOLS / 'lib/apksigner.jar',
                      TOOLS / 'aapt.exe', KEY)
    if any(not path.is_file() for path in required_tools):
        raise ValueError('Portable APK signing tools or test key are missing')
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or FIXTURE not in names:
            raise ValueError('Invalid remember-v1 APK entry set')
        if apk.read(MODE_ASSET) != MODE_VALUE:
            raise ValueError('Remember-v1 APK does not use the original login UI')
        if apk.read(ROLE_ASSET) != ROLE_VALUE:
            raise ValueError('Remember-v1 APK lacks authenticated role summaries')
        origin = apk.read(ENDPOINT_ASSET).decode('ascii').strip()
        if origin != ORIGIN:
            raise ValueError('Invalid pinned HTTPS endpoint')
        raw = apk.read(FIXTURE)
    return raw, origin


def patch_fixture(raw):
    before = json.loads(raw.decode('utf-8'))
    old_notice = json.loads(before[NOTICE]['body'])
    if (old_notice.get('Title') != OLD_TITLE
            or old_notice.get('Content') != OLD_CONTENT
            or old_notice.get('Value', {}).get('Title') != OLD_TITLE
            or old_notice.get('Value', {}).get('Content') != OLD_CONTENT
            or old_notice.get('Ecode') != ''):
        raise ValueError('Previous notice differs from the reviewed online text')
    hits = {path for path, item in before.items()
            if isinstance(item, dict) and OLD_ZONE in item.get('body', '')}
    if hits != ACCOUNT_ROUTES:
        raise ValueError('Previous zone name occurs outside the five account replies')
    for path in ACCOUNT_ROUTES:
        zones = json.loads(before[path]['body'])['Value']['ZoneInfo']
        if (len(zones) != 1 or zones[0].get('ZoneName') != OLD_ZONE
                or zones[0].get('ZID') != '1'
                or zones[0].get('ZoneStatus') != '10'
                or zones[0].get('ServerIP') != LOOPBACK):
            raise ValueError('Previous account zone protocol differs from remember-v1')

    old_zone = OLD_ZONE.encode('utf-8')
    if raw.count(old_zone) != len(ACCOUNT_ROUTES):
        raise ValueError('Unexpected zone text outside five account replies')
    result = raw.replace(old_zone, ZONE.encode('utf-8'))
    after = json.loads(result.decode('utf-8'))
    if set(after) != set(before):
        raise ValueError('Fixture route set changed')

    for path in before:
        if path == NOTICE:
            if after[path] != before[path]:
                raise ValueError('Existing notice changed')
        elif path in ACCOUNT_ROUTES:
            expected_item = copy.deepcopy(before[path])
            expected_value = json.loads(expected_item.pop('body'))
            expected_value['Value']['ZoneInfo'][0]['ZoneName'] = ZONE
            actual_item = copy.deepcopy(after[path])
            actual_value = json.loads(actual_item.pop('body'))
            if actual_item != expected_item or actual_value != expected_value:
                raise ValueError('Account reply changed beyond its zone name: ' + path)
        elif after[path] != before[path]:
            raise ValueError('Unrelated fixture changed: ' + path)
    return result


def verify_signed(path, expected_fixture):
    with zipfile.ZipFile(SOURCE) as old, zipfile.ZipFile(path) as new:
        old_names = {name for name in old.namelist() if not SIGNATURE.fullmatch(name)}
        new_names = {name for name in new.namelist() if not SIGNATURE.fullmatch(name)}
        if (new_names != old_names or len(new.namelist()) != len(set(new.namelist()))
                or new.read(FIXTURE) != expected_fixture):
            raise ValueError('Signed Xinfengzhou APK has unexpected payload members')
        verified = 0
        for name in sorted(old_names - {FIXTURE}):
            with old.open(name) as left, new.open(name) as right:
                if stream_digest(left) != stream_digest(right):
                    raise ValueError('Unrelated signed APK member changed: ' + name)
            verified += 1
    return verified


def build(expected_fixture, origin):
    output = OUTPUT
    unsigned = output / 'xinfengzhou-v1-unsigned.apk'
    aligned = output / 'xinfengzhou-v1-aligned.apk'
    candidate = output / 'witchweapon-online-original-ui-xinfengzhou-v1-test.next.apk'
    candidate_report = output / 'xinfengzhou-v1-report.next.json'
    if any(path.exists() for path in (RESULT, REPORT, unsigned, aligned,
                                      candidate, candidate_report,
                                      Path(str(candidate) + '.idsig'))):
        raise ValueError('Xinfengzhou output or intermediate already exists')
    TEMP.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(
            unsigned, 'x', allowZip64=False) as target:
        for info in source.infolist():
            if SIGNATURE.fullmatch(info.filename):
                continue
            if info.filename == FIXTURE:
                target.writestr(copy.copy(info), expected_fixture)
            else:
                copy_compressed_entry(source, target, info)
    run([TOOLS / 'zipalign.exe', '-p', '4', unsigned, aligned])
    env = os.environ.copy()
    env['TEMP'] = str(TEMP)
    env['TMP'] = str(TEMP)
    env['WITCH_TEST_KEYPASS'] = 'local-stage1'  # Existing local APK test key.
    signer = [JAVA, '-jar', TOOLS / 'lib/apksigner.jar']
    run([*signer, 'sign', '--ks', KEY, '--ks-key-alias', 'local',
              '--ks-pass', 'env:WITCH_TEST_KEYPASS', '--key-pass', 'env:WITCH_TEST_KEYPASS',
              '--out', candidate, aligned], env)
    signature = run([*signer, 'verify', '--verbose', '--print-certs', candidate], env)
    alignment = run([TOOLS / 'zipalign.exe', '-c', '-p', '4', candidate])
    # aapt on this Windows image is locale-sensitive; inspect an ASCII hardlink.
    alias = TEMP / 'xinfengzhou-v1-aapt-probe.apk'
    try:
        if alias.exists():
            raise ValueError('Previous Xinfengzhou aapt probe exists')
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
        raise ValueError('Signed Xinfengzhou package or original Unity launcher changed')
    verified = verify_signed(candidate, expected_fixture)
    if sha256(SOURCE) != SOURCE_SHA256:
        raise ValueError('Pinned remember-v1 APK changed during build')
    report = {
        'status': 'signed_static_validation_only',
        'source': record(SOURCE),
        'testApk': record(candidate),
        'package': PACKAGE,
        'launcher': LAUNCHER,
        'httpsOrigin': origin,
        'noticeTitle': OLD_TITLE,
        'noticeContent': OLD_CONTENT,
        'zoneName': ZONE,
        'changedPayloadMembers': [FIXTURE],
        'verifiedUnchangedPayloadMembers': verified,
        'signatureVerification': signature,
        'alignmentVerification': alignment,
        'notInstalled': True,
        'runtimeValidated': False,
    }
    report['testApk']['path'] = str(RESULT)
    candidate_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                encoding='utf-8')
    sidecar = Path(str(candidate) + '.idsig')
    if not sidecar.is_file():
        raise ValueError('Signed Xinfengzhou APK sidecar is missing')
    os.replace(candidate, RESULT)
    os.replace(sidecar, Path(str(RESULT) + '.idsig'))
    os.replace(candidate_report, REPORT)
    if sha256(RESULT) != report['testApk']['sha256']:
        raise ValueError('Final Xinfengzhou APK differs from verified candidate')
    for intermediate in (unsigned, aligned):
        if intermediate.resolve().parent != output.resolve():
            raise ValueError('Unexpected Xinfengzhou intermediate location')
        intermediate.unlink()
    return RESULT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--build', action='store_true')
    args = parser.parse_args()
    raw, origin = read_source()
    expected_fixture = patch_fixture(raw)
    if args.check:
        print('XINFENGZHOU_ZONE_STATIC_CHECK_OK', hashlib.sha256(expected_fixture).hexdigest())
    else:
        result = build(expected_fixture, origin)
        print('XINFENGZHOU_TEST_APK_BUILT', result, sha256(result))


if __name__ == '__main__':
    main()
