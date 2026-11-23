#!/usr/bin/env python3
# hw17: N-013 stage 1 - correlation analysis of the field-2 0x37Exx-0x37Fxx band
# across ALL existing field-2 dumps on 検証ホスト (read-only; no new device access).
# Dumps used (all 1MB field 2 = DDR 0x100000-0x200000):
#   boot2 (hw14 run, 2026-11-20 morning):
#     B2_NOCARD      pre_f2_065716 + f3_065905..f3_070530 (6 samples, card out, no session)
#     B2_CARD_NOSESS f3_070842, f3_071022, preB_f2_071344 (3 samples, card in, no session)
#                    + f3_071158 (partial file 991232 B, but band < 0x38000 fully present;
#                      used ONLY as an extra band sample, listed separately)
#     B2_SESSION     postB_f2_071533, postB2_f2_071813 (2 samples, session started)
#   boot1 (hw11 run, session ALWAYS on):
#     B1_INS_SESS    f2_001814, f2_001951, f2_002126 (inserted)
#     B1_REM_SESS    f2_002439, f2_002616, f2_002752 (removed, untorn)
#     B1_REI_SESS    f2_003106, f2_003241, f2_003419 (reinserted)
# Excluded: f2_001547 (pre-main-run cycle), f2_002303/f2_002928 (torn by events),
#           f2_003557 (partial), f3_070706 (torn by insertion).
# Privacy: band dwords are printed raw only when small (<=0xFFFF) or already known
# (+0x37FD8 card-nosession value); otherwise sha12 + class. No byte-runs printed.
import os, struct, hashlib
LAB = os.path.expanduser('~/dth30-lab')
BAND_LO, BAND_HI = 0x37E00, 0x38000   # 128 dwords
KNOWN_RAW = {0x039caef0}

