"""Compile the minimal combat change and test actual role preparation."""
from pathlib import Path
import base64
import copy
import csv
import hashlib
import json
import re
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PROJECT / 'tools'), str(PROJECT / 'android-client')]
import build_combat_weapon_repair as wire
from build_online_apk import copy_compressed_entry

OUT = PROJECT / '验收/战斗全面核查/候选'
TEMP = Path(r'D:\Environment\Java\temp\witch-combat-alignment')
JDK = Path(r'D:\Environment\Java\jdk8\bin')
JSON_JAR = Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
BASE_JAR = PROJECT / '构建/战斗修复/witchweapon-legacy.jar'


def sha(raw): return hashlib.sha256(raw).hexdigest()


def run(arguments):
    completed = subprocess.run([str(a) for a in arguments], capture_output=True, timeout=120)
    text = (completed.stdout + completed.stderr).decode('utf-8', errors='replace')
    if completed.returncode: raise RuntimeError(text)
    return text


def methods(text):
    parts = re.split(r'\n  (?=[A-Za-z][^\n]*\([^\n]*\)[^\n]*;)', text)
    result = {}
    for part in parts[1:]:
        lines = part.strip().splitlines()
        result[lines[0]] = re.sub(r'#\d+', '#CP', '\n'.join(lines)).strip().removesuffix('}').strip()
    return result


