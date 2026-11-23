#!/usr/bin/env python3
# Diff shared_A_bootonly.bin vs shared_B_session.bin; report changed ranges and
# flag-word candidates (value at candidate+0x9C in state B). Data bytes are NOT printed
# (only hashes / digit-run presence), to keep any card ID out of logs.
import struct, hashlib, sys
A = open('/home/user/dth30-lab/shared_A_bootonly.bin', 'rb').read()
B = open('/home/user/dth30-lab/shared_B_session.bin', 'rb').read()
assert len(A) == len(B) == 0x10000
da = struct.unpack('<16384I', A); db = struct.unpack('<16384I', B)
chg = [i * 4 for i in range(16384) if da[i] != db[i]]
print(f'changed dwords: {len(chg)}')
# group into ranges
ranges = []
for off in chg:
    if ranges and off - ranges[-1][1] <= 16: ranges[-1][1] = off + 4
    else: ranges.append([off, off + 4])
print('changed ranges (off, len):', [(hex(s), hex(e - s)) for s, e in ranges])
MASK = 0x2|0x4|0x8|0x20|0x40|0x80|0x100|0x200|0x400|0x800|0x2000|0x4000|0x8000|0x10000|0x20000|0x40000|0x80000|0x100000|0x200000|0x400000|0x800000
BCAS = 0x2000|0x4000|0x8000|0x10000|0x20000|0x40000|0x80000|0x100000|0x200000|0x400000|0x800000
def bcd_density(b):
    return sum(1 for x in b if (x >> 4) <= 9 and (x & 15) <= 9 and x != 0)
print('--- flag candidates: dword at X (state B) fits mask & has BCAS bits, X = base+0x9C ---')
for off in range(0x9c, 0x10000, 4):
    v = db[off // 4]
    if v and (v & ~MASK) == 0 and (v & BCAS):
        base = off - 0x9c
        data = B[base + 0x2c: base + 0x40]
        print(f'base={base:#x} flagB={v:#010x} flagA={da[off//4]:#010x} +0x40B={db[(base+0x40)//4]:#x} '
              f'data_bcd={bcd_density(data[:10])}/10 data_sha12={hashlib.sha256(data).hexdigest()[:12]} changed={off in chg}')
