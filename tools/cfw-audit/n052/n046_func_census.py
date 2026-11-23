#!/usr/bin/env python3
# N-046 census: BufFsUSB.sys (objdump disasm) が発行する RPCI Func コードの全集合。
# 送信関数 0x1a0bc は [req+0x18] を slot+0xC と MMR 0x3020 の両方へ書く (実読済み)。
# よって発行 Func の全集合 = 全 call 0x1a0bc サイトで [handle+0x18] に入る値 + 特殊経路 (Func 0x1B)。
import re
from collections import defaultdict

PATH = "~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
lines = []
for raw in open(PATH, encoding="utf-8", errors="replace"):
    m = insn_re.match(raw.rstrip("\n"))
    if m:
        lines.append((int(m.group(1), 16), m.group(3).strip()))
idx_of = {a: i for i, (a, _) in enumerate(lines)}

def func_start(addr):
    i = idx_of[addr]; j = i
    while j > 0:
        if lines[j-1][1].startswith("int3"):
            return lines[j][0]
        j -= 1
    return lines[0][0]

out = []
# ---- [A] call 0x1a0bc sites: 直前の +0x18 ストアを解決 ----
out.append("== [A] call 0x1a0bc sites and resolved [handle+0x18] ==")
results = []
for a, t in lines:
    if t != "call   0x1a0bc":
        continue
    i = idx_of[a]; fs = func_start(a)
    store = None
    j = i - 1
    while j >= 0 and lines[j][0] >= fs:
        aa, tt = lines[j]
        m = re.match(r'movl?\s+\$(0x[0-9a-f]+|\d+),0x18\(%(\w+)\)', tt)
        if m:
            store = ('imm', int(m.group(1), 0), aa, tt); break
        m = re.match(r'mov\s+%(\w+),0x18\(%(\w+)\)', tt)
        if m:
            # レジスタ経由: そのレジスタの直前の即値ロードを探す
            reg = m.group(1); val = None; va = None
            for k in range(j-1, max(0, j-200), -1):
                ka, kt = lines[k]
                mm = re.match(r'mov\s+\$(0x[0-9a-f]+|\d+),%' + reg + r'\b', kt)
                if mm:
                    val = int(mm.group(1), 0); va = ka; break
                if re.match(r'(mov|lea)\s+.*,%' + reg + r'\b', kt) or kt.startswith('call'):
                    break
            store = ('reg', val, aa, tt + (f"  ; {reg}<=imm {val:#x} @{va:#x}" if val is not None else f"  ; {reg} unresolved"))
            break
        j -= 1
    results.append((a, fs, store))
    out.append(f"  call@{a:#x} func~{fs:#x}: {store}")

# ---- [B] 全 +0x18 即値ストア (<=0x20) の関数別一覧 (裏付け) ----
out.append("")
out.append("== [B] all immediate stores to +0x18 (imm<=0x20), by function ==")
byfunc = defaultdict(list)
for a, t in lines:
    m = re.match(r'movl?\s+\$(0x[0-9a-f]+|\d+),0x18\(%(\w+)\)', t)
    if m and int(m.group(1), 0) <= 0x20:
        byfunc[func_start(a)].append((a, int(m.group(1), 0)))
for f in sorted(byfunc):
    out.append(f"  func~{f:#x}: {[(hex(a), hex(v)) for a, v in byfunc[f]]}")

# ---- [C] ドアベル MMR (0x3020/0x3030) への即値参照 (コード部のみ) ----
out.append("")
out.append("== [C] immediate refs to $0x3020/$0x3030 ==")
for a, t in lines:
    if re.search(r'\$0x302[0-9a-f]\b|\$0x303[0-9a-f]\b', t) and 'imul' not in t and 'and' not in t:
        out.append(f"  {a:#x} func~{func_start(a):#x}: {t}")

# ---- [D] 集計: Func 値 -> 発行関数 ----
out.append("")
out.append("== [D] summary: Func value -> issuer functions (via 0x1a0bc) ==")
agg = defaultdict(set)
unresolved = []
for a, fs, store in results:
    if store and store[0] == 'imm':
        agg[store[1]].add(fs)
    elif store and store[0] == 'reg' and store[1] is not None:
        agg[store[1]].add(fs)
    else:
        unresolved.append((a, fs, store))
for v in sorted(agg):
    out.append(f"  Func {v:#04x}: issuers {[hex(x) for x in sorted(agg[v])]}")
out.append(f"  unresolved call sites: {[(hex(a), hex(f)) for a, f, s in unresolved]}")
out.append("  special path: Func 0x1b issued by func~0x3df56 (push $0x1b -> MMR 0x3020, 実読済み)")
print("\n".join(out))
