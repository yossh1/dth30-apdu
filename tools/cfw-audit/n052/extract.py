#!/usr/bin/env python3
"""firmware.asm から VA 範囲を抽出する。usage: extract.py START END OUTFILE"""
import sys, re
src = open('~/dth30-re/disasm/firmware.asm')
start, end, out = int(sys.argv[1],16), int(sys.argv[2],16), sys.argv[3]
pat = re.compile(r'^0x([0-9a-f]+):')
with open(out,'w') as f:
    for line in src:
        m = pat.match(line)
        if not m: continue
        va = int(m.group(1),16)
        if start <= va < end:
            f.write(line)
print('wrote', out)
