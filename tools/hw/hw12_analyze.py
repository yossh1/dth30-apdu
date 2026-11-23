#!/usr/bin/env python3
# hw12: analysis of hw11 dumps (N-007 MMR correlation + N-008 field 2 structure search).
# Runs on 検証ホスト in ~/dth30-lab (raw dumps stay there; only this summary leaves).
# User-declared events (JST): card REMOVED 00:24:20, REINSERTED 00:30:21 (2026-11-20).
# Cycle timeline (from hw11.log): each cycle = MMR snapshot, then mon2 dump (fast),
# then f2 dump (~90 s). A state change mid-cycle tears the f2 dump of that cycle.
# Privacy: for f2 (DDR field 2) we never print raw data-region values. Changed dwords
# are reported as offset + flag-bit projection (mask of known BCAS flag bits) +
# whether non-flag bits are zero/stable. mon2 (shared mailbox) follows hw10 precedent.
import os, re, struct, sys, glob

LAB = os.path.dirname(os.path.abspath(__file__))
REMOVAL = '002420'   # HHMMSS
REINSERT = '003021'

FLAGBITS = {
    0x2000: 'INSERTED', 0x4000: 'REMOVED', 0x8000: 'ACTIVATED',
    0x80000: 'EMM_COMMAND', 0x400000: 'CARDID', 0x800000: 'VALID',
}
FLAGMASK = 0
for b in FLAGBITS: FLAGMASK |= b

def load(p):
    with open(p, 'rb') as f: return f.read()

