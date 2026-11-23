import re, struct
SYS="~/dth30-re/pkg/DTH30U2DRV_143/Drivers/BufFsUSB.sys"
data=open(SYS,"rb").read()
def read_str(pa):
    off=pa-0x10C00
    if off<0 or off>=len(data): return None
    end=data.find(b"\x00",off)
    try: return data[off:end].decode("ascii",errors="replace")
    except: return None
ASM="~/dth30-re/disasm/BufFsUSB.asm"
insn_re = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+)\s*\t(.*)$')
lines=[]
for raw in open(ASM, encoding="utf-8", errors="replace"):
    m=insn_re.match(raw.rstrip("\n"))
    if m: lines.append((int(m.group(1),16), m.group(3).strip()))
idx={a:i for i,(a,_) in enumerate(lines)}
def fend(s):
    for a,t in lines[idx[s]+1:]:
        if t.startswith("int3"): return a
    return None
for h in (0x33dee,0x35cf0,0x39736,0x3c8f2,0x36748):
    e=fend(h)
    print(f"== handler {h:#x}..{e:#x} ==")
    seen=set()
    for a,t in lines:
        if h<=a<=e:
            m=re.search(r'push\s+\$(0x4[0-9a-f]{4,5})\b', t)
            if m:
                pa=int(m.group(1),16)
                s=read_str(pa)
                if s and s not in seen and len(s)>=4:
                    seen.add(s); print(f"   {a:#x} -> {s!r}")
