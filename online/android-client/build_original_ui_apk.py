"""Build an isolated original-Unity-login candidate without replacing the fallback APK.

The preserved author APK is pinned by SHA-256. Both IL2CPP ABIs are patched at
the two reviewed password call sites; the original Unity Activity stays the
launcher. Every signed payload entry is compared with the pinned source.
"""

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import zipfile

import build_online_apk as base
import patch_accconf_bundle
import patch_lua_bundle
import patch_original_auth
import patch_original_manifest
import patch_resources


PACKAGE = patch_original_manifest.PACKAGE
LAUNCHER = base.patch_manifest.GAME
MODE_ASSET = 'assets/original_ui_auth.txt'
MODE_VALUE = b'original-ui-v1\n'
DIAGNOSTIC_ASSET = 'assets/original_ui_diagnostics.txt'
DIAGNOSTIC_VALUE = b'diagnostic-v1\n'
DIAGNOSTIC = False
ROLE_ASSET = 'assets/original_ui_role_summary.txt'
ROLE_VALUE = b'role-summary-v1\n'
ROLE_SUMMARY = False
AUTH_DIAG_ASSET = 'assets/original_ui_auth_diagnostics.txt'
AUTH_DIAG_VALUE = b'auth-diagnostic-v1\n'
AUTH_DIAGNOSTIC = False
RESULT = base.OUTPUT / 'witchweapon-online-original-ui-test.apk'
REPORT = base.OUTPUT / '原版登录候选包验收.json'
PREVIOUS_CANDIDATE_SHA = '542ef116a878669733b0981f8b1b07ea037f11fc9725f48f021af2a4893c3800'
TEMP = Path(r'D:\Environment\Android\temp\witch-online-original-ui')
INTERMEDIATE_STEM = 'original-ui'
LIB_NAMES = {'lib/' + abi + '/libil2cpp.so' for abi in patch_original_auth.SPECS}
CHANGED = base.ALLOWED_CHANGED | LIB_NAMES
ADDED = {base.ENDPOINT_ASSET, MODE_ASSET}
LOOPBACK = 'http://127.0.0.1:19878'


def candidate_fixtures(raw):
    old = b'127.0.0.1:19877'
    new = b'127.0.0.1:19878'
    if raw.count(old) != 11 or new in raw:
        raise ValueError('Unexpected online account fixture endpoint count')
    patched = raw.replace(old, new)
    fixtures = json.loads(patched.decode('utf-8'))
    for path in ('/account/user/regist', '/account/user/login',
                 '/account/user/tokenlogin', '/account/user/token/get',
                 '/account/user/getZone'):
        zones = json.loads(fixtures[path]['body'])['Value']['ZoneInfo']
        if len(zones) != 1 or zones[0]['ServerIP'] != LOOPBACK:
            raise ValueError('Candidate account zone does not use isolated loopback port')
    if patched.count(new) != 11 or old in patched:
        raise ValueError('Candidate fixture loopback patch failed')
    return patched


def prepare():
    source_files, old_classes, replacements = base.check_inputs()
    with zipfile.ZipFile(base.SOURCE) as source:
        names = source.namelist()
        if MODE_ASSET in names or any(name not in names for name in LIB_NAMES):
            raise ValueError('Unexpected candidate asset or missing original IL2CPP library')
        replacements['AndroidManifest.xml'] = patch_original_manifest.patch(
            source.read('AndroidManifest.xml'))
        replacements['resources.arsc'] = patch_resources.patch(
            source.read('resources.arsc'), PACKAGE)
        replacements['assets/assetbundle/config/xmlconf/accconf.ab'] = \
            patch_accconf_bundle.patch(
                source.read('assets/assetbundle/config/xmlconf/accconf.ab'), LOOPBACK)
        lua = patch_lua_bundle.patch(source.read('assets/assetbundle/lua/lua.ab'), PACKAGE)
        replacements['assets/assetbundle/lua/lua.ab'] = lua
        replacements['assets/offline_responses.json'] = candidate_fixtures(
            replacements['assets/offline_responses.json'])
        replacements['assets/m.assets_list.txt'] = base.patch_index(
            source.read('assets/m.assets_list.txt'), {
                '/lua/lua.ab': lua,
                '/config/xmlconf/accconf.ab': replacements[
                    'assets/assetbundle/config/xmlconf/accconf.ab'],
            })
        for abi in patch_original_auth.SPECS:
            name = 'lib/' + abi + '/libil2cpp.so'
            replacements[name] = patch_original_auth.patch(source.read(name), abi)
    if set(replacements) != CHANGED - {'classes2.dex'}:
        raise ValueError('Candidate replacement set differs from reviewed entries')
    return source_files, old_classes, replacements


