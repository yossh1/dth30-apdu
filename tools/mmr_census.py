import re, collections
lines=open("~/dth30-re/disasm/firmware.asm", errors='ignore').read().splitlines()
pat=re.compile(r'^(0x[0-9a-f]+):\s+([0-9a-f]+)\s+(.*)$')
ins=[]
for ln in lines:
    m=pat.match(ln)
    if m: ins.append((int(m.group(1),16), m.group(3).strip()))
# find jal to read_mmr 0xa01dde30, look back up to 8 insns for $a0 immediate set
census=collections.Counter(); sites={}
for i,(va,txt) in enumerate(ins):
    if 'jal 0xa01dde30' in txt:
        off=None
        for j in range(i-1, max(0,i-10), -1):
            t=ins[j][1]
            m=re.match(r'(?:addiu|ori)\s+\$a0,\s*\$zero,\s*(-?0x[0-9a-f]+|-?\d+)', t)
            if m: off=int(m.group(1),0) & 0xFFFFFFFF; break
            m=re.match(r'lui\s+\$a0,\s*(-?0x[0-9a-f]+|-?\d+)', t)
            if m: off=(int(m.group(1),0)&0xFFFF)<<16; break
            if re.match(r'(?:addiu|ori|move|addu)\s+\$a0,', t): break
        if off is not None:
            census[off]+=1; sites.setdefault(off,[]).append(va)
        else:
            census[-1]+=1
print("read_mmr distinct offsets:", len([k for k in census if k>=0]))
for off in sorted(k for k in census if k>=0):
    print(f"0x{off:04x} count={census[off]} sites={[hex(s) for s in sites[off][:4]]}")
print("unknown-arg calls:", census[-1])
# range histogram
ranges=collections.Counter()
for off,c in census.items():
    if off>=0: ranges[off>>12]+=c
print("\nrange histogram (offset>>12 : calls):")
for r in sorted(ranges): print(f"0x{r<<12:05x}-0x{(r<<12)+0xfff:05x}: {ranges[r]}")
