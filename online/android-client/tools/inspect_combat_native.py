"""Read-only original combat instruction audit with named calls and SHA evidence."""
import argparse, hashlib, json, struct, sys, zipfile
from pathlib import Path
sys.path.insert(0, r'D:\Environment\UnityTools\python-libs')
from capstone import Cs, CS_ARCH_ARM64, CS_ARCH_ARM, CS_MODE_LITTLE_ENDIAN, CS_MODE_ARM

NATIVE=Path(r'D:\Project\魔女兵器工程恢复\原版\原生代码')

def main():
    p=argparse.ArgumentParser();p.add_argument('names',nargs='+');p.add_argument('--apk');p.add_argument('--out');args=p.parse_args()
    arch='armeabi-v7a' if args.apk else 'arm64'
    index=Path(r'D:\Project\魔女兵器在线版\联调记录\ARMv7登录研究\script.json') if args.apk else NATIVE/'类型与方法索引/script.json'
    methods=json.loads(index.read_text(encoding='utf-8-sig'))['ScriptMethod']
    names={m['Address']:m['Name'] for m in methods}
    addresses=sorted(set(names))
    if args.apk:
        with zipfile.ZipFile(args.apk) as z:raw=z.read('lib/'+arch+'/libil2cpp.so')
    else:raw=(NATIVE/'输入/arm64/libil2cpp.so').read_bytes()
    if arch=='arm64':
        fields=struct.unpack_from('<HHIQQQIHHHHHH',raw,16);phoff,entsize,count=fields[4],fields[8],fields[9]
        segments=[struct.unpack_from('<IIQQQQQQ',raw,phoff+i*entsize) for i in range(count)]
        segments=[(s[3],s[3]+s[5],s[2]) for s in segments if s[0]==1]
        cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    else:
        phoff=struct.unpack_from('<I',raw,28)[0];entsize,count=struct.unpack_from('<HH',raw,42)
        segments=[struct.unpack_from('<IIIIIIII',raw,phoff+i*entsize) for i in range(count)]
        segments=[(s[2],s[2]+s[4],s[1]) for s in segments if s[0]==1]
        cs=Cs(CS_ARCH_ARM,CS_MODE_ARM)
    lines=['lib sha256 '+hashlib.sha256(raw).hexdigest()]
    for name in args.names:
        matches=[m for m in methods if m['Name']==name]
        if len(matches)!=1:raise ValueError((name,len(matches)))
        start=matches[0]['Address'];end=next(a for a in addresses if a>start)
        lo,hi,offset=next(s for s in segments if s[0]<=start<s[1])
        block=raw[offset+start-lo:offset+end-lo]
        lines.append('\nMETHOD '+name+' '+hex(start)+' bytes '+str(len(block))+' sha256 '+hashlib.sha256(block).hexdigest())
        for ins in cs.disasm(block,start):
            label=''
            if ins.mnemonic in ('b','bl'):
                try:label=' ['+names[int(ins.op_str.lstrip('#'),16)]+']'
                except (ValueError,KeyError):pass
            lines.append(hex(ins.address)+' '+ins.mnemonic+' '+ins.op_str+label)
    output='\n'.join(lines)+'\n'
    if args.out:Path(args.out).write_bytes(output.encode('utf-8'))
    else:print(output)

if __name__=='__main__':main()
