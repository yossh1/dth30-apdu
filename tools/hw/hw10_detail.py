#!/usr/bin/env python3
# hw10: detail pass over hw8 dumps.
# - For every changed dword in mon (shared field0): transitions + value CLASS only
#   (zero / small / pointer-like / flag-like with named bits / other+popcount).
#   Raw values are printed ONLY for flag-like words (status bits, not contract data).
# - Full named-bit decomposition of the word at shared+0xF4 across all dumps.
# - Heap sanity: nonzero dword counts per dump (is the zero-change result vacuous?).
import os, re, struct
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

def load(prefix, size):
    out = []
    for fn in sorted(os.listdir(LAB)):
        m = re.match(prefix + r'_(\d{6})\.bin$', fn)
        if m and os.path.getsize(os.path.join(LAB, fn)) == size:
            data = open(os.path.join(LAB, fn), 'rb').read()
            out.append((m.group(1), struct.unpack('<%dI' % (len(data)//4), data)))
    out.sort()
    return out

def vclass(v):
    if v == 0: return 'zero'
    if v & ~FLAG_UNION == 0 and bin(v).count('1') <= 6: return 'flag-like'
    if 0x80000000 <= v < 0x81000000: return 'pointer-like(0x80xxxxxx)'
    if v < 0x100000: return 'small'
    return 'other'

def named(v):
    return [FLAG_BITS[b] for b in sorted(FLAG_BITS) if v & b]

mon = load('mon', 65536)
heap = load('heap', 589824)
print(f'mon dumps: {[t for t,_ in mon]}')
print(f'heap dumps: {[t for t,_ in heap]}')
print('heap nonzero dwords per dump:', [(t, sum(1 for v in c if v)) for t, c in heap])
print('mon nonzero dwords per dump:', [(t, sum(1 for v in c if v)) for t, c in mon])

cols = [c for _, c in mon]
n = len(cols)
print(f'-- changed dwords in mon (detail):')
for idx in range(len(cols[0])):
    vals = [c[idx] for c in cols]
    if len(set(vals)) == 1: continue
    tr = [i for i in range(1, n) if vals[i] != vals[i-1]]
    dv = []
    for v in dict.fromkeys(vals):
        cl = vclass(v)
        if cl == 'flag-like':
            dv.append(f'0x{v:08x}[{",".join(named(v))}]')
        else:
            dv.append(f'<{cl} popcount={bin(v).count("1")}>')
    mono = all(vals[i] >= vals[i-1] for i in range(1, n))
    print(f'  off=0x{idx*4:04x} (dw {idx}) transitions_at={tr} monotonic_nondec={mono} distinct={dv}')

print('-- word at shared+0xF4 (dw 61) per-dump named bits:')
for t, c in mon:
    v = c[61]
    print(f'   {t}: 0x{v:08x} bits={named(v)} other_bits=0x{v & ~FLAG_UNION:08x}')

print('-- offsets in 0x40..0x120 range (candidate struct base 0x58 windows): changed?')
base = 0x58
for rel_lo, rel_hi, label in [(0x2C,0x40,'dataA +0x2C..+0x40'),(0x64,0x7C,'dataB +0x64..+0x7C'),(0x80,0x80,'dataC +0x80'),(0x9C,0x9C,'flag +0x9C'),(0xA0,0xAC,'dataD +0xA0..+0xAC'),(0xB0,0xB4,'dataE +0xB0/+0xB4')]:
    offs = list(range(base+rel_lo, base+rel_hi+1, 4))
    ch = [f'0x{o:04x}' for o in offs if len({c[o//4] for _, c in mon}) > 1]
    nz = [f'0x{o:04x}' for o in offs if any(c[o//4] for _, c in mon)]
    print(f'   {label}: changed={ch or "none"} nonzero_in_any_dump={nz or "none"}')
