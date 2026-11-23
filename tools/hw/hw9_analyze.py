#!/usr/bin/env python3
# hw9: analysis of hw8 pull/insert differential dumps (N-005 localization + N-003 prep).
# Runs on 検証ホスト in ~/dth30-lab/. Raw dumps stay on 検証ホスト (may contain contract
# info). This script prints ONLY: offsets, bit patterns, transition indices, change
# classifications and changed-byte counts. Data-region raw values are never printed.
import os, re, struct, sys
from collections import Counter

LAB = os.path.expanduser('~/dth30-lab')

FLAG_BITS = {
    0x000002: 'VIDEO_BLACK_OUT', 0x000004: 'AUDIO_BLACK_OUT', 0x000008: 'YUV_PCM_NOT_SYNC',
    0x000020: 'CABLECARD_REMOVED', 0x000040: 'CABLECARD_TIMEOUT', 0x000080: 'CABLECARD_ACCESS_ERROR',
    0x000100: 'CABLECARD_OUTPUT', 0x000200: 'CABLECARD_OUTPUT_EXT', 0x000400: 'CABLECARD_MORE_DATA',
    0x000800: 'CABLECARD_CP_CARD_CERT_ERROR',
    0x002000: 'BCASCARD_INSERTED', 0x004000: 'BCASCARD_REMOVED', 0x008000: 'BCASCARD_ACTIVATED',
    0x010000: 'BCASCARD_EMM_IDV_MSG', 0x020000: 'BCASCARD_EMM_COM_MSG', 0x040000: 'BCASCARD_AUTODISPLAY_MSG',
    0x080000: 'BCASCARD_EMM_COMMAND', 0x100000: 'BCASCARD_SDT_CONTRACT', 0x200000: 'BCASCARD_EIT_CONTRACT',
    0x400000: 'BCASCARD_CARDID', 0x800000: 'BCASCARD_VALID',
}
FLAG_UNION = 0
for b in FLAG_BITS: FLAG_UNION |= b
KEY_BITS = [0x002000, 0x004000, 0x008000, 0x400000, 0x800000, 0x000020]

