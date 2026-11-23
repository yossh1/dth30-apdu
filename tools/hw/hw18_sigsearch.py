#!/usr/bin/env python3
# hw18: N-018 - signature search for the video-channel object (ctx/obj of routine
# 0xa01be144) in ALL existing dumps on 検証ホスト (read-only; no new device access).
#
# Signatures (from artifacts/n017_trace.md sec.3/6 and excerpts B):
#   - record tag words written via cursor obj+0x334 into a DDR record buffer:
#     exact tags of routine 0xa01be144: 0x731c00c0 0x731000c0 0x730c00c0
#     0x728400c0 0x728800c0 0x730800c0 0x732000c0 0x72d000c0
#     family: (v & 0xFFFF) == 0x00C0 and 0x7200 <= (v >> 16) < 0x7400
#   - obj internal relations at obj base X:
#       dword[X+0xFF0] = final cursor - 4   (VA, address value)
#       dword[X+0x334] = cursor             (VA, >= FF0+4, same buffer)
#       dword[X+0xFF8] = dword[X+0x110]     (copy relation)
#       dword[X+0x1000] = mode value        (small)
#       dword[X+0x8C] <= 0x780, dword[X+0x90] <= 0x440 (dimension checks)
#   - H-022 prediction: ctx phys = 0x135BF8 -> obj at field2 offset 0x37000,
#     ctx at field2 offset 0x35BF8. Direct probe of that location included.
#
# Dumps (lab dir):
#   field 2 (phys base 0x100000): f2_*.bin (boot1), f3_*.bin / pre_f2 / preB_f2 /
#     postB_f2 / postB2_f2 (boot2)
#   heap field 3 (phys base 0x200000, 0x90000 window): heap_*.bin (boot1)
#   shared field 0 (phys base 0, 64KB): mon_*.bin mon2_*.bin (boot1),
#     mon3_*.bin (boot2), pre_shared / preB_shared / postB_shared /
#     postB2_shared / shared_A_bootonly / shared_B_session (boot1 *_shared A/B,
#     boot2 pre/post)
# Privacy: only offsets, tag values, and signature-field values are printed.
# Address-like and small values raw; other dwords as sha12+class (hw17 policy).
# Record payload dwords are never printed.
import os, struct, hashlib, glob
from collections import defaultdict

LAB = os.path.expanduser('~/dth30-lab')
EXACT_TAGS = {0x731c00c0, 0x731000c0, 0x730c00c0, 0x728400c0,
              0x728800c0, 0x730800c0, 0x732000c0, 0x72d000c0}

def is_tag_family(v):
    return (v & 0xFFFF) == 0x00C0 and 0x7200 <= (v >> 16) < 0x7400

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
        return 0  # shared field 0
    if fn.startswith(('f2_', 'f3_', 'pre_f2', 'preB_f2', 'postB_f2', 'postB2_f2')):
        return 0x100000
    if fn.startswith('heap_'):
        return 0x200000
    return 0  # mon_* = shared field 0

def boot_of(fn):
    if fn.startswith(('f3_', 'mon3_', 'pre_f2', 'pre_shared', 'preB_', 'postB')):
        return 'boot2'
    return 'boot1'

