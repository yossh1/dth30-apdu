import re
lines = open('~/dth30-re/disasm/firmware.asm').read().splitlines()
def va_of(line):
    m = re.match(r'0x([0-9a-f]+):', line)
    return int(m.group(1),16) if m else None
def offval(s):
    return int(s,16) if 'x' in s else int(s)

# obj offset set: all $s2-relative accesses in routine 0xa01be144..0xa01c19e8 (same method as n017_census.py)
obj_offs=set()
inr=False
for ln in lines:
    va=va_of(ln)
    if va is None: continue
    if va==0xa01be144: inr=True
    if va>=0xa01c19e8: inr=False
    if not inr: continue
    for m in re.finditer(r'(lw|sw|lh|sh|lb|sb|lbu|lhu|ll|sc)\s+\$\w+,\s*(-?0x[0-9a-f]+|-?\d+)\(\$s2\)', ln):
        obj_offs.add(offval(m.group(2)))
print(f"obj offset set size: {len(obj_offs)}")

# H-025 target function 0xa0164448: extent = to last jr $ra before next prologue.
# Observed jr $ra at 0xa01646bc/4708/4734/4788/47a0; take extent 0xa0164448..0xa01647a8.
start,end=0xa0164448,0xa01647a8
stores=[]
inr=False
for ln in lines:
    va=va_of(ln)
    if va is None: continue
    if va==start: inr=True
    if va>=end: inr=False
    if not inr: continue
    m=re.search(r'(sw|sh|sb|sc)\s+(\$\w+),\s*(-?0x[0-9a-f]+|-?\d+)\((\$\w+)\)', ln)
    if m:
        stores.append((va,m.group(1),m.group(2),offval(m.group(3)),m.group(4)))
print(f"\nfunction 0xa0164448 extent {start:#x}..{end:#x}: {len(stores)} stores total")
byoff={}
for va,op,reg,off,base in stores:
    byoff.setdefault(off,[]).append((va,op,reg,base))
print("\n== store offsets (all bases) ==")
for off in sorted(byoff):
    flag = "  <-- IN OBJ OFFSET SET" if off in obj_offs else ""
    print(f"  +0x{off:04x}: {len(byoff[off])} stores {byoff[off][:4]}{flag}")
hits=[o for o in byoff if o in obj_offs]
print(f"\nstores to obj-set offsets: {hits if hits else 'NONE'}")
