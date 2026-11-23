import struct
data=open("~/dth30-re/xcode2emb_embedded.bin",'rb').read()
def find_word(v):
    pat=struct.pack('<I', v); out=[]; i=0
    while True:
        j=data.find(pat,i)
        if j<0: break
        out.append(j); i=j+1
    return out
strs={
 "InitCableCard":0xFF030, "CP_APDU_Length":0x1022D8, "CalcDesKeyAB":0x102F89,
 "CP_task_init":0x10244C, "AuthCableCARD":0x1029F0, "send_id_to_host":0x102294,
 "ReinitTSD":0xFF024, "TSD_FPGA":0xFF1DC, "NoCableCard":0xFF0D0,
}
for name,foff in strs.items():
    for base,label in [(0x80100000,"KSEG0"),(0xA0100000,"KSEG1")]:
        v=base+foff
        hits=find_word(v)
        if hits: print(name,label,hex(v),[hex(h) for h in hits])
    # lui/addiu pattern: search asm
print("done word scan")
# lui scan in asm text for high halves
import re
asm=open("~/dth30-re/disasm/firmware.asm", errors='ignore').read()
for name,foff in strs.items():
    va=0xA0100000+foff
    hi=(va>>16)&0xFFFF; lo=va&0xFFFF
    # capstone prints lui $reg, 0x8020 etc and addiu with signed lo
    print(name, "VA", hex(va), "hi", hex(hi), "lo", hex(lo))
