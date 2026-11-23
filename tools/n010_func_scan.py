#!/usr/bin/env python3
# N-010: split BufFsUSB.asm into functions (int3 padding boundaries) and report
# functions that STORE to offset +0x11C, together with the other large offsets
# they touch, to identify which object type each +0x11C store belongs to.
import re

ASM = "~/dth30-re/disasm/BufFsUSB.asm"
lines = open(ASM, errors="replace").read().splitlines()

insn_re = re.compile(r"^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+|[0-9a-f]+)\s*\t(.*)$")
funcs = []
cur = []
for ln in lines:
    m = insn_re.match(ln)
    if not m:
        continue
    va = int(m.group(1), 16)
    txt = m.group(3).strip()
    if txt == "int3":
        if cur:
            funcs.append(cur)
            cur = []
        continue
    cur.append((va, txt))
if cur:
    funcs.append(cur)

print(f"total pseudo-functions: {len(funcs)}")

off_re = re.compile(r"0x([0-9a-f]+)\(%")
store11c_re = re.compile(r"^(mov|and|or|add|sub)\s+.*,\s*(?:dword ptr )?0x11c\(%")
for f in funcs:
    stores = [(va, t) for va, t in f if store11c_re.match(t) and "0x11c(" in t]
    if not stores:
        continue
    offs = set()
    for va, t in f:
        for om in off_re.finditer(t):
            v = int(om.group(1), 16)
            if v >= 0x100:
                offs.add(v)
    big = sorted(o for o in offs if o >= 0x10000)
    start = f[0][0]
    print(f"\nFUNC @{start:#x} len={len(f)} stores_to_11c={len(stores)}")
    for va, t in stores:
        print(f"   store @{va:#x}: {t}")
    if big:
        print(f"   big offsets touched: {[hex(o) for o in big]}")
