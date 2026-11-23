#!/usr/bin/env python3
# hw6: walk the firmware com-list (shared area) -> per-entry struct -> +0x11C pointer -> +0x9C flag.
import sys, time, struct, os, hashlib
import usb.core, usb.util
LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hw6.log'), 'w', buffering=1)
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
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def S(off):   # shared area (field 0)
    set_field(0); return R(APER + off)
def D(ddr):   # main DDR
    set_field((ddr >> 20) + 1); return R(APER + (ddr & 0xFFFFF))
def rd_any(addr):
    # addr may be MIPS VA (0x80xxxxxx/0xA0xxxxxx) or phys; < 0x100000 treated as shared offset
    if addr >= 0x80000000: addr &= 0x1FFFFFFF
    if addr < 0x100000: return S(addr)
    return D(addr)
log('chip =', hex(R(MMR + 0x478)))
for f in (0, 1):
    set_field(f)
    cnt = R(APER + 0x110)
    log(f'field {f}: com-list count @0x110 = {cnt}')
set_field(1)
cnt = R(APER + 0x110)
if cnt is None or cnt > 64: cnt = 0
for i in range(cnt):
    base = 0x124 + 0x10 * i
    set_field(1); ptr = R(APER + base - 4)
    vals = []
    for k in (0, 4, 8):
        set_field(1); vals.append(R(APER + base + k))
    log(f'entry {i}: ptr={ptr if ptr is None else hex(ptr)} vals={[hex(v) for v in vals]}')
    if not ptr: continue
    try:
        p11c = rd_any(ptr + 0x11c)
        log(f'   *(ptr+0x11c) = {p11c:#x}')
        if p11c and (0x2000 <= (p11c & 0x1FFFFFFF) < 0x2000000):
            flag = rd_any(p11c + 0x9c)
            f40 = rd_any(p11c + 0x40)
            data = b''.join(struct.pack('<I', rd_any(p11c + o)) for o in range(0x2c, 0x40, 4))
            log(f'   retstruct flag(+0x9c)={flag:#010x} +0x40={f40:#x} data sha12={hashlib.sha256(data).hexdigest()[:12]}')
    except Exception as e:
        log('   walk err', e)
