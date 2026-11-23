import struct
data = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
def scan(lo,hi,label):
    hits=[]
    for off in range(0, len(data)-3, 4):
        w = struct.unpack_from('<I', data, off)[0]
        if lo <= w < hi: hits.append((off,w))
    print(f"{label}: {len(hits)} hits")
    for off,w in hits[:60]: print(f"   fileoff 0x{off:06x} -> 0x{w:08x}")
scan(0x801be140, 0x801c19e8, "KSEG0-form ptrs into routine")
scan(0x000be140, 0x000c19e8, "phys-form ptrs into routine")
scan(0xa01be140, 0xa01c19e8, "KSEG1-form ptrs into routine")
# exact entry in phys/KSEG0 forms
for val in (0x000be140, 0x801be140):
    pat=struct.pack('<I',val); hits=[]; i=0
    while True:
        j=data.find(pat,i)
        if j<0: break
        hits.append(j); i=j+1
    print(f"exact 0x{val:08x}: {[hex(h) for h in hits]}")
