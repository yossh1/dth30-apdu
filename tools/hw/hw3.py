#!/usr/bin/env python3
# hw3: scan shared RAM (aperture page 0) for the BCAS return-structure flag word at +0x9C.
# Signature: value uses only known flag bits (mask below) and has BCAS bits set.
import sys, time, struct, os
import usb.core, usb.util
LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hw3.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)
dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
try:
    for i in range(3): usb.util.claim_interface(dev, i)
    log('claimed without set_configuration')
except Exception as e:
    log('claim failed, set_configuration:', e)
    dev.set_configuration(1)
    for i in range(3):
        try: usb.util.claim_interface(dev, i)
        except Exception: pass
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
log('chip =', hex(R(MMR + 0x478)), ' 0x3028 =', R(MMR + 0x3028))
# aperture page := 0 (shared RAM)
cur = R(MMR + 0x43c); W(MMR + 0x43c, cur & 0xFFFF80FF)
log('page set to 0; 0x43c =', hex(R(MMR + 0x43c)))
MASK = 0x2|0x4|0x8|0x20|0x40|0x80|0x100|0x200|0x400|0x800|0x2000|0x4000|0x8000|0x10000|0x20000|0x40000|0x80000|0x100000|0x200000|0x400000|0x800000
BCAS = 0x2000|0x4000|0x8000|0x10000|0x20000|0x40000|0x80000|0x100000|0x200000|0x400000|0x800000
t0 = time.time(); n = 0; hits = []
END = 0x40000
for off in range(0, END, 4):
    v = R(APER + off); n += 1
    if v and (v & ~MASK) == 0 and (v & BCAS):
        hits.append((off, v))
        log(f'HIT off={off:#x} val={v:#010x} -> struct base would be {off-0x9c:#x}')
log(f'scanned {n} dwords in {time.time()-t0:.0f}s; hits={len(hits)}')
for off, v in hits:
    base = off - 0x9c
    if base < 0: continue
    f40 = R(APER + base + 0x40)
    log(f'cand base={base:#x} flag={v:#010x} struct+0x40={f40:#x}')
