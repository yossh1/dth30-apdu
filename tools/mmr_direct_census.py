import re, collections
lines=open("~/dth30-re/disasm/firmware.asm", errors='ignore').read().splitlines()
pat=re.compile(r'^(0x[0-9a-f]+):\s+([0-9a-f]+)\s+(.*)$')
ins=[]
for ln in lines:
    m=pat.match(ln)
    if m: ins.append((int(m.group(1),16), m.group(3).strip()))
# track registers loaded from -0x6b94($gp)  (MMR base) ; gp value in capstone text: "lw $v1, -0x6b94($gp)"
base_load=re.compile(r'lw\s+(\$\w+),\s*-0x6b94\(\$gp\)')
acc=re.compile(r'(lw|sw|lhu|shu|lb|lbu|sb)\s+(?:\$\w+,\s*)?(-?0x[0-9a-f]+|-?\d+)\((\$\w+)\)')
hits=collections.defaultdict(list)
for i,(va,txt) in enumerate(ins):
    m=base_load.match(txt)
    if not m: continue
    reg=m.group(1)
    # scan forward until reg reassigned or 300 insns
    for j in range(i+1, min(len(ins), i+300)):
        t=ins[j][1]
        if re.match(r'(?:lui|move|addu|addiu|subu)\s+'+re.escape(reg)+r'\b', t) and '($gp)' not in t:
            # reassignment (except lw from gp reload)
            if not base_load.match(t): break
        mm=acc.match(t)
        if mm and mm.group(3)==reg:
            try: off=int(mm.group(2),0)
            except: continue
            hits[off].append(ins[j][0])
print("distinct direct MMR offsets:", len(hits))
for off in sorted(hits):
    print(f"0x{off:04x} n={len(hits[off])} sites={[hex(s) for s in hits[off][:5]]}")
