"""Build only the verified kill counters over the pinned task-protocol server."""
import hashlib,json,subprocess,sys,zipfile
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT/'android-client'))
from build_task_system_v127_release import released_local_save
BASE=PROJECT/'服务端候选/任务系统完整修复-原生批领完整协议.jar'
EXPECTED='a0ba0f96a8e2455b86e6a1974bf7a6d07db7e10d496f1704b1d29099a1a3fff2'
OUT=PROJECT/'服务端候选/任务系统完整修复-击杀成就.jar'
TEMP=Path(r'D:\Environment\Java\temp\witch-task-kills')
JAVA=Path(r'D:\Environment\Java\jdk8\bin')
JSON=Path(r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar')
NAMES=('ProgressionTasks','LocalSave','DailyBattle','WeaponFurnace')

def main():
    assert hashlib.sha256(BASE.read_bytes()).hexdigest()==EXPECTED and not OUT.exists()
    classes=TEMP/'classes';classes.mkdir(parents=True,exist_ok=True)
    source=TEMP/'source';source.mkdir(exist_ok=True)
    sources=[PROJECT/'legacy-server/src/com/codex/witchweapon'/(n+'.java') for n in NAMES]
    stripped=source/'LocalSave.java'
    stripped.write_text(released_local_save(sources[1].read_text(encoding='utf-8')),encoding='utf-8')
    sources[1]=stripped
    subprocess.run([str(JAVA/'javac.exe'),'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',str(BASE)+';'+str(JSON),'-d',str(classes),*map(str,sources)],check=True)
    payload={}
    for f in classes.rglob('*.class'):
        name=f.relative_to(classes).as_posix()
        assert name.startswith('com/codex/witchweapon/') and name.rsplit('/',1)[1].split('$')[0].split('.')[0] in NAMES
        payload[name]=f.read_bytes()
    assert all('com/codex/witchweapon/'+n+'.class' in payload for n in NAMES)
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUT,'x') as new:
        new.comment=old.comment;original=set(old.namelist())
        for e in old.infolist():new.writestr(e,payload.get(e.filename,old.read(e.filename)))
        for name in sorted(payload.keys()-original):new.writestr(name,payload[name])
    with zipfile.ZipFile(BASE) as old,zipfile.ZipFile(OUT) as new:
        changed=[n for n in new.namelist() if n not in original or old.read(n)!=new.read(n)]
        assert set(changed)<=set(payload)
        for n in old.namelist():
            if not n.endswith('.class'):assert old.read(n)==new.read(n)
    tests=TEMP/'tests';tests.mkdir(exist_ok=True)
    test_names=['Daily','ProgressionTasks','MainStoryTasks','TaskRewards','TutorialTask','Guild','GuildDailyCurrency','StaminaPurchase','BattleKillAchievements']
    subprocess.run([str(JAVA/'javac.exe'),'-J-Dfile.encoding=UTF-8','-encoding','UTF-8','-source','8','-target','8',
        '-cp',str(OUT)+';'+str(JSON),'-d',str(tests),
        *[str(PROJECT/'legacy-server/tests/com/codex/witchweapon'/(n+'SelfTest.java')) for n in test_names]],check=True)
    cp=';'.join(map(str,[tests,OUT,JSON,PROJECT/'legacy-server/resources']))
    fixtures=PROJECT/'legacy-server/resources/offline_responses.json'
    testdir=TEMP/'saves';testdir.mkdir(exist_ok=True)
    for n in test_names:
        args=[]
        if n in ('ProgressionTasks','MainStoryTasks','TaskRewards'):args=[str(fixtures)]
        if n in ('Guild','TutorialTask','BattleKillAchievements'):
            folder=testdir/n;folder.mkdir()
            args=[str(folder)]
        if n=='TutorialTask':args=[str(fixtures),str(folder)]
        if n=='BattleKillAchievements':args+=[str(fixtures),str(PROJECT/'legacy-server/resources/stage_catalog.json')]
        subprocess.run([str(JAVA/'java.exe'),'-Dfile.encoding=UTF-8','-cp',cp,'com.codex.witchweapon.'+n+'SelfTest',*args],check=True)
    report=PROJECT/'验收/任务系统完整修复/发布.json';r=json.loads(report.read_text(encoding='utf-8'))
    r['killAchievements']={'jar':str(OUT),'baseSha256':EXPECTED,'sha256':hashlib.sha256(OUT.read_bytes()).hexdigest(),
        'changedClasses':changed,'tests':test_names,'status':'LOCAL_VALIDATED_CANDIDATE'}
    report.write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('TASK_KILL_COUNTERS_VALIDATED',r['killAchievements']['sha256'],flush=True)

if __name__=='__main__':main()
