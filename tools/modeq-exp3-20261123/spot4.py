#!/usr/bin/env python3
# spot4: READ-ONLY probe for SECOND-ISSUE plan 2 (candidate-1 verification).
# Run against a HEALTHY STOCK boot during Stage B (session active, stock
# ECM/EMM jobs flowing). Reads the session object via the session-ptr
# global (VA 0x80226F68 = $gp-0x6C58 in the stream build; the SM reads the
# current job from session+0x1C, e.g. @0xA0124860/0xA012486C), walks the
# session slot table (session+0x1C + idx*4, bitmap at session+0x0C), and
# spot-reads live STOCK job descriptors:
#   job+0x18 (ctx as stored by stock submit), job+0x1C (prev link),
#   job+0x20 (next), job+0x08/+0x0C/+0x14, and *(ctx+0x14) (check-B gate
#   value when prev is the head: *(prev+8) == *(ctx+0x14)), plus the ctx
#   head links ctx+0x28 / ctx+0x2C for corroboration.
# VERDICT (branch gate for the KSEG1-fixed handler):
#   exit 0: at least one stock job observed with job+0x18 in KSEG1 form
#           (0xA0xxxxxx) -> candidate 1 corroborated, proceed.
#   exit 2: stock job(s) observed with job+0x18 in KSEG0 form (0x80xxxxxx)
#           -> candidate 1 collapses, STOP (do not load plan-1 material).
#   exit 3: no stock job observed in the sampling window (inconclusive).
# No writes except the aperture field selector (restored to 0 at the end)
# and the standard EP0x0e read requests. No doorbell, no reset, no Func.
import sys, time, struct
import usb.core, usb.util

def find():
    d = None
    for _ in range(100):
        d = usb.core.find(idVendor=0x0411, idProduct=0x0128)
        if d is not None: break
        time.sleep(0.1)
    assert d is not None, 'tuner not found'
    for i in range(3):
        try:
            if d.is_kernel_driver_active(i): d.detach_kernel_driver(i)
        except Exception: pass
    return d

dev = find()
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def aper_r(phys):
    set_field(phys >> 20); return R(APER + (phys & 0xFFFFF))
def phys_of(va): return va & 0x1FFFFFFF
def plausible(va):
    return va != 0 and (va >> 29) in (4, 5) and (va & 0x1FFFFFFF) < 0x3F00000 and (va & 3) == 0

print('chip', hex(R(MMR + 0x478)), 'MMR 0x3028', hex(R(MMR + 0x3028)))
sess_va = aper_r(0x226F68)   # *(0x80226F68): session-ptr global (stream build)
print(f'session-ptr *(0x80226F68) = {sess_va:#010x}')
if not plausible(sess_va):
    print('VERDICT: session pointer implausible -> INCONCLUSIVE (exit 3)')
    set_field(0); sys.exit(3)
sp = phys_of(sess_va)
hdr = {off: aper_r(sp + off) for off in (0x00, 0x04, 0x0C, 0x14, 0x18)}
print('session hdr:', {hex(k): hex(v) for k, v in hdr.items()},
      f'(bitmap={hdr[0x0C]:#x} mask={hdr[0x14]:#x} nextslot={hdr[0x18]:#x})')

DUR = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
seen = {}          # job_va -> dict of field snapshots (consistent reads only)
ctx_info = {}      # ctx_va -> (gate14, head_prev28, head_next2C)
t_end = time.time() + DUR
samples = 0
while time.time() < t_end:
    samples += 1
    bitmap = aper_r(sp + 0x0C)
    for idx in range(32):
        if idx and not (bitmap >> idx) & 1:
            continue
        job_va = aper_r(sp + 0x1C + idx * 4)
        if not plausible(job_va):
            continue
        jp = phys_of(job_va)
        f1 = {off: aper_r(jp + off) for off in (0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x2C)}
        f2 = {off: aper_r(jp + off) for off in (0x18, 0x1C, 0x20)}
        if (f1[0x18], f1[0x1C], f1[0x20]) != (f2[0x18], f2[0x1C], f2[0x20]):
            continue    # torn read (job changed mid-read); skip
        if not plausible(f1[0x18]):
            continue
        key = job_va
        if key not in seen:
            seen[key] = {'slot': idx, **f1}
            print(f'job @{job_va:#010x} slot{idx}: ' +
                  ' '.join(f'+{off:#04x}={f1[off]:#010x}' for off in (0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x2C)))
        ctx = f1[0x18]
        if ctx not in ctx_info:
            cp = phys_of(ctx)
            ctx_info[ctx] = (aper_r(cp + 0x14), aper_r(cp + 0x28), aper_r(cp + 0x2C))
            g, hp, hn = ctx_info[ctx]
            print(f'  ctx {ctx:#010x}: *(ctx+0x14)={g:#010x} (as signed {struct.unpack("<i", struct.pack("<I", g))[0]}), '
                  f'head prev ctx+0x28={hp:#010x}, head next ctx+0x2C={hn:#010x}')
    time.sleep(0.1)
set_field(0)
print(f'sampled {samples} rounds in {DUR:.0f}s; distinct jobs: {len(seen)}, distinct ctx: {len(ctx_info)}')
if not seen:
    print('VERDICT: no stock job observed -> INCONCLUSIVE (exit 3)')
    sys.exit(3)
forms = set()
for job_va, f in seen.items():
    ctx = f[0x18]
    form = 'KSEG1' if (ctx >> 28) == 0xA else ('KSEG0' if (ctx >> 28) == 0x8 else 'OTHER')
    forms.add(form)
    prev = f[0x1C]
    head_kseg1 = 0xA0000000 + (ctx & 0x1FFFFFFF) + 0xC
    head_kseg0 = 0x80000000 + (ctx & 0x1FFFFFFF) + 0xC
    rel = ('prev==head(KSEG1 form)' if prev == head_kseg1 else
           'prev==head(KSEG0 form)' if prev == head_kseg0 else
           'prev==ctx+0xC verbatim' if prev == (ctx + 0xC) & 0xFFFFFFFF else 'prev is a job/other')
    print(f'job {job_va:#010x}: ctx {ctx:#010x} [{form}], prev {prev:#010x} [{rel}], next {f[0x20]:#010x}')
print('alias forms observed:', forms)
if forms == {'KSEG1'}:
    print('VERDICT: stock jobs carry KSEG1 ctx -> candidate 1 CORROBORATED, proceed (exit 0)')
    sys.exit(0)
if 'KSEG0' in forms:
    print('VERDICT: stock jobs carry KSEG0 ctx -> candidate 1 COLLAPSES, STOP (exit 2)')
    sys.exit(2)
print('VERDICT: unexpected alias form -> treat as STOP (exit 2)')
sys.exit(2)
