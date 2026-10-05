"""Navigate the known task tabs without claiming rewards or changing a save."""
import argparse,json,subprocess,time
from pathlib import Path
from measure_android_runtime import ADB,PROJECT,measure,read

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--cycles',type=int,default=6)
    parser.add_argument('--delay',type=float,default=2)
    parser.add_argument('--start-in-hall',action='store_true')
    args=parser.parse_args()
    assert 0.5<=args.delay<=10 and 1<=args.cycles<=50
    result={'delaySeconds':args.delay,'cycles':[]}
    folder=PROJECT/'验收/运行性能'
    # The caller confirms the first task page visually before this navigation.
    if not args.start_in_hall:
        read('input tap 121 70');time.sleep(2)
    for cycle in range(args.cycles):
        for x,y in ((1741,921),(1769,477),(1769,651),(1769,305),(121,70)):
            read(f'input tap {x} {y}');time.sleep(args.delay)
        metric=measure();metric['cycle']=cycle+1
        result['cycles'].append(metric)
        print(json.dumps(metric,ensure_ascii=False),flush=True)
        if not metric['currentFramesValid']:
            result['stoppedBecause']='No newly presented frame; old frame times are invalid'
            break
    (folder/(args.label+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (folder/'当前.png').write_bytes(subprocess.check_output(ADB+['exec-out','screencap','-p']))

if __name__=='__main__':main()
