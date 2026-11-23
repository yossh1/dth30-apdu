import re
pat=re.compile(r'^0x([0-9a-f]+): [0-9a-f]+  (.*)$')
rows=[]
with open('~/dth30-re/disasm/firmware.asm') as f:
    for line in f:
        m=pat.match(line)
        if not m: continue
        va=int(m.group(1),16); ins=m.group(2)
        if 0xa0121000<=va<0xa0127000 and re.search(r'\bs[whb]\s+\$\w+, 0x11[04]\(', ins):
            rows.append((va,ins.strip()))
for va,ins in rows: print(hex(va), ins)
print('total', len(rows))