def load_series(prefix, expect_size, base_addr):
    files = []
    for fn in sorted(os.listdir(LAB)):
        m = re.match(prefix + r'_(\d{6})\.bin$', fn)
        if m and os.path.getsize(os.path.join(LAB, fn)) == expect_size:
            files.append((m.group(1), os.path.join(LAB, fn)))
    files.sort()
    stamps = [t for t, _ in files]
    cols = []  # per-dump list of dwords
    for _, p in files:
        data = open(p, 'rb').read()
        cols.append(struct.unpack('<%dI' % (len(data) // 4), data))
    return stamps, cols

def analyze(name, stamps, cols, base_addr):
    n = len(cols)
    ndw = len(cols[0])
    print(f'== {name}: {n} dumps {stamps} base=0x{base_addr:08x} dwords={ndw}')
    # per-transition changed counts
    trans_counts = []
    for i in range(1, n):
        c = sum(1 for a, b in zip(cols[i-1], cols[i]) if a != b)
        trans_counts.append(c)
    print(f'  changed-dwords per transition: {trans_counts}')
    changed = {}  # dw_index -> list of values
    for idx in range(ndw):
        vals = [c[idx] for c in cols]
        if len(set(vals)) > 1:
            changed[idx] = vals
    print(f'  changed offsets total: {len(changed)}')
    cls = Counter()
    flipflops = []   # A->B->A exactly 2 transitions, returns to start
    oneway = []
    for idx, vals in changed.items():
        tr = [i for i in range(1, n) if vals[i] != vals[i-1]]
        if all(vals[i] > vals[i-1] for i in range(1, n) if vals[i] != vals[i-1]) and len(tr) >= 3:
            cls['monotonic-counter-like'] += 1
        elif len(tr) == 2 and vals[-1] == vals[0]:
            cls['flip-flop(2 transitions, returns)'] += 1
            flipflops.append((idx, vals, tr))
        elif len(tr) == 1:
            cls['one-way(1 transition)'] += 1
            oneway.append((idx, vals, tr))
        elif len(tr) == 2:
            cls['2 transitions, no return'] += 1
        else:
            cls[f'chatter({len(tr)} transitions)'] += 1
    print(f'  classification: {dict(cls)}')
    # --- flag hunt (a): bit-pattern of key bits across dumps
    print(f'  -- key-bit pattern hits (bit set in a contiguous proper subset, or clear in one):')
    hits_a = 0
    for idx in range(ndw):
        vals = [c[idx] for c in cols]
        for b in KEY_BITS:
            pat = ''.join('1' if (v & b) else '0' for v in vals)
            s = set(pat)
            if s == {'0', '1'}:
                # contiguous block of 1s or of 0s (proper subset)
                ones = [i for i, ch in enumerate(pat) if ch == '1']
                zeros = [i for i, ch in enumerate(pat) if ch == '0']
                def contig(ix): return ix == list(range(ix[0], ix[-1] + 1))
                if contig(ones) or contig(zeros):
                    print(f'     off=0x{base_addr + idx*4:08x} (dw {idx}) bit 0x{b:06x} {FLAG_BITS[b]} pattern={pat}')
                    hits_a += 1
    if not hits_a: print('     (none)')
    # --- flag hunt (b): exactly-2-values offsets whose XOR uses only known flag bits
    print(f'  -- 2-value offsets with XOR subset of flag bits:')
    hits_b = 0
    for idx, vals in changed.items():
        dv = set(vals)
        if len(dv) == 2:
            x = dv.pop() ^ dv.pop()
            if x and (x & ~FLAG_UNION) == 0:
                names = [FLAG_BITS[b] for b in FLAG_BITS if x & b]
                tr = [i for i in range(1, n) if vals[i] != vals[i-1]]
                print(f'     off=0x{base_addr + idx*4:08x} (dw {idx}) xor=0x{x:06x} bits={names} transitions_at={tr}')
                hits_b += 1
    if not hits_b: print('     (none)')
    # --- all flip-flops with their XOR bit decomposition (values of flag-like words only)
    print(f'  -- flip-flop offsets (A->B->A): {len(flipflops)}')
    for idx, vals, tr in flipflops:
        dv = list(set(vals))
        x = dv[0] ^ dv[1] if len(dv) == 2 else None
        xdesc = f'xor=0x{x:06x}' if x is not None else f'{len(dv)} distinct values'
        print(f'     off=0x{base_addr + idx*4:08x} (dw {idx}) transitions_at={tr} {xdesc}')
    print(f'  -- one-way offsets: {len(oneway)} (offsets only)')
    for idx, vals, tr in oneway:
        print(f'     off=0x{base_addr + idx*4:08x} (dw {idx}) transition_at={tr}')
    return changed

def data_corr(changed, flag_dw, base_addr, ndw):
    # data windows relative to flag dword (flag at struct+0x9C => dw offset 0x27 from struct base)
    rel = []
    for lo, hi in [(-0x70, -0x5C), (-0x38, -0x20), (-0x1C, -0x1C), (0x04, 0x10), (0x14, 0x14), (0x18, 0x18)]:
        rel.append((lo, hi))
    print(f'  data-region correlation for flag dw {flag_dw} (addr 0x{base_addr + flag_dw*4:08x}):')
    for lo, hi in rel:
        cnt = 0; tot = 0
        for byteoff in range(lo, hi + 1, 4):
            dw = flag_dw + byteoff // 4
            tot += 4
            if dw in changed: cnt += 4
        print(f'    window {lo:+#x}..{hi:+#x}: {cnt}/{tot} bytes changed across the pull/insert cycle')

stamps_m, cols_m = load_series('mon', 65536, 0x00000000)
stamps_h, cols_h = load_series('heap', 589824, 0x00200000)
common = [t for t in stamps_m if t in stamps_h]
print(f'mon stamps={stamps_m}')
print(f'heap stamps={stamps_h}')
print(f'common complete pairs={common}')
# restrict both to common stamps for aligned analysis
def restrict(stamps, cols, keep):
    ix = [stamps.index(t) for t in keep]
    return [cols[i] for i in ix]
cols_m2 = restrict(stamps_m, cols_m, common)
cols_h2 = restrict(stamps_h, cols_h, common)
ch_m = analyze('mon (shared field0)', common, cols_m2, 0x00000000)
ch_h = analyze('heap (DDR 0x200000-0x290000)', common, cols_h2, 0x00200000)
