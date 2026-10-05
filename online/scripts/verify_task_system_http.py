"""Exercise native task and achievement endpoints on an isolated loopback host."""
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import urllib.parse

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'验收/任务系统完整修复/接口测试'
JAVA=Path(r'D:\Environment\Java\jdk8\bin\java.exe')
SECRET='isolated-task-protocol-check-no-production-access'
ACCOUNT='TaskProtocolTest000001'

def fields(raw):
    def var(i):
        n,shift=0,0
        while True:
            b=raw[i];i+=1;n|=(b&127)<<shift
            if b<128:return n,i
            shift+=7
    out=[];i=0
    while i<len(raw):
        tag,i=var(i);kind=tag&7
        if kind==0:v,i=var(i)
        elif kind==2:
            size,i=var(i);v=raw[i:i+size];i+=size
        else:raise AssertionError('Unexpected wire kind')
        out.append((tag>>3,v))
    return out

def jobs(raw):
    return {dict(fields(v))[1]:dict(fields(v)) for n,v in fields(raw) if n==1}

def call(path,**form):
    request=urllib.request.Request('http://127.0.0.1:19879'+path,
        data=urllib.parse.urlencode(form).encode(),
        headers={'X-WW-Proxy-Secret':SECRET,'X-WW-Account-ID':ACCOUNT,
                 'Content-Type':'application/x-www-form-urlencoded'})
    return urllib.request.urlopen(request,timeout=8).read()

def main():
    save=ROOT/'users'/ACCOUNT/'offline_save_v1.json'
    if save.exists():
        prior=json.loads(save.read_text(encoding='utf-8'))
        assert prior['name']=='ProtocolTest' and prior['legacyRoleId']==7
    save.parent.mkdir(parents=True,exist_ok=True)
    state=dict(version=1,saveRevision=1,roleCreated=True,name='ProtocolTest',
        legacyRoleId=7,starterProfile=1,cosmeticProfile=1,exp=119105,gold=10000,
        rmb=1000,ownedServants={},mainlineStages={'3110001001':{'wins':1}},
        dailyTasks={'day':(__import__('time').time_ns()//10**9+28800)//86400,
                    'progress':{'502031001':1},'claimed':{}})
    save.write_text(json.dumps(state),encoding='utf-8')
    environment=os.environ.copy();environment['WW_LEGACY_PROXY_SECRET']=SECRET
    cp=str(PROJECT/'服务端候选/任务系统完整修复-原生批领完整协议.jar')+';'+r'D:\Environment\Java\libraries\android-json-9.0.0_r61\android-json.jar'
    server=subprocess.Popen([str(JAVA),'-Dfile.encoding=UTF-8','-cp',cp,
        'com.codex.witchweapon.StandaloneServer','--port','19879','--data-dir',str(ROOT),
        '--responses',str(PROJECT/'legacy-server/resources/offline_responses.json')],
        env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        ready=server.stdout.readline().decode('utf-8');assert ready.startswith('READY'),ready
        tasks=call('/task/all',roleid=7)
        meta={dict(fields(v))[3]:dict(fields(v)) for n,v in fields(tasks) if n==2}
        daily=[i for i,m in meta.items() if m[1]==2]
        story=[i for i,m in meta.items() if m[1]==6]
        assert len(daily)==15 and len(story)==106,(len(daily),len(story))
        for ids in ([502031001],[i for i in story if jobs(tasks)[i][2]==0]):
            assert ids
            args=dict(roleid=7,jobids='|'.join(map(str,ids)),
                      typeids='|'.join(str(int(meta[i][2])) for i in ids))
            first=call('/task/updatemore',**args)
            after=json.loads(save.read_text(encoding='utf-8'))
            assert len(fields(first))>0
            retry=call('/task/updatemore',**args)
            retried=json.loads(save.read_text(encoding='utf-8'))
            assert retry==first and after==retried
            listed=jobs(call('/task/all',roleid=7))
            assert all(listed[i][2]==1 for i in ids)
        achievements=call('/achievement/all',roleid=7)
        assert len(jobs(achievements))==50
        ready=[i for i,row in jobs(achievements).items() if row[2]==0]
        assert ready
        metas={dict(fields(v))[3]:dict(fields(v)) for n,v in fields(achievements) if n==2}
        ident=ready[0]
        reward=call('/achievement/update',roleid=7,jobid=ident,type=metas[ident][2].decode())
        assert fields(reward)
        assert jobs(call('/achievement/all',roleid=7))[ident][2]==1
        print('TASK_HTTP_OK daily=15 story=106 achievements=50 batch-replay=exact achievement-claim=ok',flush=True)
    finally:
        server.terminate();server.wait(timeout=10)
        errors=server.stderr.read().decode('utf-8')
        if errors:print(errors)

if __name__=='__main__':main()
