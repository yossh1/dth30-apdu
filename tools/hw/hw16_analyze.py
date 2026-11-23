#!/usr/bin/env python3
# hw16_analyze: N-012 session-trigger diff + signature scan + RPCI response scan.
# Runs on 検証ホスト against lab files only (no USB access).
# Inputs:
#   preB_shared_071344.bin / preB_f2_071344.bin     (card IN, session NOT started)
#   postB_shared_071533.bin / postB_f2_071533.bin   (immediately after Stage B)
#   postB2_shared_071813.bin / postB2_f2_071813.bin (45 s after postB)
#   hw15_resp.jsonl (Stage B 'I' responses + 'Q' outcomes; raw stays on 検証ホスト)
#   replay_base.json.gz (expected values for mismatch recomputation)
# Signature (N-012 revised): base p (dword aligned, window >= 0xB8) is a candidate iff
#   (a) dword at p+0x9C in the POST dump is nonzero, uses ONLY corrected flag bits
#       (mask 0xC8E000), and sets at least one of INSERTED/CARDID/ACTIVATED;
#   (b) at least one data-field dword of the block layout changed pre->post
#       (offsets +0x14,+0x1C,+0x20,+0x24,+0x2C,+0x30..+0x3C,+0x64..+0x7C,+0x80,
#        +0xA0..+0xAC,+0xB0,+0xB4) AND the window contains >=1 changed dword;
#   (c) reproducibility is NOT tested here (needs a second trigger run) - reported as such.
# Data values are reported as sha12, never raw. Flag dwords (status bits) are reported raw.
import os, struct, hashlib, json, gzip
LAB = os.path.expanduser('~/dth30-lab')
FLAGMASK = 0xC8E000
FLAGBITS = [(0x2000,'INSERTED'),(0x4000,'REMOVED'),(0x8000,'ACTIVATED'),
            (0x80000,'EMM'),(0x800000,'VALID'),(0x400000,'CARDID')]
DATA_OFFS = [0x14,0x1C,0x20,0x24,0x2C] + list(range(0x30,0x40,4)) + \
            list(range(0x64,0x80,4)) + [0x80] + list(range(0xA0,0xB0,4)) + [0xB0,0xB4]
out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)
def proj(v):
    names = [n for b,n in FLAGBITS if v & b]
    rest = v & ~FLAGMASK
    return ('bits=' + ('|'.join(names) if names else 'none') +
            (' rest=%#x' % rest if rest else ' rest=0'))
