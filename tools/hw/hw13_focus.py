#!/usr/bin/env python3
# hw13: noise-robust flip-flop scan of hw11 f2 dumps.
# hw12's 3-representative comparison found 6 candidate flip-flops, but field 2 has
# ~69 dwords of within-state churn, so single-representative hits may be coincidence.
# Here: use only untorn dumps per state, require the modal value of each state group
# to be 100% consistent within the group, and modal_inserted == modal_reinserted
# != modal_removed. Raw values are never printed: flag-bit projection + short hash only.
import os, struct, hashlib
from collections import Counter

LAB = os.path.dirname(os.path.abspath(__file__))
FLAGBITS = {0x2000:'INSERTED',0x4000:'REMOVED',0x8000:'ACTIVATED',0x80000:'EMM_COMMAND',0x400000:'CARDID',0x800000:'VALID'}
FLAGMASK = 0
for b in FLAGBITS: FLAGMASK |= b

GROUPS = {
    'inserted':   ['001814','001951','002126'],            # untorn, before removal 00:24:20
    'removed':    ['002439','002616','002752'],            # untorn, removal..reinsert 00:30:21
    'reinserted': ['003106','003241','003419'],            # untorn, after reinsert
}
data = {}
for state, tss in GROUPS.items():
    data[state] = []
    for ts in tss:
        with open(os.path.join(LAB, 'f2_%s.bin' % ts), 'rb') as f:
            b = f.read()
        data[state].append(struct.unpack('<%dI' % (len(b)//4), b))

def h(v): return hashlib.sha256(struct.pack('<I', v)).hexdigest()[:6]
def names(v):
    return '|'.join(nm for bit, nm in FLAGBITS.items() if v & bit) or '-'

N = len(data['inserted'][0])
strict, partial = [], []
for i in range(N):
    mod, cons = {}, {}
    for state, arrs in data.items():
        vals = [a[i] for a in arrs]
        c = Counter(vals)
        v, cnt = c.most_common(1)[0]
        mod[state], cons[state] = v, cnt/len(vals)
    if mod['inserted'] == mod['reinserted'] == mod['removed']:
        continue
    if mod['inserted'] == mod['reinserted'] and mod['removed'] != mod['inserted']:
        rec = (i, mod, cons)
        (strict if all(cons[s] == 1.0 for s in cons) else partial).append(rec)

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

P('=== hw13 strict flip-flop scan (100%% within-state consistent, ins==rei!=rem): %d ===' % len(strict))
for i, mod, cons in strict:
    P('off 0x%05x (DDR 0x%06x): ins hash=%s flagbits=[%s] | rem hash=%s flagbits=[%s] | rei hash=%s flagbits=[%s]'
      % (i*4, 0x100000+i*4, h(mod['inserted']), names(mod['inserted'] & FLAGMASK),
         h(mod['removed']), names(mod['removed'] & FLAGMASK),
         h(mod['reinserted']), names(mod['reinserted'] & FLAGMASK)))
P()
P('=== partial flip-flop (ins==rei!=rem but within-state consistency <100%%): %d ===' % len(partial))
for i, mod, cons in partial[:30]:
    P('off 0x%05x: cons ins/rem/rei = %.2f/%.2f/%.2f' % (i*4, cons['inserted'], cons['removed'], cons['reinserted']))
P()
# cluster check around hw12 candidates 0xa8ec4..0xa90b0: how many dwords in 0xa8e00..0xa9200
# are state-stable at all (never change in any dump)?
allts = ['001814','001951','002126','002303','002439','002616','002752','002928','003106','003241','003419']
arrs = []
for ts in allts:
    with open(os.path.join(LAB, 'f2_%s.bin' % ts), 'rb') as f: b = f.read()
    arrs.append(struct.unpack('<%dI' % (len(b)//4), b))
lo, hi = 0xa8e00//4, 0xa9200//4
stable = sum(1 for i in range(lo, hi) if len({a[i] for a in arrs}) == 1)
P('region 0xa8e00-0xa9200: %d/%d dwords never change across all 11 dumps' % (stable, hi-lo))
with open(os.path.join(LAB, 'hw13_summary.txt'), 'w') as f: f.write('\n'.join(out) + '\n')
P('summary written to hw13_summary.txt')