def load(fn):
    with open(os.path.join(LAB, fn), 'rb') as f: data = f.read()
    return struct.unpack('<%dI' % (len(data)//4), data[:len(data)//4*4])

def fmt(v):
    if v == 0: return '0'
    if v <= 0xFFFF or v in KNOWN_RAW: return '%#x' % v
    h = hashlib.sha256(struct.pack('<I', v)).hexdigest()[:8]
    return 'sha:%s' % h

def cls(v):
    if v == 0: return 'zero'
    if v <= 0xFFFF: return 'small'
    if 0x100000 <= v < 0x400000: return 'ddr-addr-like'
    if (v >> 28) in (0x8, 0xA): return 'kseg-addr-like'
    return 'other'

GROUPS = [
    ('B2_NOCARD',      ['pre_f2_065716.bin','f3_065905.bin','f3_070041.bin','f3_070217.bin','f3_070354.bin','f3_070530.bin']),
    ('B2_CARD_NOSESS', ['f3_070842.bin','f3_071022.bin','preB_f2_071344.bin']),
    ('B2_SESSION',     ['postB_f2_071533.bin','postB2_f2_071813.bin']),
    ('B1_INS_SESS',    ['f2_001814.bin','f2_001951.bin','f2_002126.bin']),
    ('B1_REM_SESS',    ['f2_002439.bin','f2_002616.bin','f2_002752.bin']),
    ('B1_REI_SESS',    ['f2_003106.bin','f2_003241.bin','f2_003419.bin']),
]
EXTRA_NOSESS = ('B2_CARD_NOSESS(partial f3_071158)', 'f3_071158.bin')

data = {}
for name, files in GROUPS:
    data[name] = [load(f) for f in files]
extra = load(EXTRA_NOSESS[1])

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

lo_i, hi_i = BAND_LO//4, BAND_HI//4
P('hw17 band correlation analysis (N-013 stage 1): band field2 +0x37E00..+0x38000 (DDR 0x137E00..0x138000)')
P('groups: ' + ', '.join('%s n=%d' % (n, len(data[n])) for n, _ in GROUPS))

def gvals(name, i):
    return {d[i] for d in data[name]}
def gsingle(name, i):
    s = gvals(name, i)
    return s.pop() if len(s) == 1 else None

# --- 1. anchor dwords full table
P()
P('== anchors across all groups (raw) ==')
for off in (0x37FD8, 0x37FF0):
    i = off//4
    row = []
    for name, _ in GROUPS:
        s = gvals(name, i)
        row.append('%s=%s' % (name, fmt(next(iter(s))) if len(s) == 1 else 'CHURN{%s}' % ','.join(fmt(v) for v in sorted(s))))
    P('off %#x: ' % off + ' | '.join(row))
    P('   extra nosess partial sample: %s' % fmt(extra[i]))

# --- 2. strict correlation scans
P()
P('== strict state-correlated dwords in band ==')
b2 = ['B2_NOCARD', 'B2_CARD_NOSESS', 'B2_SESSION']
b1 = ['B1_INS_SESS', 'B1_REM_SESS', 'B1_REI_SESS']
strict_b2, strict_b1, churn_band = [], [], []
for i in range(lo_i, hi_i):
    off = i*4
    v2 = [gsingle(n, i) for n in b2]
    if all(v is not None for v in v2) and len(set(v2)) > 1:
        strict_b2.append((off, v2))
    v1 = [gsingle(n, i) for n in b1]
    if all(v is not None for v in v1) and v1[0] == v1[2] and v1[0] != v1[1]:
        strict_b1.append((off, v1))
    if any(gsingle(n, i) is None for n, _ in GROUPS):
        churn_band.append(off)
P('-- boot2 strict (internally consistent in all 3 states, not all equal): %d' % len(strict_b2))
for off, v2 in strict_b2:
    ex = extra[off//4]
    P('   off %#x: NOCARD=%s CARD_NOSESS=%s SESSION=%s | extra-nosess=%s (%s)'
      % (off, fmt(v2[0]), fmt(v2[1]), fmt(v2[2]), fmt(ex), 'MATCHES nosess' if ex == v2[1] else 'differs'))
P('-- boot1 strict flip-flop (INS==REI != REM, internally consistent): %d' % len(strict_b1))
for off, v1 in strict_b1:
    P('   off %#x: INS=%s REM=%s REI=%s' % (off, fmt(v1[0]), fmt(v1[1]), fmt(v1[2])))
both = sorted({o for o, _ in strict_b2} & {o for o, _ in strict_b1})
P('-- strict in BOTH boots: %s' % (['%#x' % o for o in both] or 'none'))
P('-- band dwords that churn within at least one state group: %d of %d' % (len(churn_band), hi_i-lo_i))
P('   churn offsets: %s' % ' '.join('%#x' % o for o in churn_band))

# --- 3. band structure: classification + nonzero runs for representative dumps
P()
P('== band structure (representative dumps) ==')
REPS = [('B2_CARD_NOSESS rep preB_f2', 'preB_f2_071344.bin'),
        ('B2_SESSION rep postB2_f2', 'postB2_f2_071813.bin'),
        ('B1_REM_SESS rep f2_002616', 'f2_002616.bin'),
        ('B2_NOCARD rep pre_f2', 'pre_f2_065716.bin')]
for label, fn in REPS:
    d = load(fn)
    band = d[lo_i:hi_i]
    from collections import Counter
    c = Counter(cls(v) for v in band)
    runs = []
    start = None
    for k, v in enumerate(band):
        if v != 0 and start is None: start = k
        if (v == 0 or k == len(band)-1) and start is not None:
            end = k-1 if v == 0 else k
            runs.append((BAND_LO + start*4, BAND_LO + end*4 + 4))
            start = None
    P('%s: classes %s' % (label, dict(c)))
    P('   nonzero runs: %s' % (', '.join('[%#x..%#x)' % r for r in runs) or 'none'))

# --- 4. neighbourhood detail around the anchors (values by policy fmt)
P()
P('== neighbourhood detail (boot2 groups + boot1 REM) ==')
for center in (0x37FD8, 0x37FF0):
    P('-- around %#x --' % center)
    for off in range(center-0x20, center+0x24, 4):
        i = off//4
        cells = []
        for name in ('B2_NOCARD', 'B2_CARD_NOSESS', 'B2_SESSION', 'B1_REM_SESS'):
            v = gsingle(name, i)
            cells.append('%s=%s' % (name.split('_', 1)[1], fmt(v) if v is not None else 'CHURN'))
        P('   off %#x: %s' % (off, ' | '.join(cells)))

with open(os.path.join(LAB, 'hw17_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P()
P('summary written to hw17_summary.txt')
