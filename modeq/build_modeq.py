#!/usr/bin/env python3
"""Build Mode Q handler (variant B) materials.

Assembles modeq_handler.asm with Keystone (MIPS32 LE), two passes:
pass 1 measures mq_handler length (= CB_OFF) and total code length;
pass 2 substitutes the real @@PEND_LO@@ / @@CB_LO@@ immediates.
Then patches the stream image (stub trampoline + cave code) and the
hw-series replay ops, verifying that diffs are confined to the
intended regions. Written by the parent agent after the investigator's
build step was stopped; addresses/design are the investigator's,
measured on the STREAM build (see modeq_handler.asm header).
"""
import gzip, json, struct, hashlib, copy, re, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.path.dirname(HERE)
CAVE_VA = 0xA011E238
CAVE_OFF = 0x1E238          # stream offset of the cave (shift 0 region)
CAVE_SIZE = 6596
STUB_OFF = 0x534D0          # stream offset of Func 0x04 stub body
STUB_VA = 0xA01534D0

from keystone import Ks, KS_ARCH_MIPS, KS_MODE_MIPS32, KS_MODE_LITTLE_ENDIAN
ks = Ks(KS_ARCH_MIPS, KS_MODE_MIPS32 | KS_MODE_LITTLE_ENDIAN)

def asm(code, va):
    # .set noreorder is REQUIRED: without it Keystone inserts its own nop
    # after every branch on top of the source's explicit delay-slot
    # instructions (19 extra nops in the handler), which among other
    # things pushed the worker-exit delay-slot addiu out of the delay
    # slot so it would never execute. The source manages all delay
    # slots explicitly. Faithfulness is verified below by comparing the
    # disassembled mnemonic sequence against the source sequence.
    enc, _ = ks.asm('.set noreorder\n' + code, va)
    return bytes(enc)

def check_sequence(code_bytes, va, src_part, name):
    from capstone import Cs, CS_ARCH_MIPS, CS_MODE_MIPS32, CS_MODE_LITTLE_ENDIAN as LE2
    md = Cs(CS_ARCH_MIPS, CS_MODE_MIPS32 | LE2)
    got = []
    for i in md.disasm(code_bytes, va):
        m = i.mnemonic
        got.append({'move': 'or'}.get(m, m))
    exp = []
    for ln in src_part.splitlines():
        ln = ln.strip()
        if not ln or ln.endswith(':'):
            continue
        m = ln.split()[0]
        exp.append(m)
    assert got == exp, f'{name}: sequence mismatch\n got {got}\n exp {exp}'
    print(f'{name}: sequence faithful ({len(exp)} instructions)')

def load_source():
    src = open(os.path.join(HERE, 'modeq_handler.asm')).read()
    lines = []
    for ln in src.splitlines():
        ln = ln.split(';', 1)[0].rstrip()
        if ln.strip():
            lines.append(ln)
    code = '\n'.join(lines)
    # split at the callback label: handler part | callback part
    idx = code.index('mq_callback:')
    return code[:idx], code[idx:]

def build_code(pend_lo, cb_lo):
    hsrc, csrc = load_source()
    def sgn(v):  # addiu immediates must be signed, else Keystone expands via $at
        return str(v - 0x10000 if v >= 0x8000 else v)
    def sub(s):
        return s.replace('@@PEND_LO@@', sgn(pend_lo)).replace('@@CB_LO@@', sgn(cb_lo))
    handler = asm(sub(hsrc), CAVE_VA)
    cb = asm(sub(csrc), CAVE_VA + len(handler))
    return handler, cb

# ---- pass 1: measure with dummy immediates (sizes are immediate-independent)
h1, c1 = build_code(0, 0)
CB_OFF = len(h1)
CODE_LEN = CB_OFF + len(c1)
DATA_OFF = (CODE_LEN + 3) & ~3
assert CODE_LEN <= CAVE_SIZE - 8, f'code too big: {CODE_LEN}'
pend_va = CAVE_VA + DATA_OFF
cb_va = CAVE_VA + CB_OFF
PEND_LO = pend_va & 0xFFFF
CB_LO = cb_va & 0xFFFF
# the source forms addresses as lui 0xA012 / addiu lo (sign-extended):
assert (0xA0120000 + (PEND_LO - 0x10000 if PEND_LO >= 0x8000 else PEND_LO)) & 0xFFFFFFFF == pend_va
assert (0xA0120000 + (CB_LO - 0x10000 if CB_LO >= 0x8000 else CB_LO)) & 0xFFFFFFFF == cb_va

# ---- pass 2: real immediates; sizes must not change
h2, c2 = build_code(PEND_LO, CB_LO)
assert len(h2) == CB_OFF and len(c2) == len(c1), 'size changed between passes'
code = h2 + c2
_hsrc, _csrc = load_source()
check_sequence(h2, CAVE_VA, _hsrc, 'handler')
check_sequence(c2, cb_va, _csrc, 'callback')
print(f'handler {CB_OFF} B, callback {len(c2)} B, code total {CODE_LEN} B, DATA_OFF {DATA_OFF:#x}')
print(f'CB va {cb_va:#010x}, PEND va {pend_va:#010x}')

