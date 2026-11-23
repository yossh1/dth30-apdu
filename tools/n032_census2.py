#!/usr/bin/env python3
# N-032 census #2: in each Func-0x08 issuer function, list stores to param offsets
# +0x58/+0x5c/+0x60/+0x64 (any base reg), and the request-build block before the send call.
import re

ASM = "~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
lines = []
for raw in open(ASM, encoding="utf-8", errors="replace"):
    m = insn_re.match(raw.rstrip("\n"))
    if m:
        lines.append((int(m.group(1), 16), m.group(3).strip()))
idx = {a: i for i, (a, _) in enumerate(lines)}

def func_range(start):
    end = None
    for a, t in lines[idx[start] + 1:]:
        if t.startswith("int3"):
            end = a
            break
    return (start, end)

issuers = {
    0x1FF84: (0x203DF, 0x22C20, 0x22C41),
    0x22F22: (0x232F7, 0x2591F, 0x25940),
    0x26BFE: (0x2737A, 0x2AD06, 0x2AD27),
    0x2AFC4: (0x2B5E0, 0x2DDC1, 0x2DDE1),
    0x2DF9C: (0x2E292, 0x311D1, 0x311F2),
    0x314CA: (0x316C9, 0x31DC6, 0x31DE5),
}
pat = re.compile(r'(movl|movw|movb|orl|andl|mov)\s+.*,(0x58|0x5c|0x60|0x64)\(%\w+\)')
for fstart, (alloc, imm, send) in sorted(issuers.items()):
    s, e = func_range(fstart)
    print(f"== issuer func {fstart:#x}..{e:#x}  alloc@{alloc:#x} imm8@{imm:#x} send@{send:#x} ==")
    for a, t in lines:
        if s <= a <= e and pat.search(t):
            print(f"   {a:#x}: {t}")
    print()
