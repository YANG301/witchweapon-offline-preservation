"""Restore the original GetMaxNumber entry when preparing a full APK."""
from pathlib import Path
import struct

RVA=0x1483228
OFFLINE=bytes.fromhex('21 00 80 52 01 A4 02 B9 C0 03 5F D6')
ORIGINAL=bytes.fromhex('EB 2B BA 6D E9 23 01 6D F8 5F 02 A9')

def patch(raw):
    if raw[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected arm64 little-endian ELF')
    offset=struct.unpack_from('<Q',raw,32)[0]
    size,count=struct.unpack_from('<HH',raw,54)
    found=[]
    for i in range(count):
        kind,flags,start,address,_,length,_,_=struct.unpack_from('<IIQQQQQQ',raw,offset+i*size)
        if kind==1 and flags&1 and address<=RVA and RVA+12<=address+length:
            found.append(start+RVA-address)
    if len(found)!=1:raise ValueError('Original GetMaxNumber code segment absent or ambiguous')
    start=found[0]
    before=raw[start:start+12]
    if before==ORIGINAL:return raw
    if before!=OFFLINE:raise ValueError('Unreviewed GetMaxNumber native entry')
    result=raw[:start]+ORIGINAL+raw[start+12:]
    assert len(result)==len(raw) and result[:start]==raw[:start] and result[start+12:]==raw[start+12:]
    return result
