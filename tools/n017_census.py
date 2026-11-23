import re
lines = open('~/dth30-re/disasm/firmware.asm').read().splitlines()
# routine range VA 0xa01be144..0xa01c19e4
def va_of(line):
    m = re.match(r'0x([0-9a-f]+):', line)
    return int(m.group(1),16) if m else None
start, end = 0xa01be144, 0xa01c19e8
inrange=False; offs={}; fp_uses=[]; s2store=[]; calls={}
for ln in lines:
    va = va_of(ln)
    if va is None: continue
    if va==start: inrange=True
    if va>=end: inrange=False
    if not inrange: continue
    # $s2-relative accesses
    for m in re.finditer(r'(lw|sw|lh|sh|lb|sb|lbu|lhu|ll|sc)\s+\$\w+,\s*(-?0x[0-9a-f]+|-?\d+)\(\$s2\)', ln):
        off = int(m.group(2),16) if 'x' in m.group(2) else int(m.group(2))
        offs.setdefault(off, []).append((m.group(1), hex(va)))
    if '$fp' in ln and ('($fp)' in ln or ', $fp' in ln or '$fp,' in ln):
        fp_uses.append(ln.strip())
    m = re.search(r'jal\s+(0x[0-9a-f]+)', ln)
    if m: calls[m.group(1)] = calls.get(m.group(1),0)+1
print("== distinct $s2 offsets (obj-relative), sorted ==")
for off in sorted(offs):
    kinds = {}
    for k,_ in offs[off]: kinds[k]=kinds.get(k,0)+1
    print(f"  +0x{off:04x}: {sum(kinds.values())} accesses {kinds}")
print(f"\ntotal distinct offsets: {len(offs)}")
print("\n== offsets in band-tail range 0xe00..0x1008 ==")
for off in sorted(offs):
    if 0xe00 <= off <= 0x1008: print(f"  +0x{off:04x}: {offs[off]}")
print("\n== $fp uses (first 20) ==")
for u in fp_uses[:20]: print("  ", u)
print(f"  total $fp-mention lines: {len(fp_uses)}")
print("\n== jal targets (top) ==")
for t,c in sorted(calls.items(), key=lambda kv:-kv[1])[:15]: print(f"  {t}: {c}")
