"""Compile only the maze repair against signed157, retaining unpublished source work."""
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

PROJECT = Path(r"D:\Project\魔女兵器在线版")
AREA = PROJECT / "验收/迷宫修复"
BASELINE = PROJECT / "验收/战斗全面核查/候选/witchweapon-legacy.jar"
JSON_JAR = Path(r"D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar")
JAVA = Path(r"D:\Environment\Java\jdk8\bin")

def strip_unpublished(source):
    changes = [
        ('        // A late unsettled CSC request must not close or reward a newly\n'
         '        // entered stone slate. Already committed CSC retries above are read-only.\n'
         '        if(state.optBoolean("active",false) &&\n'
         '            StoneSlateBattle.contains(state.optLong("activeStage",0)))\n'
         '            throw new IOException("Maze settlement superseded by stone slate");\n', ''),
        ('        if(path.equals("/challenge/combat/victory") || path.equals("/challenge/combat/cancel")){\n'
         '            StoneSlateBattle.Settlement settlement=StoneSlateBattle.bundled().settle(state,args,now,\n'
         '                path.equals("/challenge/combat/cancel"));\n'
         '            if(settlement.next!=null)commit(settlement.next);\n'
         '            return settlement.response;\n        }\n', ''),
        ('            if(path.equals("/challenge/combat/role/info") &&\n'
         '                StoneSlateBattle.contains(state.optLong("activeStage",0)))\n'
         '                return StoneSlateBattle.bundled().role(state,args,seed,catalog);\n', ''),
        ('            r.set(117,r.number(117,0)|StoneSlateBattle.challengeBits(state));\n', ''),
        ('                return StoneSlateBattle.bundled().progress(progress,state);', '                return progress;'),
        ('            if(StoneSlateBattle.contains(stage)){\n'
         '                JSONObject next=StoneSlateBattle.bundled().begin(state,stage,args,now);\n'
         '                if(next!=state)commit(next);\n'
         '                return seed;\n            }\n', ''),
    ]
    assert source.count('StoneSlateBattle') == 9
    for before, after in changes:
        assert source.count(before) == 1, before
        source = source.replace(before, after)
    assert 'StoneSlateBattle' not in source
    return source

def digest(value):
    return hashlib.sha256(value).hexdigest()

def main():
    source_root = PROJECT / "legacy-server/src/com/codex/witchweapon"
    staging = AREA / "候选源码/com/codex/witchweapon"
    staging.mkdir(parents=True, exist_ok=True)
    classes = AREA / "候选类"
    classes.mkdir(parents=True, exist_ok=True)
    for name in ('LocalSave', 'BarrierLabyrinth', 'StandaloneServer', 'MazeRules'):
        source = (source_root / f'{name}.java').read_text(encoding='utf-8')
        if name == 'LocalSave':
            source = strip_unpublished(source)
        (staging / f'{name}.java').write_text(source, encoding='utf-8')
    command = [str(JAVA / 'javac.exe'), '-encoding', 'UTF-8', '-source', '8', '-target', '8', '-cp', f'{BASELINE};{JSON_JAR}', '-d', str(classes)]
    subprocess.run(command + [str(p) for p in staging.glob('*.java')], check=True)
    changed = {str(p.relative_to(classes)).replace('\\', '/'): p.read_bytes() for p in classes.rglob('*.class')}
    resource = PROJECT / 'legacy-server/resources/maze_rules.json'
    changed['maze_rules.json'] = resource.read_bytes()
    candidate = AREA / 'witchweapon-maze-candidate.jar'
    with zipfile.ZipFile(BASELINE) as src, zipfile.ZipFile(candidate, 'w') as dst:
        for entry in src.infolist():
            dst.writestr(entry, changed.pop(entry.filename, src.read(entry)))
        for name, contents in changed.items():
            dst.writestr(name, contents, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(BASELINE) as old, zipfile.ZipFile(candidate) as new:
        differences = [name for name in new.namelist() if name not in old.namelist() or old.read(name) != new.read(name)]
        allowed = ('com/codex/witchweapon/BarrierLabyrinth', 'com/codex/witchweapon/LocalSave', 'com/codex/witchweapon/StandaloneServer', 'com/codex/witchweapon/MazeRules')
        assert all(name == 'maze_rules.json' or name.endswith('.class') and name.startswith(allowed) for name in differences)
        assert 'com/codex/witchweapon/StoneSlateBattle.class' not in new.namelist()
        assert old.read('com/codex/witchweapon/LocalEconomy.class') == new.read('com/codex/witchweapon/LocalEconomy.class')
        assert old.read('preserved_battle_catalog.json') == new.read('preserved_battle_catalog.json')
    report = {'baseline': str(BASELINE), 'baselineSha256': digest(BASELINE.read_bytes()), 'candidate': str(candidate), 'candidateSha256': digest(candidate.read_bytes()), 'changedMembers': differences, 'unpublishedStoneSlateReferencesExcluded': 9, 'sourceLeftIntact': True}
    (AREA / '候选成员核对.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))

if __name__ == '__main__':
    main()
