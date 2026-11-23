#!/usr/bin/env python3
# N-032 census: BufFsUSB.asm (objdump -d style, addresses = VA-0x400000+0x10000? raw file offsets as printed)
# The .asm uses addresses like "   1a0bc:" (image base 0x400000 removed? actually VA-0x3F0000 style used in prior notes: VA = printed + 0x3F0000? No:
# prior notes cite VA 0x1a0bc etc. directly as printed). We just work in printed address space.
import re, sys
from collections import defaultdict

PATH = "~/dth30-re/disasm/BufFsUSB.asm"
lines = []
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
for raw in open(PATH, encoding="utf-8", errors="replace"):
    m = insn_re.match(raw.rstrip("\n"))
    if m:
        addr = int(m.group(1), 16)
        lines.append((addr, m.group(3).strip()))
by_addr = {a: t for a, t in lines}
addrs = [a for a, _ in lines]
idx_of = {a: i for i, (a, _) in enumerate(lines)}

def func_start(addr):
    # walk back to previous int3 padding / ret boundary: use nearest preceding address whose insn is 'int3' run end
    i = idx_of[addr]
    j = i
    while j > 0:
        a, t = lines[j - 1]
        if t.startswith("int3") :
            return lines[j][0]
        j -= 1
    return lines[0][0]

out = []

# ---- [A] callers of send 0x1a0bc: scan backwards for immediate stores to +0x18 (req Func field) ----
out.append("== [A] call 0x1a0bc sites: backward scan (<=600 insns) for 'movl $imm,0x18(reg)' ==")
for a, t in lines:
    if t == "call   0x1a0bc":
        hits = []
        i = idx_of[a]
        for j in range(i - 1, max(0, i - 600), -1):
            aa, tt = lines[j]
            m = re.match(r'movl\s+\$(0x[0-9a-f]+|\d+),0x18\(%(\w+)\)', tt)
            if m:
                hits.append((aa, tt))
                break
            if tt.startswith("int3"):
                break
        out.append(f"  call@{a:#x} func~{func_start(a):#x} req+0x18 imm: {hits if hits else 'NONE in window'}")

# ---- [B] all immediate stores to +0x18 anywhere with small values (Func candidates) ----
out.append("")
out.append("== [B] all 'movl $imm,0x18(reg)' with imm<=0x20 ==")
for a, t in lines:
    m = re.match(r'movl\s+\$(0x[0-9a-f]+|\d+),0x18\(%(\w+)\)', t)
    if m:
        v = int(m.group(1), 0)
        if v <= 0x20:
            out.append(f"  {a:#x} func~{func_start(a):#x}: {t}")

# ---- [C] references to callback table base 0x16bade8 and nearby (table fill) ----
out.append("")
out.append("== [C] any instruction mentioning 0x16bade8 / 0x16bade* / 0x16bad* offsets ==")
for a, t in lines:
    if re.search(r'16bad[0-9a-f]{2}', t):
        out.append(f"  {a:#x} func~{func_start(a):#x}: {t}")

# ---- [D] stores to param offsets +0x58/+0x5c/+0x60 via computed pointer (movl $imm,0x7c/0x80/0x84 after +0x24 base) ----
# param area = slot+0x24, so param+0x58 = ptr+0x7c, param+0x5c = ptr+0x80, param+0x60 = ptr+0x84 when base is host param ptr.
out.append("")
out.append("== [D] immediate stores to +0x7c/+0x80/+0x84 (param+0x58/+0x5c/+0x60 if base=param ptr) ==")
for a, t in lines:
    m = re.match(r'movl\s+\$(0x[0-9a-f]+|\d+),(0x7c|0x80|0x84)\(%(\w+)\)', t)
    if m:
        out.append(f"  {a:#x} func~{func_start(a):#x}: {t}")

# ---- [E] callers of alloc 0x18654 grouped by function ----
out.append("")
out.append("== [E] call 0x18654 sites grouped by containing function ==")
grp = defaultdict(list)
for a, t in lines:
    if t == "call   0x18654":
        grp[func_start(a)].append(a)
for f in sorted(grp):
    out.append(f"  func~{f:#x}: calls at {[hex(x) for x in grp[f]]}")

# ---- [F] callers of send 0x1a0bc grouped by function ----
out.append("")
out.append("== [F] call 0x1a0bc sites grouped by containing function ==")
grp = defaultdict(list)
for a, t in lines:
    if t == "call   0x1a0bc":
        grp[func_start(a)].append(a)
for f in sorted(grp):
    out.append(f"  func~{f:#x}: calls at {[hex(x) for x in grp[f]]}")

print("\n".join(out))
