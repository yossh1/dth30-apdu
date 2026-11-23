#!/usr/bin/env python3
# hw19 analyze v2: N-021 - signature search + census over the hw19 spot dumps.
# Per-region streaming (array('I')) to stay within 検証ホスト RAM; no device access.
#
# Regions (phys base): spot_f1_* = field 1 (phys 0x000000), spot_f3tail_* =
# field 3 offsets 0x90000.. (phys 0x290000), spot_f<f>_* for f>=4 = field f
# (phys (f-1)*0x100000). Fields 71/72 are probe-classified mirrors of 7/8
# whose vectors differed only by live-data churn.
#
# (a) record-tag census: exact 8 tags + family (hw18 definitions), plus the
#     obj relation scan of hw18 phase 2.
# (b) return-flag semantics scan: dwords composed ONLY of the corrected flag
#     bits {INSERTED 0x2000, REMOVED 0x4000, ACTIVATED 0x8000,
#     EMM_COMMAND 0x80000, CARDID 0x400000, VALID 0x800000} (nonzero).
# (c) census per region: nonzero %, longest zero run, value classes,
#     per-64KB nonzero% spread.
# Single device state (card in, session on): structure only, NO card/session
# correlation can be judged from this data alone.
# Privacy (hw17/hw18 policy): offsets, tag values and flag values raw; other
# dwords as sha12+class. Payload dwords are never printed.
import os, struct, hashlib, glob
from array import array
from collections import Counter

LAB = os.path.expanduser('~/dth30-lab')
EXACT_TAGS = {0x731c00c0, 0x731000c0, 0x730c00c0, 0x728400c0,
              0x728800c0, 0x730800c0, 0x732000c0, 0x72d000c0}
FLAG_BITS = 0x2000 | 0x4000 | 0x8000 | 0x80000 | 0x400000 | 0x800000
FLAG_NAMES = [(0x2000, 'INSERTED'), (0x4000, 'REMOVED'), (0x8000, 'ACTIVATED'),
              (0x80000, 'EMM'), (0x400000, 'CARDID'), (0x800000, 'VALID')]

def is_tag_family(v):
    return (v & 0xFFFF) == 0x00C0 and 0x7200 <= (v >> 16) < 0x7400

def cls(v):
    if v == 0: return 'zero'
    if v <= 0xFFFF: return 'small'
    if (v >> 28) in (0x8, 0xA): return 'kseg-va'
    if 0x100000 <= v < 0x4000000: return 'ddr-phys-like'
    return 'other'

def fmt(v):
    if cls(v) in ('zero', 'small', 'kseg-va', 'ddr-phys-like'):
        return '%#x' % v
    return 'sha:%s(%s)' % (hashlib.sha256(struct.pack('<I', v)).hexdigest()[:8], cls(v))

def region_of(fn):
    b = os.path.basename(fn)
    if b.startswith('spot_f3tail_'): return ('field3-tail', 0x290000)
    if b.startswith('spot_f1_'): return ('field1', 0)
    if b.startswith('spot_f'):
        f = int(b.split('_')[1][1:])
        return ('field%d' % f, (f - 1) * 0x100000)
    return (None, None)

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s, flush=True)

files = sorted(glob.glob(os.path.join(LAB, 'spot_*.bin')))
meta = []
for fn in files:
    name, base = region_of(fn)
    if name is not None:
        meta.append((name, base, fn))
P('hw19 analysis v2 (N-021): spot regions = %d' % len(meta))

tag_lines = []
tot_e = tot_f = 0
rel_cands = []
flag_total = 0
flag_per_region = Counter()
flag_examples = []
census_lines = []
total_dw = 0

for name, base, fn in meta:
    with open(fn, 'rb') as fh: raw = fh.read()
    d = array('I'); d.frombytes(raw[:len(raw) // 4 * 4])
    del raw
    n = len(d); total_dw += n
    # (a) tags
    e_cnt = f_cnt = 0
    for i, v in enumerate(d):
        if v in EXACT_TAGS: e_cnt += 1
        elif is_tag_family(v):
            f_cnt += 1
            if f_cnt <= 5:
                tag_lines.append('   family hit %s phys %#x val %s' % (name, base + i * 4, fmt(v)))
    tot_e += e_cnt; tot_f += f_cnt
    if e_cnt or f_cnt:
        tag_lines.append('%s: exact=%d family=%d' % (name, e_cnt, f_cnt))
    # (a2) relation scan
    for i in range(n):
        v = d[i]
        if (v >> 28) not in (0x8, 0xA): continue
        X = i * 4 - 0xFF0
        if X < 0 or X + 0x1008 > n * 4: continue
        xi = X // 4
        bp = v & 0x1FFFFFFF
        cur = d[xi + 0x334 // 4]
        if (cur >> 28) not in (0x8, 0xA): continue
        cp = cur & 0x1FFFFFFF
        if not (4 <= cp - bp <= 0x2004) or (cp - bp) % 4: continue
        if d[xi + 0xFF8 // 4] != d[xi + 0x110 // 4]: continue
        if d[xi + 0x1000 // 4] >= 0x10: continue
        rel_cands.append((name, base + X, v, cur))
    # (b) flag scan + (c) census in one pass
    nz = 0; classes = Counter(); best = run = 0
    blocks = [0] * ((n + 0x3FFF) // 0x4000)
    for i, v in enumerate(d):
        if v:
            nz += 1; blocks[i // 0x4000] += 1; run = 0
            if (v & ~FLAG_BITS) == 0:
                flag_total += 1; flag_per_region[name] += 1
                if len(flag_examples) < 40:
                    names = '|'.join(nm for bit, nm in FLAG_NAMES if v & bit)
                    flag_examples.append((name, base + i * 4, v, names))
        else:
            run += 1
            if run > best: best = run
        classes[cls(v)] += 1
    bpct = [100.0 * c / 0x4000 for c in blocks]
    census_lines.append('%-12s nz%%=%.1f zero-run-max=%d dw | classes: %s | 64KB blocks: zero=%d/%d dense(>99%%)=%d min=%.0f%% max=%.0f%%'
        % (name, 100.0 * nz / n, best,
           ' '.join('%s=%d' % kv for kv in classes.most_common()),
           sum(1 for x in bpct if x == 0.0), len(bpct),
           sum(1 for x in bpct if x > 99.0), min(bpct), max(bpct)))
    del d

P('total dwords scanned = %d' % total_dw)
P()
P('== (a) record-tag census ==')
for s in tag_lines: P(s)
P('totals: exact=%d family=%d' % (tot_e, tot_f))
P()
P('== (a2) obj relation scan ==')
P('candidates: %d' % len(rel_cands))
for name, phys, ff0, cur in rel_cands[:20]:
    P('   %s obj phys %#x +0xFF0=%s +0x334=%s' % (name, phys, fmt(ff0), fmt(cur)))
P()
P('== (b) return-flag semantics scan ==')
P('flag-only dwords: %d' % flag_total)
for name, cnt in flag_per_region.most_common():
    P('   %-12s %d' % (name, cnt))
for name, phys, v, names in flag_examples:
    P('   ex %s phys %#x val %#x (%s)' % (name, phys, v, names))
P()
P('== (c) census per region ==')
for s in census_lines: P(s)

with open(os.path.join(LAB, 'hw19_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P()
P('summary written to hw19_summary.txt')