def cases():
    fixture = json.loads((OUT / 'offline_responses.json').read_text(encoding='utf-8'))
    role = wire.role_class()()
    role.ParseFromString(base64.b64decode(fixture['/combat/role/info']['base64']))
    original = Path(r'D:\Project\魔女兵器工程恢复\原版\可读脚本与配置\配置\clientexel')
    def table(name):
        with (original / (name+'.txt')).open(encoding='utf-8-sig', newline='') as stream:
            return {int(r['ID']):r for r in csv.DictReader(stream) if r['ID'].isdigit()}
    servants, ranks = table('servant'), table('servantrankinfo')
    effects = json.loads((PROJECT / '验收/战斗全面核查/95条武器被动等级接入断言.json').read_text(encoding='utf-8'))['rows']
    result = []
    seen = set()
    for sv in role.SvCombatInfo:
        for rank, account_level in ((1,1),(10,50)):
            level = 7 + (sv.SvWeaponCardID % 31)
            source = ranks[int(servants[sv.SvCardID]['rank_info'])*100 + rank]
            owned = [r for r in effects if r['servantID']==sv.SvCardID and r['weaponID']==sv.SvWeaponCardID]
            seen.update(r['spellID'] for r in owned)
            result.append(dict(servant=sv.SvCardID, weapon=sv.SvWeaponCardID, rank=rank,
                weaponLevel=level, accountLevel=account_level,
                accountExp=sum(fixture['_catalog']['roleLevels'][str(n)] for n in range(1,account_level)),
                energy=[int(source[k]) for k in ('energy_restore_time','energy_restore_killing_time',
                    'energy_restore_attacked','energy_restore_injured')],
                spells=sorted({r['spellID'] for r in owned}), triggers=sorted({r['triggerID'] for r in owned}),
                buffs=sorted({int(b) for r in owned for b in r['directBuffIDArgs']})))
    assert len(seen) == 95 and len(result)==144
    path = TEMP / 'original-csv-cases.json'
    path.write_text(json.dumps(dict(cases=result), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    return path


def main():
    assert sha(BASE_JAR.read_bytes()) == '8b29468d3de3dc5fd58cc31cd422da2039fd072feae2319a1994290a38904655'
    classes = TEMP / 'candidate-classes'; classes.mkdir(parents=True, exist_ok=True)
    test_classes = TEMP / 'test-classes'; test_classes.mkdir(parents=True, exist_ok=True)
    source = PROJECT / 'legacy-server/src/com/codex/witchweapon'
    run([JDK/'javac.exe','-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
         '-cp',str(BASE_JAR)+';'+str(JSON_JAR),'-d',classes,
         source/'LocalEconomy.java',source/'OriginalCombatRules.java'])
    prior = run([JDK/'javap.exe','-J-Dfile.encoding=UTF-8','-c','-p','-classpath',BASE_JAR,'com.codex.witchweapon.LocalEconomy'])
    revised = run([JDK/'javap.exe','-J-Dfile.encoding=UTF-8','-c','-p','-classpath',str(classes)+';'+str(BASE_JAR),'com.codex.witchweapon.LocalEconomy'])
    a,b = methods(prior),methods(revised)
    assert set(a)==set(b)
    changed = [name for name in a if a[name]!=b[name]]
    assert len(changed)==1 and changed[0].startswith('static byte[] combat('), changed
    fixture = OUT/'offline_responses.json'
    test = PROJECT/'legacy-server/tests/com/codex/witchweapon'
    run([JDK/'javac.exe','-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
         '-cp',str(classes)+';'+str(BASE_JAR)+';'+str(JSON_JAR),'-d',test_classes,
         test/'OriginalCombatRulesSelfTest.java', test/'CombatWeaponTypesSelfTest.java',
         test/'RestrictedCombatRoleSelfTest.java'])
    cp = ';'.join(map(str,(test_classes,classes,BASE_JAR,JSON_JAR)))
    csv_cases = cases()
    evidence = [run([JDK/'java.exe','-Dfile.encoding=UTF-8','-Xmx512m','-cp',cp,
                    'com.codex.witchweapon.OriginalCombatRulesSelfTest',fixture,csv_cases]).strip(),
                run([JDK/'java.exe','-Dfile.encoding=UTF-8','-Xmx512m','-cp',cp,
                    'com.codex.witchweapon.CombatWeaponTypesSelfTest',fixture]).strip()]
    save = TEMP/'guide-save';save.mkdir(exist_ok=True)
    assert list(save.iterdir())==[]
    evidence.append(run([JDK/'java.exe','-Dfile.encoding=UTF-8','-Xmx512m','-cp',cp,
        'com.codex.witchweapon.RestrictedCombatRoleSelfTest',save,fixture]).strip())
    candidate = OUT/'witchweapon-legacy.jar'
    replacements = {'com/codex/witchweapon/LocalEconomy.class':(classes/'com/codex/witchweapon/LocalEconomy.class').read_bytes(),
                    'com/codex/witchweapon/OriginalCombatRules.class':(classes/'com/codex/witchweapon/OriginalCombatRules.class').read_bytes()}
    with zipfile.ZipFile(BASE_JAR) as old,zipfile.ZipFile(candidate,'w') as new:
        for entry in old.infolist():
            if entry.filename in replacements:new.writestr(copy.copy(entry),replacements[entry.filename])
            else:copy_compressed_entry(old,new,entry)
        for path in set(replacements)-set(old.namelist()):new.writestr(path,replacements[path])
    with zipfile.ZipFile(BASE_JAR) as old,zipfile.ZipFile(candidate) as new:
        assert set(new.namelist())-set(old.namelist())=={'com/codex/witchweapon/OriginalCombatRules.class'}
        assert {n for n in old.namelist() if old.read(n)!=new.read(n)}=={'com/codex/witchweapon/LocalEconomy.class'}
    report = dict(baseJarSha256=sha(BASE_JAR.read_bytes()), candidateJarSha256=sha(candidate.read_bytes()),
        classes=list(replacements), changedMethods=changed, unrelatedMethodsUnchanged=len(a)-len(changed),
        testResults=evidence, originalCsvCases=144, auditedWeaponEffectsCovered=95, deviceValidated=False)
    (OUT/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for row in evidence:print(row)
    print('COMBAT_MINIMAL_JAR_OK',report['candidateJarSha256'], 'unrelatedMethods', report['unrelatedMethodsUnchanged'])


if __name__=='__main__':main()
