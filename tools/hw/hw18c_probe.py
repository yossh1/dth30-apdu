#!/usr/bin/env python3
# hw18c: N-018 follow-up probe of the two ctx windows in representative dumps.
#  - candidate ctx window: field2 [0x88DC, 0x88DC+0x10818)  (hw18b tier-A hit)
#  - predicted ctx window: field2 [0x35BF8, 0x35BF8+0x10818) (H-022 prediction)
# Prints nonzero-dword census (offset + value) per window per dump.
# Privacy: small / kseg-va / ddr-phys-like values raw; others sha12+class.
# No byte runs, no payload dumps beyond single dwords in these two windows.
import os, struct, hashlib

LAB = os.path.expanduser('~/dth30-lab')

def cls(v):
    if v == 0: return 'zero'
    if v <= 0xFFFF: return 'small'
    if (v >> 28) in (0x8, 0xA): return 'kseg-va'
    if 0x100000 <= v < 0x400000: return 'ddr-phys-like'
    return 'other'

def fmt(v):
    if cls(v) in ('zero', 'small', 'kseg-va', 'ddr-phys-like'):
        return '%#x' % v
    return 'sha:%s(%s)' % (hashlib.sha256(struct.pack('<I', v)).hexdigest()[:8], cls(v))

def load(fn):
    with open(os.path.join(LAB, fn), 'rb') as f:
        raw = f.read()
    return struct.unpack('<%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])

REPS = [('pre_f2_065716.bin', 'boot2 NOCARD pre-session'),
        ('preB_f2_071344.bin', 'boot2 CARD-NOSESS'),
        ('postB2_f2_071813.bin', 'boot2 SESSION'),
        ('f2_001814.bin', 'boot1 SESSION ins'),
        ('f2_002616.bin', 'boot1 SESSION rem')]
WINDOWS = [(0x88DC, 'candidate ctx (hw18b)'), (0x35BF8, 'predicted ctx (H-022)')]

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

for fn, label in REPS:
    d = load(fn)
    P('== %s (%s) ==' % (fn, label))
    for base, wname in WINDOWS:
        lo, hi = base // 4, (base + 0x10818) // 4
        nz = [(i * 4, d[i]) for i in range(lo, min(hi, len(d))) if d[i] != 0]
        P('  window %s @%#x: nonzero dwords = %d of %d' % (wname, base, len(nz), hi - lo))
        for off, v in nz:
            P('    +%#06x (ctx+%#06x): %s' % (off, off - base, fmt(v)))
    # candidate obj entry fields (routine entry uses obj+4 / obj+8 as div pair)
    xi = 0x9CE4 // 4
    P('  candidate obj+4=%s obj+8=%s' % (fmt(d[xi + 1]), fmt(d[xi + 2])))

with open(os.path.join(LAB, 'hw18c_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P('summary written to hw18c_summary.txt')