# ---- trampoline at stub VA: j cave; nop  (8 bytes of the 0xCC stub)
# Keystone appends extra padding nops after a trailing branch; the first
# 8 bytes are the exact j word + delay-slot nop (j word cross-checked
# against the manual encoding below).
tramp = asm('j 0xA011E238\nnop', STUB_VA)[:8]
_jword = (0x02 << 26) | ((CAVE_VA >> 2) & 0x3FFFFFF)
assert tramp[:4] == struct.pack('<I', _jword) and tramp[4:] == bytes(4)
print('trampoline:', tramp.hex())

# ---- patch the stream image
base_stream = open(os.path.join(HERE, 'work', 'stream_base.bin'), 'rb').read()
assert len(base_stream) > CAVE_OFF + CAVE_SIZE
assert base_stream[CAVE_OFF:CAVE_OFF + CAVE_SIZE] == bytes(CAVE_SIZE), 'cave not zero in base stream'
patched = bytearray(base_stream)
patched[STUB_OFF:STUB_OFF + 8] = tramp
patched[CAVE_OFF:CAVE_OFF + CODE_LEN] = code
# pending area stays zero (idle state)
diff_ranges = []
i = 0
while i < len(base_stream):
    if base_stream[i] != patched[i]:
        j = i
        while j < len(base_stream) and base_stream[j] != patched[j]:
            j += 1
        diff_ranges.append((i, j))
        i = j
    else:
        i += 1
allowed = [(STUB_OFF, STUB_OFF + 8), (CAVE_OFF, CAVE_OFF + CODE_LEN)]
assert all(any(a <= s and e <= b for a, b in allowed) for s, e in diff_ranges), diff_ranges
print('stream diff ranges:', [(hex(s), hex(e)) for s, e in diff_ranges])
open(os.path.join(HERE, 'stream_modeq.bin'), 'wb').write(patched)

# ---- map replay ops to stream offsets by payload matching, then patch ops
base_ops = json.load(gzip.open(os.path.join(PROJ, 'artifacts', 'phase2-20261122', 'replay_base.json.gz'), 'rt'))
def op_stream_off(op):
    if len(op) < 4:
        return None
    try:
        p = bytes.fromhex(op[3])
    except Exception:
        return None
    if len(p) < 256:
        return None
    off = base_stream.find(p[:64])
    if off < 0 or base_stream[off:off + len(p)] != p:
        return None
    return off
mapping = {}
for k, op in enumerate(base_ops):
    o = op_stream_off(op)
    if o is not None:
        mapping[k] = o
print('mapped ops:', {k: hex(v) for k, v in mapping.items() if v <= CAVE_OFF < v + 10**7 or v <= STUB_OFF < v + 10**7})

def patch_op(ops, stream_off, data):
    for k, o in mapping.items():
        p_len = len(bytes.fromhex(ops[k][3]))
        if o <= stream_off and stream_off + len(data) <= o + p_len:
            b = bytearray(bytes.fromhex(ops[k][3]))
            b[stream_off - o: stream_off - o + len(data)] = data
            ops[k][3] = b.hex()
            return k, stream_off - o
    raise SystemExit(f'no op covers stream {stream_off:#x}')

modeq_ops = copy.deepcopy(base_ops)
k1, l1 = patch_op(modeq_ops, STUB_OFF, tramp)
k2, l2 = patch_op(modeq_ops, CAVE_OFF, code)
print(f'trampoline -> ops[{k1}] local {l1:#x}; handler -> ops[{k2}] local {l2:#x}')

def diff_ops(a, b):
    out = []
    for k, (x, y) in enumerate(zip(a, b)):
        if x != y:
            xb, yb = bytes.fromhex(x[3]), bytes.fromhex(y[3])
            assert len(xb) == len(yb) and x[:3] == y[:3], k
            ds = [i for i in range(len(xb)) if xb[i] != yb[i]]
            out.append((k, ds))
    return out
d = diff_ops(base_ops, modeq_ops)
total = sum(len(ds) for _, ds in d)
print('replay diff:', [(k, len(ds), hex(ds[0]), hex(ds[-1])) for k, ds in d], 'total bytes', total)
exp = {k1: (l1, l1 + 8), k2: (l2, l2 + CODE_LEN)}
for k, ds in d:
    a, b = exp[k]
    assert all(a <= i < b for i in ds), (k, ds[:5])
with gzip.open(os.path.join(HERE, 'replay_modeq.json.gz'), 'wt') as f:
    json.dump(modeq_ops, f)

for fn in ('stream_modeq.bin', 'replay_modeq.json.gz'):
    p = os.path.join(HERE, fn)
    print(fn, hashlib.sha256(open(p, 'rb').read()).hexdigest(), os.path.getsize(p))
print('BUILD OK')
