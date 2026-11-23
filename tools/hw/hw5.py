#!/usr/bin/env python3
# hw5: scan main-DDR heap region 0x200000-0x290000 for return-structure flag at +0x9C.
# Strong signature: only known flag bits, CARDID bit set, plus context (data region BCD density).
import sys, time, struct, os, hashlib
import usb.core, usb.util
LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hw5.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)
dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
for i in range(3):
    try: usb.util.claim_interface(dev, i)
    except Exception: pass
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
_page = [None]
def set_field(f):
    if _page[0] != f:
        cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8)); _page[0] = f
def D(ddr):   # main DDR read: field = page+1
    set_field((ddr >> 20) + 1)
    return R(APER + (ddr & 0xFFFFF))
MASK = 0x2|0x4|0x8|0x20|0x40|0x80|0x100|0x200|0x400|0x800|0x2000|0x4000|0x8000|0x10000|0x20000|0x40000|0x80000|0x100000|0x200000|0x400000|0x800000
def bcd_density(b):
    return sum(1 for x in b if (x >> 4) <= 9 and (x & 15) <= 9 and x != 0)
log('chip =', hex(R(MMR + 0x478)))
t0 = time.time(); n = 0; exact = []
for ddr in range(0x200000, 0x290000, 4):
    v = D(ddr); n += 1
    if v in (0x402000, 0xC02000, 0xC00000, 0xE02000, 0x40A000, 0xC0A000):
        exact.append((ddr, v)); log(f'EXACT flag-like at {ddr:#x}: {v:#x} (struct base {ddr-0x9c:#x})')
    elif v and (v & ~MASK) == 0 and (v & 0x400000) and (v & 0x2000):
        base = ddr - 0x9c
        data = b''.join(struct.pack('<I', D(base + o)) for o in range(0x2c, 0x40, 4))
        dens = bcd_density(data[:10])
        log(f'CAND base={base:#x} flag={v:#010x} +0x40={D(base+0x40):#x} bcd_density={dens}/10 data_sha12={hashlib.sha256(data).hexdigest()[:12]}')
log(f'scanned {n} dwords in {time.time()-t0:.0f}s; exact hits={len(exact)}')
