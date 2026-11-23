#!/usr/bin/env python3
# N-010: find instruction sequences where a register is loaded from [x+0x18]
# and the same register (or one derived from it) is used as base for a store
# to +0x11C within a small window. Also list every store to +0x11C with the
# preceding add/mov context so each can be classified by hand.
import re

ASM = "~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r"^\s+([0-9a-f]+):\t[0-9a-f ]+\t(.*)$")
insns = []
for ln in open(ASM, errors="replace"):
    m = insn_re.match(ln)
    if m:
        insns.append((int(m.group(1), 16), m.group(2).strip()))

store11c = re.compile(r"^(mov|movl|andl|orl|add|sub)\s+.+,\s*(?:0x[0-9a-f]+,)?0x11c\(%(\w+)\)")
print("=== all stores to +0x11C with 6-insn context ===")
for i, (va, t) in enumerate(insns):
    m = store11c.match(t)
    if m and "0x11c(" in t:
        base = m.group(2)
        ctx = insns[max(0, i - 6):i]
        print(f"\n@{va:#x}: {t}   [base=%{base}]")
        for cva, ct in ctx:
            print(f"    @{cva:#x}: {ct}")
