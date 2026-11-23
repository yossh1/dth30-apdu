#!/usr/bin/env python3
# hw15_analyze: N-009 insertion-effect analysis (file-based, no USB access).
# Compares hw14 dumps on 検証ホスト:
#   NOCARD (card removed, booted, no session):
#     pre_shared_065716.bin / pre_f2_065716.bin + mon3/f3 cycles 0-4 (065905..070530)
#     + mon3 cycle 5 (070706; its mon3 read finished ~07:07:12, before insertion 07:08:32.
#       cycle 5 f3 is torn by the insertion and is EXCLUDED)
#   CARD-NOSESSION (card inserted 07:08:32, session NOT started):
#     mon3/f3 cycles 6-7 (070842, 071022), both fully post-insertion.
# Method (hw13-style strict): a dword is an insertion-correlated candidate iff
#   all NOCARD dumps agree on one value, all CARD dumps agree on one value, and they differ.
# Churn dwords (disagreement inside a state) are counted separately as noise.
# Flag projection uses the corrected +0x9C semantics mask:
#   INSERTED 0x2000 / REMOVED 0x4000 / ACTIVATED 0x8000 / EMM 0x80000 /
#   VALID 0x800000 / CARDID 0x400000  -> mask 0xC8E000.
# Data-like changed regions (digit runs) are reported as len+sha12 only, never raw.
import os, sys, struct, hashlib, re
LAB = os.path.expanduser('~/dth30-lab')
FLAGMASK = 0xC8E000
FLAGBITS = [(0x2000,'INSERTED'),(0x4000,'REMOVED'),(0x8000,'ACTIVATED'),
            (0x80000,'EMM'),(0x800000,'VALID'),(0x400000,'CARDID')]
def proj(v):
    if v == 0: return 'zero'
    names = [n for b,n in FLAGBITS if v & b]
    rest = v & ~FLAGMASK
    return ('bits=' + ('|'.join(names) if names else 'none') +
            (' rest=%#x' % rest if rest else ' rest=0'))
def load(fn):
    with open(os.path.join(LAB, fn),'rb') as f: data = f.read()
    return struct.unpack('<%dI' % (len(data)//4), data[:len(data)//4*4])
def modal(vals):
    s = set(vals)
    return vals[0] if len(s) == 1 else None
out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

P('hw15 insertion-effect analysis (N-009 front half)')
P('states: NOCARD = pre 065716 + cycles 0-4 (+mon3 cycle5); CARD-NOSESSION = cycles 6-7 (post-insertion 07:08:32, no session)')
def analyze2(tag, nocard_files, card_files):
    P(f'== {tag}')
    nc = [load(f) for f in nocard_files]; ca = [load(f) for f in card_files]
    n = min(len(d) for d in nc + ca)
    strict = []; churn = 0
    for i in range(n):
        ncv = modal([d[i] for d in nc]); cav = modal([d[i] for d in ca])
        if ncv is None or cav is None:
            if (ncv is None) != (cav is None): churn += 1
            continue
        if ncv != cav: strict.append((i*4, ncv, cav))
    P(f'   dwords={n} strict-state-diff={len(strict)} one-side-churn={churn}')
    for off, ncv, cav in strict:
        P(f'   off={off:#08x} nocard={ncv:#010x} ({proj(ncv)}) card={cav:#010x} ({proj(cav)})')
    return strict

nc_mon = ['pre_shared_065716.bin','mon3_065905.bin','mon3_070041.bin','mon3_070217.bin',
          'mon3_070354.bin','mon3_070530.bin','mon3_070706.bin']
ca_mon = ['mon3_070842.bin','mon3_071022.bin']
nc_f3  = ['pre_f2_065716.bin','f3_065905.bin','f3_070041.bin','f3_070217.bin',
          'f3_070354.bin','f3_070530.bin']
ca_f3  = ['f3_070842.bin','f3_071022.bin']
analyze2('shared (field 0, 64KB)', nc_mon, ca_mon)
analyze2('field 2 (1MB)', nc_f3, ca_f3)

# MMR snapshots from hw14.log: parse per-cycle, check uniformity across insertion boundary
P('== MMR snapshots (hw14.log)')
snaps = []
for line in open(os.path.join(LAB,'hw14.log')):
    m = re.search(r'cycle (\d+) start (\d+) mmr (.*)', line)
    if m: snaps.append((int(m.group(1)), m.group(2), m.group(3).strip()))
uniq = set(s for _,_,s in snaps)
P(f'   cycles parsed={len(snaps)} unique snapshots={len(uniq)}')
for u in uniq: P('   ' + u)
cyc = {c: t for c, t, _ in snaps}
P(f'   cycle starts: {cyc}')

with open(os.path.join(LAB,'hw15_summary.txt'),'w') as f: f.write('\n'.join(out) + '\n')
print('summary written to ~/dth30-lab/hw15_summary.txt')