def load(fn):
    with open(os.path.join(LAB, fn),'rb') as f: data = f.read()
    return struct.unpack('<%dI' % (len(data)//4), data[:len(data)//4*4]), data
def sha12(b): return hashlib.sha256(b).hexdigest()[:12]

def diff_list(a, b):
    return [i for i in range(min(len(a),len(b))) if a[i] != b[i]]

def sig_scan(tag, pre, post, chg):
    P(f'-- signature scan {tag}: changed dwords={len(chg)}')
    chgset = set(chg)
    cands = []
    n = len(post)
    for p in range(0, (n*4) - 0xB8, 4):
        flag = post[p//4 + 0x9C//4]
        if flag == 0 or (flag & ~FLAGMASK) != 0: continue
        if not (flag & (0x2000 | 0x400000 | 0x8000)): continue
        win = range(p//4, p//4 + 0xB8//4)
        if not any(i in chgset for i in win): continue
        dchg = [o for o in DATA_OFFS if (p+o)//4 in chgset]
        if not dchg: continue
        cands.append((p, flag, dchg))
    P(f'   candidates (a)+(b): {len(cands)}')
    for p, flag, dchg in cands[:40]:
        P(f'   base={p:#08x} flag(+0x9C)={flag:#010x} ({proj(flag)}) data-changed={[hex(o) for o in dchg]}')
    return cands

P('hw16 session-trigger analysis (N-012, N-009 back half)')
P('Stage B executed 07:15:21-07:15:22 JST; TS 20791296 B/10s sync 110592/110592 (session effect confirmed)')
for region, pre_f, post_f, post2_f in [
        ('shared(field0)', 'preB_shared_071344.bin', 'postB_shared_071533.bin', 'postB2_shared_071813.bin'),
        ('field2', 'preB_f2_071344.bin', 'postB_f2_071533.bin', 'postB2_f2_071813.bin')]:
    pre, _ = load(pre_f); post, _ = load(post_f); post2, _ = load(post2_f)
    chg1 = diff_list(pre, post); chg2 = diff_list(pre, post2); chg3 = diff_list(post, post2)
    P(f'== {region}: preB->postB changed={len(chg1)}  preB->postB2 changed={len(chg2)}  postB->postB2 changed={len(chg3)}')
    if region.startswith('shared'):
        for i in chg1:
            P(f'   shared off={i*4:#08x} preB={pre[i]:#010x} postB={post[i]:#010x} postB2={post2[i]:#010x}')
    sig_scan(region + ' postB', pre, post, chg1)
    sig_scan(region + ' postB2', pre, post2, chg2)

# stability re-check of the 8 hw15 field-2 insertion candidates in preB (3rd no-session sample)
P('== hw15 field-2 insertion candidates re-checked in preB_f2 (card IN, no session, ~07:13-07:15)')
f2pre, _ = load('preB_f2_071344.bin')
for off, ncv, cav in [(0x037fd8,0x0,0x039caef0),(0x037ff0,0x0,0x1),(0x0a8ec8,0x80239eb0,0x8400),
                      (0x0a9024,0x8012592c,0x8012580c),(0x0a9040,0xa0060270,0x0),(0x0a9044,0xa022f254,0x0),
                      (0x0a905c,0x80124ef8,0x80124354),(0x0a9064,0x0,0x802359b8)]:
    v = f2pre[off//4]
    P(f'   off={off:#08x} nocard-modal={ncv:#010x} card(cyc6/7)={cav:#010x} preB={v:#010x} -> ' +
      ('SAME as card cyc6/7' if v == cav else 'DIFFERS from card cyc6/7 (churn-like)'))

# RPCI response scan
P('== RPCI Stage B response scan (hw15_resp.jsonl; raw stays on 検証ホスト)')
ops = json.load(gzip.open(os.path.join(LAB, 'replay_base.json.gz'), 'rt'))
resp = [json.loads(l) for l in open(os.path.join(LAB, 'hw15_resp.jsonl'))]
iresp = [r for r in resp if r['kind'] == 'I']; qresp = [r for r in resp if r['kind'] == 'Q']
P(f'   I responses={len(iresp)}  Q polls={len(qresp)}  Q unmatched={sum(1 for r in qresp if not r["matched"])}')
mism = []
flag_hits = []; cardid_hits = []
from collections import Counter
dist = Counter()
for r in iresp:
    v = int.from_bytes(bytes.fromhex(r['hex']), 'little')
    dist[v] += 1
    exp = ops[r['op']][4]
    if exp is not None and r['hex'] != exp: mism.append(r['op'])
    if v != 0 and (v & ~FLAGMASK) == 0: flag_hits.append((r['op'], v))
    if v & 0x400000: cardid_hits.append((r['op'], v))
P(f'   recomputed mismatches={len(mism)} ops={mism[:60]}')
P(f'   distinct I-response values={len(dist)}; top: ' +
  ', '.join(f'{v:#010x}x{c}' for v, c in dist.most_common(8)))
P(f'   flag-semantics-only responses (nonzero, bits within 0xC8E000): {len(flag_hits)}')
for op, v in flag_hits[:40]: P(f'     op={op} value={v:#010x} ({proj(v)})')
P(f'   responses with CARDID bit (0x400000) set anywhere: {len(cardid_hits)}')
for op, v in cardid_hits[:40]: P(f'     op={op} value={v:#010x} ({proj(v)})')
# mismatch detail: expected vs actual as hashes + actual projection/zero-ness
P('   mismatch detail (sha12 of expected/actual; actual projection):')
for r in iresp:
    if r['op'] in set(mism):
        v = int.from_bytes(bytes.fromhex(r['hex']), 'little')
        exp = ops[r['op']][4]
        P(f'     op={r["op"]} exp_sha12={sha12(bytes.fromhex(exp))} act_sha12={sha12(bytes.fromhex(r["hex"]))} ' +
          f'act_is_zero={v==0} act_proj=({proj(v)})')
with open(os.path.join(LAB, 'hw16_summary.txt'), 'w') as f: f.write('\n'.join(out) + '\n')
print('summary written to ~/dth30-lab/hw16_summary.txt')
