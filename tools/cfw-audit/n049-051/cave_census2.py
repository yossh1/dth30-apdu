import re, struct
data=open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
N=len(data)
cands=[(0x1e238,0x19c4),(0x1dc5f,0x48b),(0x1fd10,0x401),(0xcb18,0x110e8)]
def in_cand(foff):
    for s,l in cands:
        if s<=foff<s+l: return (s,l)
    return None
hits={c[0]:[] for c in cands}
for i in range(0,N-3,4):
    w=struct.unpack_from('<I',data,i)[0]
    for base in (0x80100000,0xa0100000):
        if base<=w<base+N:
            c=in_cand(w-base)
            if c: hits[c[0]].append(('ptr',hex(i),hex(w)))
            break
pat=re.compile(r'^0x([0-9a-f]+): [0-9a-f]+  (.*)$')
lines=[]
with open('~/dth30-re/disasm/firmware.asm') as f:
    for line in f:
        m=pat.match(line)
        if m: lines.append((int(m.group(1),16), m.group(2).strip()))
reg_hi={}
for va,ins in lines:
    m=re.match(r'(jal|j|bal)\s+0x([0-9a-f]+)',ins)
    if m:
        t=int(m.group(2),16)
        for base in (0xa0100000,0x80100000):
            cc=in_cand(t-base)
            if cc: hits[cc[0]].append(('jump',hex(va),hex(t)))
    m=re.match(r'lui\s+\$(\w+), 0x([0-9a-f]+)',ins)
    if m: reg_hi[m.group(1)]=(int(m.group(2),16)<<16, va); continue
    m=re.match(r'addiu\s+\$(\w+), \$(\w+), (-?0x[0-9a-f]+|-?\d+)',ins)
    if m and m.group(2) in reg_hi and m.group(1)==m.group(2):
        hi,hva=reg_hi[m.group(2)]
        if va-hva<=0x40:
            addr=(hi+int(m.group(3),0))&0xffffffff
            for base in (0xa0100000,0x80100000):
                cc=in_cand(addr-base)
                if cc: hits[cc[0]].append(('lui/addiu',hex(hva),hex(addr)))
for s,l in cands:
    print(f'cave file {s:#x} len {l:#x}: refs={len(hits[s])}')
    for h in hits[s][:12]: print('   ',h)
