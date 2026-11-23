import re
ASM="~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
lines=[]
for raw in open(ASM, encoding="utf-8", errors="replace"):
    m=insn_re.match(raw.rstrip("\n"))
    if m: lines.append((int(m.group(1),16), m.group(3).strip()))
S,E=0x27c00,0x28620
seg=[(a,t) for a,t in lines if S<=a<=E]
for i,(a,t) in enumerate(seg):
    if re.search(r'\bor\s+\$0x[0-9a-f]+,%eax', t):
        # find gate: nearest preceding test/cmp within 12 insns
        gate=""
        for b,u in reversed(seg[max(0,i-12):i]):
            if u.startswith(("test","cmp","testb","testw","cmpl")):
                gate=f"{b:#x}: {u}"; break
        print(f"{a:#x}: {t:28s} gate: {gate}")
