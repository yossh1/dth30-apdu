import struct, sys
data = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
targets = {
 0xa01be140:'KSEG1 entry', 0x801be140:'KSEG0 entry',
 0xa01bede8:'KSEG1 idiom', 0x801bede8:'KSEG0 idiom',
}
for val,name in targets.items():
    pat = struct.pack('<I', val)
    hits=[]; i=0
    while True:
        j = data.find(pat, i)
        if j<0: break
        hits.append(j); i=j+1
    print(f"{name} 0x{val:08x}: {len(hits)} hits at fileoffs {[hex(h) for h in hits]}")
# also scan for any 32-bit word in range of the routine (potential interior pointers)
lo,hi = 0xa01be140, 0xa01c19e8
cnt=0; samples=[]
for off in range(0, len(data)-3, 4):
    w = struct.unpack_from('<I', data, off)[0]
    if lo <= w < hi:
        cnt+=1
        if len(samples)<40: samples.append((hex(off), hex(w)))
print(f"words pointing into routine range [{hex(lo)},{hex(hi)}): {cnt}")
for s in samples: print("  ", s)
