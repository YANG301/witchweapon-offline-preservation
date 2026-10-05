"""Patch only task progress readers in the pinned live JAR and verify rewards."""
from pathlib import Path
import hashlib
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'build/witchweapon-legacy.jar'
OUTPUT = ROOT / 'build/witchweapon-legacy-task-progress.jar'
BASE_SHA = 'a460c6758db0f1d6c142cbfb8d7bfd49e06902dcebb69fa6bbb33a94db6d40d6'
TEMP = Path(r'D:\Environment\Java\temp\witch-task-progress')
JAVA = Path(r'D:\Environment\Java\jdk8\bin\java.exe')
JAVAC = JAVA.with_name('javac.exe')
JSON_JAR = Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
PACKAGE = 'com/codex/witchweapon/'
NAMES = ('MainStoryTasks', 'ProgressionTasks', 'TaskStageProgress')
ENV = dict(os.environ, TEMP=str(TEMP), TMP=str(TEMP))

def run(args, expect_success=True):
    result = subprocess.run([str(a) for a in args], env=ENV, capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    if expect_success and result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result

def compile_to(folder, sources, classpath):
    folder.mkdir()
    run([JAVAC, '-J-Dfile.encoding=UTF-8', '-encoding', 'UTF-8', '-source', '8',
         '-target', '8', '-cp', classpath, '-d', folder, *sources])

def main():
    if hashlib.sha256(BASE.read_bytes()).hexdigest() != BASE_SHA:
        raise ValueError('Live baseline JAR changed')
    if OUTPUT.exists() or TEMP.exists():
        raise FileExistsError('Candidate or bounded build temporary directory already exists')
    TEMP.mkdir()
    tests = [ROOT / ('tests/' + PACKAGE + n + 'SelfTest.java')
             for n in ('MainStoryTasks', 'ProgressionTasks')]
    helper = ROOT / ('src/' + PACKAGE + 'TaskStageProgress.java')
    old_classes = TEMP / 'baseline-test-classes'
    compile_to(old_classes, [helper, tests[0]], os.pathsep.join(map(str, (BASE, JSON_JAR))))
    fixture = ROOT / 'resources/offline_responses.json'
    old = run([JAVA, '-Dfile.encoding=UTF-8', '-cp',
               os.pathsep.join(map(str, (old_classes, BASE, JSON_JAR))),
               'com.codex.witchweapon.MainStoryTasksSelfTest', fixture], False)
    if old.returncode == 0 or 'Existing daily/furnace clear must immediately complete' not in old.stderr:
        raise AssertionError('Regression does not reproduce on the live baseline')
    print('BASELINE_REPRODUCED: existing daily/furnace wins are omitted', flush=True)
    classes = TEMP / 'candidate-test-classes'
    sources = [ROOT / ('src/' + PACKAGE + n + '.java') for n in NAMES]
    compile_to(classes, [*sources, *tests], os.pathsep.join(map(str, (BASE, JSON_JAR))))
    for name in ('MainStoryTasks', 'ProgressionTasks'):
        result = run([JAVA, '-Dfile.encoding=UTF-8', '-cp',
                      os.pathsep.join(map(str, (classes, BASE, JSON_JAR))),
                      'com.codex.witchweapon.' + name + 'SelfTest', fixture])
        print(result.stdout.strip(), flush=True)
    changed = {PACKAGE + n + '.class': (classes / (PACKAGE + n + '.class')).read_bytes()
               for n in NAMES}
    with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(OUTPUT, 'x') as new:
        for entry in old.infolist():
            new.writestr(entry, changed.pop(entry.filename, old.read(entry)))
        for name, data in changed.items():
            new.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(BASE) as old, zipfile.ZipFile(OUTPUT) as new:
        expected = {PACKAGE + n + '.class' for n in NAMES}
        actual = {name for name in new.namelist()
                  if name not in old.namelist() or new.read(name) != old.read(name)}
        assert actual == expected and not (set(old.namelist()) - set(new.namelist()))
        assert len(new.namelist()) == len(set(new.namelist()))
    print('TASK_PROGRESS_JAR_VERIFIED', hashlib.sha256(OUTPUT.read_bytes()).hexdigest(), flush=True)

if __name__ == '__main__':
    main()