def dwords(b):
    return struct.unpack('<%dI' % (len(b)//4), b[:len(b)//4*4])

def parse_log():
    cycles = []  # (n, start_ts, {addr:val})
    rx = re.compile(r'cycle (\d+) start (\d{6}) mmr (.*)')
    with open(os.path.join(LAB, 'hw11.log')) as f:
        for line in f:
            m = rx.search(line)
            if m:
                snap = {}
                for kv in m.group(3).split():
                    a, v = kv.split('='); snap[int(a, 16)] = int(v, 16)
                cycles.append((int(m.group(1)), m.group(2), snap))
    return cycles

def state_of(ts):
    # state at cycle START (mon2 + MMR reflect this; f2 may be torn if event mid-cycle)
    if ts < REMOVAL: return 'inserted'
    if ts < REINSERT: return 'removed'
    return 'reinserted'

def torn_f2(ts):
    # f2 dump spans roughly [ts+8s, ts+95s]; torn if an event falls inside
    def sec(t): return int(t[:2])*3600 + int(t[2:4])*60 + int(t[4:])
    s, e = sec(ts) + 8, sec(ts) + 95
    return any(s <= sec(ev) <= e for ev in (REMOVAL, REINSERT))

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

cycles = parse_log()
P('=== hw11 cycles (main run, start>=001814) ===')
main = [c for c in cycles if c[1] >= '001814']
for n, ts, snap in main:
    P('cycle %d start %s state_at_start=%s f2_torn=%s' % (n, ts, state_of(ts), torn_f2(ts)))

P()
P('=== N-007: MMR time series ===')
addrs = sorted(main[0][2].keys())
hdr = 'cycle start  state      ' + ' '.join('%04x' % a for a in addrs)
P(hdr)
for n, ts, snap in main:
    P('%5d %s %-10s ' % (n, ts, state_of(ts)) + ' '.join('%08x' % snap[a] for a in addrs))
changed = [a for a in addrs if len({snap[a] for _, _, snap in main}) > 1]
P('MMR registers that changed across all cycles:', [hex(a) for a in changed] or 'NONE')

def analyze_region(pattern, name, raw_ok, expect_size=None):
    files = sorted(glob.glob(os.path.join(LAB, pattern)))
    files = [f for f in files if os.path.basename(f).split('_')[1][:6] >= '001814']
    if expect_size:
        kept = []
        for f in files:
            if os.path.getsize(f) == expect_size: kept.append(f)
            else: print('SKIP incomplete %s (%d B)' % (os.path.basename(f), os.path.getsize(f)))
        files = kept
    P()
    P('=== %s: %d dumps ===' % (name, len(files)))
    seq = []
    for f in files:
        ts = os.path.basename(f).split('_')[1][:6]
        b = load(f)
        seq.append((ts, dwords(b)))
        P('%s size=%d state_at_start=%s' % (ts, len(b), state_of(ts)))
    # consecutive diff counts
    P('-- consecutive diff (dword count) --')
    for (t0, d0), (t1, d1) in zip(seq, seq[1:]):
        n = min(len(d0), len(d1))
        diff = [i for i in range(n) if d0[i] != d1[i]]
        P('%s -> %s : %d dwords differ' % (t0, t1, len(diff)))
    # state-representative comparison: use last pure inserted, middle removed, last reinserted
    ins = [s for s in seq if state_of(s[0]) == 'inserted']
    rem = [s for s in seq if state_of(s[0]) == 'removed' and not torn_f2(s[0])]
    rei = [s for s in seq if state_of(s[0]) == 'reinserted']
    if ins and rem and rei:
        base, rm, ri = ins[-1], rem[len(rem)//2], rei[-1]
        P('-- state comparison: inserted=%s removed=%s reinserted=%s --' % (base[0], rm[0], ri[0]))
        n = min(len(base[1]), len(rm[1]), len(ri[1]))
        flipflop, oneway, other = [], [], []
        for i in range(n):
            a, b, c = base[1][i], rm[1][i], ri[1][i]
            if a == b == c: continue
            if a != b and c == a: flipflop.append(i)
            elif a != b and c != a: oneway.append(i)
            else: other.append(i)
        P('flip-flop (changes on removal, reverts on reinsert): %d dwords' % len(flipflop))
        for i in flipflop:
            a, b, c = base[1][i], rm[1][i], ri[1][i]
            if raw_ok:
                P('  off 0x%05x: ins=%08x rem=%08x rei=%08x' % (i*4, a, b, c))
            else:
                fa, fb, fc = a & FLAGMASK, b & FLAGMASK, c & FLAGMASK
                def names(v): return '|'.join(nm for bit, nm in FLAGBITS.items() if v & bit) or '-'
                P('  off 0x%05x: flagbits ins=[%s] rem=[%s] rei=[%s]; nonflag ins/rem/rei zero=%s/%s/%s stable_nonflag=%s'
                  % (i*4, names(fa), names(fb), names(fc),
                     (a & ~FLAGMASK) == 0, (b & ~FLAGMASK) == 0, (c & ~FLAGMASK) == 0,
                     (a & ~FLAGMASK) == (b & ~FLAGMASK) == (c & ~FLAGMASK)))
        P('one-way / non-reverting changed dwords: %d' % len(oneway))
        for i in oneway[:40]:
            a, b, c = base[1][i], rm[1][i], ri[1][i]
            if raw_ok:
                P('  off 0x%05x: ins=%08x rem=%08x rei=%08x' % (i*4, a, b, c))
            else:
                P('  off 0x%05x: changed (values withheld); flagbits ins/rem/rei = %06x/%06x/%06x'
                  % (i*4, a & FLAGMASK, b & FLAGMASK, c & FLAGMASK))
        P('changed only between inserted->reinserted or within-state noise: %d dwords' % len(other))
        # stability within states (is the region static inside one state?)
        for label, group in (('inserted', ins), ('removed', rem), ('reinserted', rei)):
            if len(group) >= 2:
                g0 = group[0][1]
                tot = set()
                for _, g in group[1:]:
                    for i in range(min(len(g0), len(g))):
                        if g0[i] != g[i]: tot.add(i)
                P('within-state %s: %d distinct dwords vary across %d dumps' % (label, len(tot), len(group)))
    return seq

seq_mon = analyze_region('mon2_*.bin', 'mon2 shared region (field 0)', raw_ok=True, expect_size=0x10000)
# mon2 +0xF4 block detail across all cycles
P()
P('=== mon2 +0xF0..+0x100 timeline ===')
for ts, d in seq_mon:
    P('%s state=%-10s ' % (ts, state_of(ts)) + ' '.join('+%02x=%08x' % (o, d[o//4]) for o in (0xF0, 0xF4, 0xF8, 0xFC, 0x100)))
analyze_region('f2_*.bin', 'f2 DDR field 2 (0x100000-0x200000)', raw_ok=False, expect_size=0x100000)

with open(os.path.join(LAB, 'hw12_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P()
P('summary written to hw12_summary.txt')
