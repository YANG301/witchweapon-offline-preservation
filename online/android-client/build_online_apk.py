"""Build a separate, signed Android online test APK from the preserved author APK.

`--check` compiles and validates the small Android adapter without making an
APK. `--build --origin https://...` additionally creates the isolated test APK.
No source APK, author repository, installed app or Android user data is changed.
"""
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import zipfile
import zlib

import patch_accconf_bundle
import patch_autologin
import patch_lua_bundle
import patch_manifest
import patch_resources


HERE = Path(__file__).resolve().parent
SOURCE = Path(r'D:\Project\魔女兵器工程恢复\单机版\作者源码构建\构建产物\witchweapon-author-source.apk')
SOURCE_SHA = 'f16e8e4d913157e082ab3a770444a8b8995c47731a2a9e3b54372cb43f41f9cf'
PREVIOUS_TEST_SHA = '7ceae95be37b10b5df7236a15f89327dab6242b5d3686b25e20ae7b9677f4235'
AUTHOR = Path(r'D:\Project\魔女兵器工程恢复\作者单机版源码')
OUTPUT = HERE / 'build'
TEMP = Path(r'D:\Environment\Android\temp\witch-online-adapter')
JDK = Path(r'D:\Environment\Java\jdk8\bin')
JAVA = Path(r'D:\Environment\AndroidReverse\jadx-1.5.6\jre\bin\java.exe')
ANDROID = Path(r'D:\Environment\Android\platforms\android-28\android.jar')
TOOLS = Path(r'D:\Environment\Android\build-tools\35.0.0')
KEY = Path(r'D:\Project\魔女兵器工程恢复\单机版\作者源码构建\author-local-test.jks')
SIGNATURE = re.compile(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', re.I)
AUTHOR_HELPERS = ('LocalSave.java', 'LocalEconomy.java', 'ProtoWire.java')
ADAPTER = ('OfflineApplication.java', 'OnlineEndpoint.java', 'ChatWebSocketRelay.java',
           'OnlineLoginActivity.java', 'OnlineAuthTokens.java',
           'OnlineSessionStore.java', 'LegacyStateMirror.java',
           'OriginalUiAuthBridge.java', 'OriginalUiRoleSummary.java',
           'OriginalUiAuthDiagnostic.java')
ALLOWED_CHANGED = {'AndroidManifest.xml', 'resources.arsc', 'classes2.dex',
                   'assets/assetbundle/lua/lua.ab',
                   'assets/assetbundle/config/xmlconf/accconf.ab',
                   'assets/offline_responses.json', 'assets/m.assets_list.txt'}
ENDPOINT_ASSET = 'assets/online_endpoint.txt'
PACKAGE = 'com.codex.witchweapon.online.test'


def sha256(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def record(path):
    return {'path': str(path), 'bytes': Path(path).stat().st_size,
            'sha256': sha256(path)}


def endpoint_origin(value):
    if not value or value != value.strip() or any(c in value for c in '\r\n?#@\\'):
        raise ValueError('Origin must be one HTTPS host without query, fragment or credentials')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path not in ('', '/'):
        raise ValueError('Origin must be an HTTPS origin without a path')
    if not re.fullmatch(r'[A-Za-z0-9.-]+', parsed.hostname):
        raise ValueError('Only DNS names or IPv4 addresses are supported by this test build')
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError('Invalid HTTPS port') from exc
    if port is not None and not (1 <= port <= 65535):
        raise ValueError('Invalid HTTPS port')
    return 'https://' + parsed.netloc.lower()


def run(command, env=None):
    result = subprocess.run([str(piece) for piece in command], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=env, timeout=900)
    output = result.stdout.decode('utf-8', errors='replace').strip()
    if result.returncode:
        raise RuntimeError('Command failed: ' + str(command[0]) + '\n' + output[-4000:])
    return output


def copy_compressed_entry(source, target, info):
    """Copy unchanged ZIP payload bytes without decompressing game assets."""
    if info.file_size >= 0xffffffff or info.compress_size >= 0xffffffff:
        raise ValueError('ZIP64 member unexpectedly present')
    source.fp.seek(info.header_offset)
    header = source.fp.read(30)
    if header[:4] != b'PK\x03\x04':
        raise ValueError('Invalid source ZIP local header')
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


def dex_classes(raw):
    if raw[:4] != b'dex\n' or struct.unpack_from('<I', raw, 32)[0] != len(raw):
        raise ValueError('Invalid DEX header')
    if raw[12:32] != hashlib.sha1(raw[32:]).digest() \
            or struct.unpack_from('<I', raw, 8)[0] != zlib.adler32(raw[12:]) & 0xffffffff:
        raise ValueError('Invalid DEX checksum')
    strings, string_offset, types, type_offset = struct.unpack_from('<4I', raw, 56)
    classes, class_offset = struct.unpack_from('<2I', raw, 96)

    def get_string(index):
        if index >= strings:
            raise ValueError('Invalid DEX string index')
        offset = struct.unpack_from('<I', raw, string_offset + index * 4)[0]
        for _ in range(5):
            digit = raw[offset]
            offset += 1
            if digit < 128:
                break
        return raw[offset:raw.index(b'\0', offset)].decode('ascii')

    found = []
    for index in range(classes):
        type_index = struct.unpack_from('<I', raw, class_offset + index * 32)[0]
        if type_index >= types:
            raise ValueError('Invalid DEX type index')
        string_index = struct.unpack_from('<I', raw, type_offset + type_index * 4)[0]
        found.append(get_string(string_index))
    if len(found) != len(set(found)):
        raise ValueError('Duplicate DEX class descriptor')
    return sorted(found)


def patch_index(raw, bundles):
    text = raw.decode('utf-8')
    lines = text.splitlines()
    for name, data in bundles.items():
        target = '=' + name + ':'
        matched = [i for i, line in enumerate(lines) if target in line]
        if len(matched) != 1:
            raise ValueError('Expected one bundle index entry for ' + name)
        index = matched[0]
        old = lines[index]
        if not re.fullmatch(r'[0-9a-f]{32}=' + re.escape(name) + r':[0-9]+', old):
            raise ValueError('Unexpected bundle index format for ' + name)
        lines[index] = hashlib.md5(data).hexdigest() + '=' + name + ':' + str(len(data))
    result = ('\n'.join(lines) + '\n').encode('utf-8')
    for name in bundles:
        if result.count(('=' + name + ':').encode('ascii')) != 1:
            raise ValueError('Bundle index patch failed for ' + name)
    return result


def patch_fixtures(raw):
    old, new = b'127.0.0.1:19876', b'127.0.0.1:19877'
    if raw.count(old) != 11:
        raise ValueError('Unexpected count of original fixture endpoints')
    notice_path = '/Notice/fetchContent'
    old_title = '单人测试版'
    old_content = '本地运行测试。无需账号，进度保存在本机。'
    new_title = '在线保存版（测试）'
    new_content = '使用邮箱登录，进度保存在服务器；目前仅限受控模拟器。'
    old_zone_name = '本地单人存档'
    new_zone_name = '在线保存区'
    account_zone_paths = {
        '/account/user/regist', '/account/user/login',
        '/account/user/tokenlogin', '/account/user/token/get',
        '/account/user/getZone'}
    original = json.loads(raw.decode('utf-8'))
    optional_fixture = {'type': 'application/octet-stream', 'base64': ''}
    if original.get('/misc/getLeancloudInfo') != optional_fixture:
        raise ValueError('Optional Leancloud fixture is no longer a fixed empty protobuf')
    notice = json.loads(original[notice_path]['body'])
    if (notice.get('Title') != old_title or notice.get('Content') != old_content
            or notice.get('Value', {}).get('Title') != old_title
            or notice.get('Value', {}).get('Content') != old_content):
        raise ValueError('Original notice fixture differs from the reviewed text')
    old_title_bytes, old_content_bytes = old_title.encode('utf-8'), old_content.encode('utf-8')
    if raw.count(old_title_bytes) != 2 or raw.count(old_content_bytes) != 2:
        raise ValueError('Notice text appears outside the two expected JSON fields')
    zone_hits = {path for path, item in original.items()
                 if old_zone_name in item.get('body', '')}
    if zone_hits != account_zone_paths or raw.count(old_zone_name.encode('utf-8')) != len(account_zone_paths):
        raise ValueError('Unexpected original account zone-name locations')
    for path in account_zone_paths:
        zones = json.loads(original[path]['body'])['Value']['ZoneInfo']
        if (len(zones) != 1 or zones[0].get('ZoneName') != old_zone_name
                or zones[0].get('ZID') != '1'
                or zones[0].get('ServerIP') != 'http://127.0.0.1:19876'):
            raise ValueError('Original account zone fixture differs from expected')
    result = raw.replace(old, new)
    result = result.replace(old_title_bytes, new_title.encode('utf-8'))
    result = result.replace(old_content_bytes, new_content.encode('utf-8'))
    result = result.replace(old_zone_name.encode('utf-8'), new_zone_name.encode('utf-8'))
    if result.count(new) != 11 or old in result:
        raise ValueError('Fixture port replacement failed')
    updated = json.loads(result.decode('utf-8'))
    if updated.get('/misc/getLeancloudInfo') != optional_fixture:
        raise ValueError('Optional Leancloud fixture changed during online patching')
    updated_notice = json.loads(updated[notice_path]['body'])
    if (updated_notice.get('Title') != new_title or updated_notice.get('Content') != new_content
            or updated_notice.get('Value', {}).get('Title') != new_title
            or updated_notice.get('Value', {}).get('Content') != new_content
            or updated_notice.get('Ecode') != notice.get('Ecode')):
        raise ValueError('Target notice fixture was not updated consistently')
    if (result.count(new_zone_name.encode('utf-8')) != len(account_zone_paths)
            or old_zone_name.encode('utf-8') in result):
        raise ValueError('Account zone-name replacement failed')
    for path in account_zone_paths:
        before = json.loads(original[path]['body'])['Value']['ZoneInfo'][0]
        after = json.loads(updated[path]['body'])['Value']['ZoneInfo'][0]
        if (after.get('ZoneName') != new_zone_name
                or after.get('ServerIP') != 'http://127.0.0.1:19877'
                or {key: value for key, value in after.items() if key not in ('ZoneName', 'ServerIP')}
                    != {key: value for key, value in before.items() if key not in ('ZoneName', 'ServerIP')}):
            raise ValueError('Account zone protocol fields changed unexpectedly')
    return result


def check_inputs():
    if not SOURCE.is_file() or SOURCE.stat().st_size != 1795759861 or sha256(SOURCE) != SOURCE_SHA:
        raise ValueError('Preserved base APK changed or is unavailable')
    source_files = [HERE / 'src/com/codex/witchweapon' / name for name in ADAPTER]
    source_files += [AUTHOR / name for name in AUTHOR_HELPERS]
    required = source_files + [JDK / 'javac.exe', JAVA, ANDROID, TOOLS / 'lib/d8.jar',
                               TOOLS / 'zipalign.exe', TOOLS / 'lib/apksigner.jar',
                               TOOLS / 'aapt.exe', KEY]
    for path in required:
        if not path.is_file():
            raise ValueError('Missing pinned build input: ' + str(path))
    with zipfile.ZipFile(SOURCE) as apk:
        names = apk.namelist()
        if len(names) != len(set(names)) or ENDPOINT_ASSET in names:
            raise ValueError('Unexpected source APK entries')
        for name in ALLOWED_CHANGED:
            if name not in names:
                raise ValueError('Source APK is missing ' + name)
        manifest = patch_manifest.patch(apk.read('AndroidManifest.xml'))
        resources = patch_resources.patch(apk.read('resources.arsc'))
        lua = patch_autologin.patch(
            patch_lua_bundle.patch(apk.read('assets/assetbundle/lua/lua.ab')))
        accconf = patch_accconf_bundle.patch(apk.read('assets/assetbundle/config/xmlconf/accconf.ab'))
        fixtures = patch_fixtures(apk.read('assets/offline_responses.json'))
        index = patch_index(apk.read('assets/m.assets_list.txt'), {
            '/lua/lua.ab': lua, '/config/xmlconf/accconf.ab': accconf})
        classes = dex_classes(apk.read('classes2.dex'))
    return source_files, classes, {
        'AndroidManifest.xml': manifest, 'resources.arsc': resources,
        'assets/assetbundle/lua/lua.ab': lua,
        'assets/assetbundle/config/xmlconf/accconf.ab': accconf,
        'assets/offline_responses.json': fixtures,
        'assets/m.assets_list.txt': index}


def compile_dex(source_files, old_classes):
    classes_dir = TEMP / 'classes'
    dex_dir = TEMP / 'dex'
    # Only our two fixed build-cache children may be recursively cleared.
    if classes_dir.resolve().parent != TEMP.resolve() or dex_dir.resolve().parent != TEMP.resolve():
        raise ValueError('Unexpected build-cache target')
    if classes_dir.exists():
        shutil.rmtree(classes_dir)
    if dex_dir.exists():
        shutil.rmtree(dex_dir)
    classes_dir.mkdir(parents=True)
    dex_dir.mkdir()
    env = os.environ.copy()
    env['TEMP'] = str(TEMP)
    env['TMP'] = str(TEMP)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    run([JDK / 'javac.exe', '-encoding', 'UTF-8', '-source', '8', '-target', '8',
         '-classpath', ANDROID, '-d', classes_dir, *source_files], env)
    class_files = sorted(classes_dir.rglob('*.class'))
    if not class_files:
        raise ValueError('javac did not produce class files')
    run([JAVA, '-cp', TOOLS / 'lib/d8.jar', 'com.android.tools.r8.D8',
         '--min-api', '21', '--lib', ANDROID, '--output', dex_dir, *class_files], env)
    dex_path = dex_dir / 'classes.dex'
    if sorted(dex_dir.glob('*.dex')) != [dex_path]:
        raise ValueError('D8 produced an unexpected DEX set')
    raw = dex_path.read_bytes()
    classes = dex_classes(raw)
    required = {'Lcom/codex/witchweapon/OfflineApplication;',
                'Lcom/codex/witchweapon/OnlineLoginActivity;',
                'Lcom/codex/witchweapon/OnlineEndpoint;',
                'Lcom/codex/witchweapon/LegacyStateMirror;'}
    if not required.issubset(classes) or not set(old_classes).issubset(classes):
        raise ValueError('Compiled DEX lost the original helper classes')
    return raw, classes


def verify_apk(result, old_classes, new_classes, origin, expected):
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(result) as signed:
        a = {x for x in source.namelist() if not SIGNATURE.fullmatch(x)}
        b = {x for x in signed.namelist() if not SIGNATURE.fullmatch(x)}
        if b != a | {ENDPOINT_ASSET} or len(signed.namelist()) != len(set(signed.namelist())):
            raise ValueError('Signed APK member set differs unexpectedly')
        changed = set()
        verified = 0
        for name in sorted(a):
            with source.open(name) as left, signed.open(name) as right:
                old_hash = hashlib.file_digest(left, 'sha256').digest()
                new_hash = hashlib.file_digest(right, 'sha256').digest()
            if old_hash != new_hash:
                changed.add(name)
            if name in ALLOWED_CHANGED and new_hash != hashlib.sha256(expected[name]).digest():
                raise ValueError('Modified member differs from prepared replacement: ' + name)
            verified += 1
        if changed != ALLOWED_CHANGED:
            raise ValueError('Unexpected changed APK entries: ' + repr(sorted(changed)))
        if signed.read(ENDPOINT_ASSET) != (origin + '\n').encode('ascii'):
            raise ValueError('HTTPS endpoint asset differs')
        if dex_classes(signed.read('classes2.dex')) != new_classes:
            raise ValueError('Signed APK DEX class set differs')
        if not set(old_classes).issubset(new_classes):
            raise ValueError('Missing legacy helper DEX classes')
        # The modified Unity AssetBundle was parsed and round-tripped before
        # packaging; its exact bytes were checked above after signing.
    return sorted(changed), verified


def build(origin, old_classes, new_classes, replacements, dex, replace_verified=False):
    OUTPUT.mkdir(exist_ok=True)
    unsigned = OUTPUT / 'online-unsigned.apk'
    aligned = OUTPUT / 'online-aligned.apk'
    result = OUTPUT / 'witchweapon-online-test.apk'
    report_path = OUTPUT / '在线测试包验收.json'
    candidate = OUTPUT / 'witchweapon-online-test.next.apk' if replace_verified else result
    candidate_report = OUTPUT / '在线测试包验收.next.json' if replace_verified else report_path
    if any(path.exists() for path in (unsigned, aligned, candidate, candidate_report)):
        raise ValueError('An unreviewed build candidate or intermediate already exists')
    if replace_verified:
        if not result.is_file() or not report_path.is_file() or sha256(result) != PREVIOUS_TEST_SHA:
            raise ValueError('Existing test APK does not match the reviewed previous build')
        previous = json.loads(report_path.read_text(encoding='utf-8'))
        if (previous.get('testApk', {}).get('sha256') != PREVIOUS_TEST_SHA
                or previous.get('package') != PACKAGE
                or previous.get('httpsOrigin') != origin):
            raise ValueError('Existing validation report does not match the reviewed test APK')
    replacements = dict(replacements)
    replacements['classes2.dex'] = dex
    replacements[ENDPOINT_ASSET] = (origin + '\n').encode('ascii')
    expected = dict(replacements)
    with zipfile.ZipFile(SOURCE) as source, zipfile.ZipFile(unsigned, 'x', allowZip64=False) as target:
        for info in source.infolist():
            name = info.filename
            if SIGNATURE.fullmatch(name):
                continue
            if name in replacements:
                target.writestr(copy.copy(info), replacements.pop(name))
            else:
                copy_compressed_entry(source, target, info)
        if set(replacements) != {ENDPOINT_ASSET}:
            raise ValueError('APK replacements were not consumed as expected')
        target.writestr(ENDPOINT_ASSET, replacements[ENDPOINT_ASSET], compress_type=zipfile.ZIP_STORED)
    run([TOOLS / 'zipalign.exe', '-p', '4', unsigned, aligned])
    env = os.environ.copy()
    env['TEMP'] = str(TEMP)
    env['TMP'] = str(TEMP)
    env['WITCH_TEST_KEYPASS'] = 'local-stage1'  # Test-only key, never a server credential.
    signer = [JAVA, '-jar', TOOLS / 'lib/apksigner.jar']
    run([*signer, 'sign', '--ks', KEY, '--ks-key-alias', 'local',
         '--ks-pass', 'env:WITCH_TEST_KEYPASS', '--key-pass', 'env:WITCH_TEST_KEYPASS',
         '--out', candidate, aligned], env)
    signature = run([*signer, 'verify', '--verbose', '--print-certs', candidate], env)
    alignment = run([TOOLS / 'zipalign.exe', '-c', '-p', '4', candidate])
    # aapt is locale-sensitive on this machine, so use a temporary ASCII path.
    alias = TEMP / 'online-aapt-probe.apk'
    try:
        if alias.exists():
            alias.unlink()
        os.link(candidate, alias)
        badging = run([TOOLS / 'aapt.exe', 'dump', 'badging', alias])
        xml = run([TOOLS / 'aapt.exe', 'dump', 'xmltree', alias, 'AndroidManifest.xml'])
    finally:
        if alias.exists():
            alias.unlink()
    if ("package: name='" + PACKAGE + "'") not in badging \
            or "launchable-activity: name='com.codex.witchweapon.OnlineLoginActivity'" not in badging \
            or 'android:exported(0x01010010)=(type 0x12)0x1' not in xml:
        raise ValueError('Manifest package, launcher or exported flag failed aapt verification')
    changed, verified = verify_apk(candidate, old_classes, new_classes, origin, expected)
    if sha256(SOURCE) != SOURCE_SHA:
        raise ValueError('Original source APK changed during build')
    report = {
        'status': 'signed_static_validation_only', 'source': record(SOURCE),
        'testApk': record(candidate), 'package': PACKAGE, 'launcher': patch_manifest.LOGIN,
        'httpsOrigin': origin, 'changedPayloadMembers': changed,
        'addedPayloadMembers': [ENDPOINT_ASSET], 'verifiedPayloadMembers': verified,
        'dexClasses': new_classes,
        'signatureVerification': signature, 'alignmentVerification': alignment,
        'notInstalled': True, 'runtimeValidated': False,
        'limits': ['Trusted emulator test only: other Android apps can access loopback port 19877.',
                   'Original Unity login still uses local account fixtures after native HTTPS login.',
                   'Original APK network security config has broader cleartext permission.']}
    report['testApk']['path'] = str(result)
    if replace_verified:
        report['previousTestApkSha256'] = PREVIOUS_TEST_SHA
    candidate_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if replace_verified:
        # The reviewed old APK remains intact until the new candidate passes
        # signature, manifest, DEX and every non-signature member check.
        candidate_sidecar = Path(str(candidate) + '.idsig')
        final_sidecar = Path(str(result) + '.idsig')
        if not candidate_sidecar.is_file():
            raise ValueError('New v4 signature sidecar is missing')
        os.replace(candidate, result)
        os.replace(candidate_sidecar, final_sidecar)
        os.replace(candidate_report, report_path)
        if sha256(result) != report['testApk']['sha256']:
            raise ValueError('Final replaced test APK differs from validated candidate')
    for intermediate in (unsigned, aligned):
        if intermediate.resolve().parent != OUTPUT.resolve():
            raise ValueError('Refusing to delete an unexpected intermediate path')
        intermediate.unlink()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--build', action='store_true')
    parser.add_argument('--origin', help='HTTPS origin written into the test APK asset')
    parser.add_argument('--replace-verified', action='store_true',
                        help='Replace only the pinned previous test APK after full candidate validation')
    args = parser.parse_args()
    origin = endpoint_origin(args.origin) if args.origin else None
    if args.build and not origin:
        parser.error('--build requires --origin')
    if args.replace_verified and not args.build:
        parser.error('--replace-verified requires --build')
    files, old_classes, replacements = check_inputs()
    dex, new_classes = compile_dex(files, old_classes)
    if args.check:
        print('ONLINE_ADAPTER_STATIC_CHECK_OK', len(new_classes), 'DEX classes')
        return
    result = build(origin, old_classes, new_classes, replacements, dex, args.replace_verified)
    print('ONLINE_TEST_APK_BUILT', result, sha256(result))


if __name__ == '__main__':
    main()
