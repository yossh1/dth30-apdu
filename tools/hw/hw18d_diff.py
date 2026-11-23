#!/usr/bin/env python3
# hw18d: N-018 follow-up - diffs of the candidate ctx window (field2
# [0x88DC, 0x88DC+0x10818)) between representative dumps:
#   pre_f2 (boot2 nocard) -> preB_f2 (boot2 card-nosess): insertion-only effect
#   preB_f2 -> postB2_f2 (boot2 session): session-start effect (the +6)
#   f2_001814 (boot1 session) vs postB2_f2 (boot2 session): cross-boot stability
# Privacy: same fmt policy as hw18 (small/kseg-va/ddr-phys raw, else sha12).
import os, struct, hashlib

LAB = os.path.expanduser('~/dth30-lab')
BASE, SIZE = 0x88DC, 0x10818

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

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

def diff(fn1, fn2, label):
    d1, d2 = load(fn1), load(fn2)
    lo, hi = BASE // 4, (BASE + SIZE) // 4
    ch = [(i * 4, d1[i], d2[i]) for i in range(lo, hi) if d1[i] != d2[i]]
    P('%s: %d changed dwords in candidate window' % (label, len(ch)))
    for off, a, b in ch:
        P('   off %#x (ctx+%#x): %s -> %s' % (off, off - BASE, fmt(a), fmt(b)))

diff('pre_f2_065716.bin', 'preB_f2_071344.bin', 'boot2 insertion-only (pre_f2 -> preB_f2)')
diff('preB_f2_071344.bin', 'postB2_f2_071813.bin', 'boot2 session-start (preB_f2 -> postB2_f2)')
diff('f2_001814.bin', 'postB2_f2_071813.bin', 'cross-boot session (boot1 f2_001814 vs boot2 postB2)')

with open(os.path.join(LAB, 'hw18d_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P('summary written to hw18d_summary.txt')