def compile_candidate(source_files, old_classes):
    base.TEMP = TEMP
    dex, classes = base.compile_dex(source_files, old_classes)
    if 'Lcom/codex/witchweapon/OriginalUiAuthBridge;' not in classes:
        raise ValueError('Compiled candidate lacks original UI account adapter')
    return dex, classes


def verify_signed(path, old_classes, new_classes, expected, origin):
    with zipfile.ZipFile(base.SOURCE) as source, zipfile.ZipFile(path) as signed:
        old_names = {name for name in source.namelist()
                     if not base.SIGNATURE.fullmatch(name)}
        new_names = {name for name in signed.namelist()
                     if not base.SIGNATURE.fullmatch(name)}
        if new_names != old_names | ADDED or len(signed.namelist()) != len(set(signed.namelist())):
            raise ValueError('Candidate APK entry set differs unexpectedly')
        changed = set()
        verified = 0
        for name in sorted(old_names):
            with source.open(name) as left, signed.open(name) as right:
                old_hash = hashlib.file_digest(left, 'sha256').digest()
                new_hash = hashlib.file_digest(right, 'sha256').digest()
            if old_hash != new_hash:
                changed.add(name)
            if name in CHANGED and new_hash != hashlib.sha256(expected[name]).digest():
                raise ValueError('Prepared replacement differs after signing: ' + name)
            verified += 1
        if changed != CHANGED:
            raise ValueError('Unreviewed candidate payload changes: ' + repr(sorted(changed)))
        if signed.read(base.ENDPOINT_ASSET) != (origin + '\n').encode('ascii'):
            raise ValueError('Candidate HTTPS origin changed')
        if signed.read(MODE_ASSET) != MODE_VALUE:
            raise ValueError('Original UI build-mode asset changed')
        if DIAGNOSTIC and signed.read(DIAGNOSTIC_ASSET) != DIAGNOSTIC_VALUE:
            raise ValueError('Diagnostic logging gate asset changed')
        if ROLE_SUMMARY and signed.read(ROLE_ASSET) != ROLE_VALUE:
            raise ValueError('Role summary gate asset changed')
        if AUTH_DIAGNOSTIC and signed.read(AUTH_DIAG_ASSET) != AUTH_DIAG_VALUE:
            raise ValueError('Account diagnostic gate asset changed')
        if base.dex_classes(signed.read('classes2.dex')) != new_classes \
                or not set(old_classes).issubset(new_classes):
            raise ValueError('Candidate DEX class set differs')
        for abi, spec in patch_original_auth.SPECS.items():
            raw = signed.read('lib/' + abi + '/libil2cpp.so')
            if len(raw) != spec['size']:
                raise ValueError('Patched IL2CPP size changed: ' + abi)
            for address, offset, original, replacement in spec['sites']:
                if patch_original_auth._elf_offset(raw, abi, address) != offset \
                        or raw[offset:offset + 4] != replacement:
                    raise ValueError('IL2CPP password call-site verification failed: ' + abi)
        if base.sha256(base.SOURCE) != base.SOURCE_SHA:
            raise ValueError('Preserved author APK changed during candidate build')
    return sorted(changed), verified


