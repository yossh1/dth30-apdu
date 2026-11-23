import re
lines = open('~/dth30-re/disasm/firmware.asm').read().splitlines()
def va_of(line):
    m = re.match(r'0x([0-9a-f]+):', line)
    return int(m.group(1),16) if m else None

# split into crude functions: start at addiu $sp,$sp,-N that follows a jr $ra (or file start)
funcs = []  # (start_va, [lines])
cur = None
prev_jr = True
for ln in lines:
    va = va_of(ln)
    if va is None: continue
    if prev_jr and re.search(r'addiu \$sp, \$sp, -', ln):
        cur = (va, [])
        funcs.append(cur)
        prev_jr = False
    if cur is not None:
        cur[1].append(ln)
    if 'jr $ra' in ln:
        prev_jr = True

print(f"total crude functions: {len(funcs)}")
print("\n== functions that load a pointer via +0x318 and store to +0xb8/+0xbc through the same register ==")
for start, fl in funcs:
    ld = {}
    hits = []
    for ln in fl:
        m = re.search(r'lw (\$\w+), 0x318\(\$\w+\)', ln)
        if m: ld[m.group(1)] = va_of(ln)
        m = re.search(r'(sw|sh|sb) (\$\w+), (0xb8|0xbc)\((\$\w+)\)', ln)
        if m and m.group(4) in ld:
            hits.append(ln.strip())
    if hits:
        print(f"func @{start:#x}:")
        for h in hits: print("   ", h)

print("\n== all stores to +0xbc where base reg was loaded from +0x318 anywhere earlier in same function (loose) ==")
for start, fl in funcs:
    has318 = any('0x318(' in ln and 'lw' in ln for ln in fl)
    if not has318: continue
    sts = [ln.strip() for ln in fl if re.search(r'sw \$\w+, 0xbc\(\$\w+\)', ln)]
    if sts:
        print(f"func @{start:#x}: {sts}")
