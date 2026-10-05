"""Read SurfaceFlinger frame times and process memory without restarting the game."""
import argparse,json,re,shlex,statistics,subprocess,time
from pathlib import Path
PROJECT=Path(__file__).resolve().parents[1]
ADB=[r'D:\Environment\Android\platform-tools\adb.exe','-s','1008002699867175077363317']
PACKAGE='com.codex.witchweapon.online.originalui.test'
def read(command):
    return subprocess.check_output(ADB+['shell',command]).decode('utf-8','replace')
def measure():
    pid=read('pidof '+PACKAGE).strip();assert pid.isdigit(), 'Game is not running'
    layers=read('dumpsys SurfaceFlinger --list').splitlines()
    layer=next(x for x in layers if x.startswith('SurfaceView['+PACKAGE) and '(BLAST)' in x)
    raw=read('dumpsys SurfaceFlinger --latency '+shlex.quote(layer))
    rows=[list(map(int,s.split())) for s in raw.splitlines()[1:] if len(s.split())==3]
    ns=[x[1] for x in rows if 0<x[1]<9223372036854775807]
    ds=[(b-a)/1e6 for a,b in zip(ns,ns[1:]) if 0<b-a<1e9]
    uptime=float(read('cat /proc/uptime').split()[0])
    age=uptime-ns[-1]/1e9 if ns else None
    fresh=age is not None and -.5 <= age < 2
    mem=read('dumpsys meminfo '+PACKAGE)
    top=read('top -H -b -n 1 -p '+pid)
    cpu_line=next((x for x in top.splitlines() if 'UnityMain' in x and x.split()[0].isdigit()),'')
    cpu=cpu_line.split()[8] if cpu_line else None
    temperature=re.search(r'temperature:\s*(\d+)',read('dumpsys battery'))
    pss=re.search(r'TOTAL PSS:\s*(\d+)',mem)
    return {'timestamp':time.time(),'pid':pid,'frames':len(ns),'lastFrameAgeSeconds':age,
        'currentFramesValid':fresh,
        'averageFPS':1000/statistics.mean(ds) if ds and fresh else None,
        'frameMsP50':statistics.median(ds) if ds and fresh else None,
        'frameMsP95':sorted(ds)[int(.95*(len(ds)-1))] if ds and fresh else None,
        'over50ms':sum(x>50 for x in ds),'unityMainCPU':cpu,
        'pssMB':int(pss[1])/1024 if pss else None,
        'batteryTemperatureC':int(temperature[1])/10 if temperature else None}
def main():
    parser=argparse.ArgumentParser();parser.add_argument('label');parser.add_argument('--samples',type=int,default=3)
    args=parser.parse_args();metrics=[]
    for i in range(args.samples):
        metrics.append(measure())
        if i+1<args.samples:time.sleep(3)
    folder=PROJECT/'验收/运行性能';folder.mkdir(exist_ok=True)
    (folder/(args.label+'.json')).write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