def build(origin, old_classes, new_classes, replacements, dex, replace_verified=False):
    base.OUTPUT.mkdir(exist_ok=True)
    unsigned = base.OUTPUT / (INTERMEDIATE_STEM + '-unsigned.apk')
    aligned = base.OUTPUT / (INTERMEDIATE_STEM + '-aligned.apk')
    candidate = base.OUTPUT / ('witchweapon-online-' + INTERMEDIATE_STEM + '-test.next.apk')
    candidate_report = base.OUTPUT / ('原版登录候选包验收.next.json'
                                      if INTERMEDIATE_STEM == 'original-ui'
                                      else INTERMEDIATE_STEM + '-report.next.json')
    if any(path.exists() for path in (unsigned, aligned, candidate,
                                       candidate_report, Path(str(candidate) + '.idsig'))):
        raise ValueError('Original UI candidate or unreviewed intermediate already exists')
    if replace_verified:
        if not RESULT.is_file() or not REPORT.is_file() \
                or base.sha256(RESULT) != PREVIOUS_CANDIDATE_SHA:
            raise ValueError('Previous candidate differs from the reviewed build')
        previous = json.loads(REPORT.read_text(encoding='utf-8'))
        if (previous.get('testApk', {}).get('sha256') != PREVIOUS_CANDIDATE_SHA
                or previous.get('package') != PACKAGE or previous.get('httpsOrigin') != origin):
            raise ValueError('Previous candidate report differs from the reviewed build')
    elif RESULT.exists() or REPORT.exists():
        raise ValueError('An original UI candidate already exists')
    if base.sha256(base.OUTPUT / 'witchweapon-online-test.apk') \
            != 'eea0cf30d32722f0efe64dea6642cbcef329e8cbc9a3a5e00428cb40d87dc242':
        raise ValueError('Validated fallback APK has changed')
    replacements = dict(replacements)
    replacements['classes2.dex'] = dex
    replacements[base.ENDPOINT_ASSET] = (origin + '\n').encode('ascii')
    replacements[MODE_ASSET] = MODE_VALUE
    if DIAGNOSTIC:
        replacements[DIAGNOSTIC_ASSET] = DIAGNOSTIC_VALUE
    if ROLE_SUMMARY:
        replacements[ROLE_ASSET] = ROLE_VALUE
    if AUTH_DIAGNOSTIC:
        replacements[AUTH_DIAG_ASSET] = AUTH_DIAG_VALUE
    expected = dict(replacements)
    with zipfile.ZipFile(base.SOURCE) as source, zipfile.ZipFile(
            unsigned, 'x', allowZip64=False) as target:
        for info in source.infolist():
            name = info.filename
            if base.SIGNATURE.fullmatch(name):
                continue
            if name in replacements:
                target.writestr(copy.copy(info), replacements.pop(name))
            else:
                base.copy_compressed_entry(source, target, info)
        if set(replacements) != ADDED:
            raise ValueError('Candidate payload replacements were not consumed')
        for name in sorted(ADDED):
            target.writestr(name, replacements[name], compress_type=zipfile.ZIP_STORED)
    base.run([base.TOOLS / 'zipalign.exe', '-p', '4', unsigned, aligned])
    env = os.environ.copy()
    env['TEMP'] = str(TEMP)
    env['TMP'] = str(TEMP)
    env['WITCH_TEST_KEYPASS'] = 'local-stage1'  # Existing local test key, not a VPS secret.
    signer = [base.JAVA, '-jar', base.TOOLS / 'lib/apksigner.jar']
    base.run([*signer, 'sign', '--ks', base.KEY, '--ks-key-alias', 'local',
              '--ks-pass', 'env:WITCH_TEST_KEYPASS', '--key-pass', 'env:WITCH_TEST_KEYPASS',
              '--out', candidate, aligned], env)
    signature = base.run([*signer, 'verify', '--verbose', '--print-certs', candidate], env)
    alignment = base.run([base.TOOLS / 'zipalign.exe', '-c', '-p', '4', candidate])
    # aapt on this Windows image is locale-sensitive; inspect an ASCII hardlink.
    alias = TEMP / (INTERMEDIATE_STEM + '-aapt-probe.apk')
    try:
        if alias.exists():
            raise ValueError('Prior candidate aapt probe exists')
        os.link(candidate, alias)
        badging = base.run([base.TOOLS / 'aapt.exe', 'dump', 'badging', alias])
        xml = base.run([base.TOOLS / 'aapt.exe', 'dump', 'xmltree', alias,
                        'AndroidManifest.xml'])
    finally:
        if alias.exists():
            alias.unlink()
    if ("package: name='" + PACKAGE + "'") not in badging \
            or ("launchable-activity: name='" + LAUNCHER + "'") not in badging \
            or "launchable-activity: name='com.codex.witchweapon.OnlineLoginActivity'" in badging \
            or 'android:exported(0x01010010)=(type 0x12)0x1' not in xml:
        raise ValueError('Candidate package or original Unity launcher failed aapt verification')
    changed, verified = verify_signed(candidate, old_classes, new_classes, expected, origin)
    report = {
        'status': 'signed_static_validation_only',
        'source': base.record(base.SOURCE),
        'testApk': base.record(candidate),
        'package': PACKAGE, 'launcher': LAUNCHER,
        'deviceLoopbackPort': 19878,
        'httpsOrigin': origin,
        'roleSummaryEnabled': ROLE_SUMMARY,
        'authDiagnosticsEnabled': AUTH_DIAGNOSTIC,
        'fallbackApkSha256': 'eea0cf30d32722f0efe64dea6642cbcef329e8cbc9a3a5e00428cb40d87dc242',
        'changedPayloadMembers': changed,
        'addedPayloadMembers': sorted(ADDED), 'verifiedPayloadMembers': verified,
        'dexClasses': new_classes,
        'signatureVerification': signature,
        'alignmentVerification': alignment,
        'nativePasswordCallSites': {
            abi: [hex(site[0]) for site in spec['sites']]
            for abi, spec in patch_original_auth.SPECS.items()},
        'notInstalled': True, 'runtimeValidated': False,
        'limits': [
            'Trusted emulator test only: other Android apps can reach loopback port 19878.',
            ('Role summary requires the deployed authenticated /api/v1/legacy-role endpoint '
             'and explicit metadata migration for the two older Java saves.' if ROLE_SUMMARY else
             'Original account ExistRoles remains the author fixture pending per-account role-state mapping.'),
            'The original Unity login UI and native password call-site behavior require device validation.',
        ],
    }
    report['testApk']['path'] = str(RESULT)
    if replace_verified:
        report['previousCandidateSha256'] = PREVIOUS_CANDIDATE_SHA
    candidate_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                encoding='utf-8')
    sidecar = Path(str(candidate) + '.idsig')
    if not sidecar.is_file():
        raise ValueError('Candidate v4 signature sidecar is missing')
    os.replace(candidate, RESULT)
    os.replace(sidecar, Path(str(RESULT) + '.idsig'))
    os.replace(candidate_report, REPORT)
    if base.sha256(RESULT) != report['testApk']['sha256']:
        raise ValueError('Final candidate differs from verified signed APK')
    for intermediate in (unsigned, aligned):
        if intermediate.resolve().parent != base.OUTPUT.resolve():
            raise ValueError('Unexpected candidate intermediate location')
        intermediate.unlink()
    return RESULT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--build', action='store_true')
    parser.add_argument('--origin', help='Candidate HTTPS origin asset')
    parser.add_argument('--replace-verified', action='store_true',
                        help='Replace only the pinned previous candidate after complete validation')
    args = parser.parse_args()
    if args.build and not args.origin:
        parser.error('--build requires --origin')
    if args.replace_verified and not args.build:
        parser.error('--replace-verified requires --build')
    origin = base.endpoint_origin(args.origin) if args.origin else None
    source_files, old_classes, replacements = prepare()
    dex, new_classes = compile_candidate(source_files, old_classes)
    if args.check:
        print('ORIGINAL_UI_ADAPTER_STATIC_CHECK_OK', len(new_classes), 'DEX classes')
        return
    result = build(origin, old_classes, new_classes, replacements, dex, args.replace_verified)
    print('ORIGINAL_UI_TEST_APK_BUILT', result, base.sha256(result))


if __name__ == '__main__':
    main()
