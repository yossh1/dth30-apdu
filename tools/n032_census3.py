import re
ASM="~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
lines=[]
for raw in open(ASM, encoding="utf-8", errors="replace"):
    m=insn_re.match(raw.rstrip("\n"))
    if m: lines.append((int(m.group(1),16), m.group(3).strip()))
idx={a:i for i,(a,_) in enumerate(lines)}
ranges={0x1ff84:0x22c65,0x22f22:0x2594f,0x26bfe:0x2ad41,0x2afc4:0x2ddf0,0x2df9c:0x31201,0x314ca:0x31e03}
for s,e in ranges.items():
    print(f"== issuer {s:#x} ==")
    for a,t in lines:
        if not (s<=a<=e): continue
        m=re.search(r'(?:lea|add)\s+(?:\$)?(0x58|0x5c|0x60)\(%', t) or re.search(r'add\s+\$(0x58|0x5c|0x60),', t)
        if m:
            off=m.group(1)
            i=idx[a]
            win=lines[i:i+8]
            for ca,ct in win:
                if "call   0x42b36" in ct or "call   0x42984" in ct:
                    kind = "SET" if "42b36" in ct else "GET"
                    pushes=[x[1] for x in win if x[1].startswith("push")]
                    ors=[x[1] for x in lines[max(0,i-14):i] if re.search(r'\bor\s+\$0x[0-9a-f]+,', x[1])]
                    print(f"   {a:#x} param+{off} {kind} pushes={pushes} prior_or={ors[-1] if ors else ''}")
                    break
