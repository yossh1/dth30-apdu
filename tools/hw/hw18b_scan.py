#!/usr/bin/env python3
# hw18b: N-018 follow-up - "cold object" scan. hw18 phase 2 required the record
# path to have run (obj+0xFF0/+0x334 holding VAs). If it never ran in captured
# states, those fields stay 0 and the object is missed. This scan anchors on
# init-time constants that stage2/stage5 write into THIS ctx unconditionally:
#   ctx+0x8E24 = 1   (stage2, excerpts G: sw 1 via ctx+0x8000 form +0xE24)
#   ctx+0x4B1C = 1   (stage5, excerpts F: sw $v0(=1), 0x4b1c(ctx))
# obj = ctx + 0x1408, so relative to obj base X:
#   dword[X+0x7A1C] == 1  and  dword[X+0x3714] == 1
# plus the structural relations that hold regardless of record-path activity:
#   dword[X+0xFF8] == dword[X+0x110]   (copy target starts equal after memset;
#                                      NOTE: only equal if routine ran or both 0)
#   dword[X+0x1000] small (mode)
# Tier A: all conditions. Tier B: both =1 markers + mode small, FF8/110 reported
# as-is (in case the copy relation does not hold pre-run).
# Same dumps / privacy policy as hw18_sigsearch.py.
import os, struct, hashlib, glob
from collections import defaultdict

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

def field_base(fn):
    if 'shared' in fn:
        return 0
    if fn.startswith(('f2_', 'f3_', 'pre_f2', 'preB_f2', 'postB_f2', 'postB2_f2')):
        return 0x100000
    if fn.startswith('heap_'):
        return 0x200000
    return 0

def boot_of(fn):
    if fn.startswith(('f3_', 'mon3_', 'pre_f2', 'pre_shared', 'preB_', 'postB')):
        return 'boot2'
    return 'boot1'

files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(LAB, '*.bin')))
out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

P('hw18b cold-object scan (N-018): anchors ctx+0x8E24==1 (obj+0x7A1C), ctx+0x4B1C==1 (obj+0x3714)')
tierA, tierB = [], []
for fn in files:
    base, boot = field_base(fn), boot_of(fn)
    with open(os.path.join(LAB, fn), 'rb') as f:
        raw = f.read()
    d = struct.unpack('<%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])
    n = len(d)
    for xi in range(n):
        X = xi * 4
        if X + 0x7A20 > n * 4:
            break
        if d[xi + 0x7A1C // 4] != 1 or d[xi + 0x3714 // 4] != 1:
            continue
        mode = d[xi + 0x1000 // 4]
        if mode >= 0x10:
            continue
        ff8 = d[xi + 0xFF8 // 4]; v110 = d[xi + 0x110 // 4]
        rec = (fn, boot, base, X, d[xi + 0xFF0 // 4], d[xi + 0x334 // 4],
               ff8, v110, mode, d[xi + 0x808 // 4], d[xi + 0x8C // 4], d[xi + 0x90 // 4])
        if ff8 == v110:
            tierA.append(rec)
        else:
            tierB.append(rec)

def show(label, recs):
    P('%s: %d' % (label, len(recs)))
    for fn, boot, base, X, ff0, cur, ff8, v110, mode, st, d8c, d90 in recs:
        P('   %s (%s) obj_off=%#x -> ctx phys = %#x | +0xFF0=%s +0x334=%s +0xFF8=%s '
          '+0x110=%s +0x1000=%#x +0x808=%s +0x8C=%s +0x90=%s'
          % (fn, boot, X, base + X - 0x1408, fmt(ff0), fmt(cur), fmt(ff8),
             fmt(v110), mode, fmt(st), fmt(d8c), fmt(d90)))

show('tier A (markers + FF8==+0x110 + mode small)', tierA)
show('tier B (markers + mode small, FF8!=+0x110)', tierB)

with open(os.path.join(LAB, 'hw18b_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P('summary written to hw18b_summary.txt')