files = sorted(os.path.basename(p) for p in glob.glob(os.path.join(LAB, '*.bin')))
dumps = {}   # fn -> (base, boot, dwords list)
for fn in files:
    with open(os.path.join(LAB, fn), 'rb') as f:
        raw = f.read()
    d = struct.unpack('<%dI' % (len(raw) // 4), raw[:len(raw) // 4 * 4])
    dumps[fn] = (field_base(fn), boot_of(fn), d)

out = []
def P(*a):
    s = ' '.join(str(x) for x in a); out.append(s); print(s)

P('hw18 signature search (N-018): dumps scanned = %d' % len(dumps))
P('  field2: %d, heap(field3): %d, shared(field0): %d' % (
    sum(1 for v in dumps.values() if v[0] == 0x100000),
    sum(1 for v in dumps.values() if v[0] == 0x200000),
    sum(1 for v in dumps.values() if v[0] == 0)))

# ---------- Phase 1: tag census ----------
P()
P('== phase 1: record-tag census per dump ==')
clusters = defaultdict(list)   # boot -> list of (phys_lo, phys_hi, fn, n_hits)
tot_exact = tot_family = 0
for fn in files:
    base, boot, d = dumps[fn]
    exact_hits = [i * 4 for i, v in enumerate(d) if v in EXACT_TAGS]
    fam_hits = [i * 4 for i, v in enumerate(d) if is_tag_family(v)]
    tot_exact += len(exact_hits); tot_family += len(fam_hits)
    if exact_hits or fam_hits:
        P('%s (base %#x, %s): exact=%d family=%d' % (fn, base, boot, len(exact_hits), len(fam_hits)))
        # cluster family hits: chain offsets <= 0x40 apart
        offs = sorted(set(fam_hits))
        if offs:
            start = prev = offs[0]; cnt = 1
            for o in offs[1:]:
                if o - prev <= 0x40:
                    prev = o; cnt += 1
                else:
                    clusters[boot].append((base + start, base + prev + 4, fn, cnt))
                    start = prev = o; cnt = 1
            clusters[boot].append((base + start, base + prev + 4, fn, cnt))
P('totals: exact tag hits = %d, family hits = %d' % (tot_exact, tot_family))
for boot in ('boot1', 'boot2'):
    cl = clusters.get(boot, [])
    P('%s tag clusters (phys ranges): %d' % (boot, len(cl)))
    for lo, hi, fn, cnt in cl:
        P('   phys [%#x..%#x) in %s (family hits in cluster: %d)' % (lo, hi, fn, cnt))

def in_cluster(boot, phys, slack_lo=0x10, slack_hi=0x2000):
    for lo, hi, fn, cnt in clusters.get(boot, []):
        if lo - slack_lo <= phys < hi + slack_hi:
            return True
    return False

# ---------- Phase 2: object relation scan ----------
P()
P('== phase 2: obj relation scan (FF8==+0x110 copy, FF0/334 VA pair, +0x1000 small) ==')
cands = []
for fn in files:
    base, boot, d = dumps[fn]
    n = len(d)
    for i in range(n):
        v = d[i]
        if (v >> 28) not in (0x8, 0xA):
            continue
        X = i * 4 - 0xFF0           # candidate obj base if d[i] is obj+0xFF0
        if X < 0 or X + 0x1008 > n * 4:
            continue
        xi = X // 4
        ff0 = v; bp = ff0 & 0x1FFFFFFF
        cur = d[xi + 0x334 // 4]
        if (cur >> 28) not in (0x8, 0xA):
            continue
        cp = cur & 0x1FFFFFFF
        if not (4 <= cp - (bp + 4) + 4 <= 0x2004):   # cp-bp in [4, 0x2004]
            continue
        if (cp - bp) % 4 != 0:
            continue
        if d[xi + 0xFF8 // 4] != d[xi + 0x110 // 4]:
            continue
        mode = d[xi + 0x1000 // 4]
        if mode >= 0x10:
            continue
        dim8c = d[xi + 0x8C // 4]; dim90 = d[xi + 0x90 // 4]
        tagref = in_cluster(boot, bp + 4) and in_cluster(boot, cp)
        cands.append((fn, base, boot, X, ff0, cur, mode, dim8c, dim90, tagref))
P('candidates: %d' % len(cands))
for fn, base, boot, X, ff0, cur, mode, d8c, d90, tagref in cands:
    P('   %s (%s) obj_off=%#x -> ctx phys = %#x | +0xFF0=%s +0x334=%s +0x1000=%#x '
      '+0x8C=%#x +0x90=%#x | pointers-into-tag-cluster=%s'
      % (fn, boot, X, base + X - 0x1408, fmt(ff0), fmt(cur), mode, d8c, d90, tagref))

# ---------- Phase 3: direct probe at H-022 predicted location ----------
P()
P('== phase 3: direct probe, predicted obj base = field2 offset 0x37000 (ctx 0x35BF8) ==')
PROBE = [(0x110, '+0x110'), (0x334, '+0x334'), (0x808, '+0x808'), (0x8C, '+0x8C'),
         (0x90, '+0x90'), (0xFF0, '+0xFF0'), (0xFF8, '+0xFF8'), (0x1000, '+0x1000'),
         (0x7A1C, 'ctx+0x8E24 (obj+0x7A1C, init=1)')]
for fn in files:
    base, boot, d = dumps[fn]
    if base != 0x100000 or len(d) * 4 < 0x38008:
        continue
    xi = 0x37000 // 4
    cells = []
    for off, name in PROBE:
        cells.append('%s=%s' % (name, fmt(d[xi + off // 4])))
    eq = 'FF8==+0x110' if d[xi + 0xFF8 // 4] == d[xi + 0x110 // 4] else 'FF8!=+0x110'
    P('%s (%s): %s | %s' % (fn, boot, ' '.join(cells), eq))

with open(os.path.join(LAB, 'hw18_summary.txt'), 'w') as f:
    f.write('\n'.join(out) + '\n')
P()
P('summary written to hw18_summary.txt')
