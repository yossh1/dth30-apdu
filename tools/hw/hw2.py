#!/usr/bin/env python3
# hw2: verify DMA-IN correctness vs RPCI APER dword reads (firmware still running from hw1).
import sys, time, struct, hashlib, re, os
import usb.core, usb.util
LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hw2.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)
dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
dev.set_configuration(1)
for i in range(3):
    try: usb.util.claim_interface(dev, i)
    except Exception: pass
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def B(a, v):
    dev.write(0x0d, struct.pack('<HII', 0x001f, a, v), timeout=2000); dev.read(0x8d, 512, timeout=2000)
def set_page(p):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | ((p + 1) << 8))
def aper_r32(ddr):
    set_page(ddr >> 20); return R(APER + (ddr & 0xFFFFF))
def dma_in(count):
    B(0x1f4, APER); B(0x1f0, count | 0x40000000); B(0x1e0, 0x2); B(0x1e4, 1)
    return bytes(dev.read(0x81, count, timeout=15000))

log('chip =', hex(R(MMR + 0x478)), ' 0x3028 =', R(MMR + 0x3028))
ref = b''.join(struct.pack('<I', aper_r32(o)) for o in range(0, 64, 4))
log('APER DDR[0:64] =', ref.hex())
set_page(0)
d = dma_in(4096)
log('DMA  DDR[0:64] =', d[:64].hex())
log('DMA nonzero bytes in 4KB:', sum(1 for x in d if x), ' sha:', hashlib.sha256(d).hexdigest()[:12])
log('APER==DMA first64:', ref == d[:64])
# histogram over one full page via DMA: how many distinct byte values?
set_page(1); d1 = dma_in(0x100000)
log('page1 DMA: nonzero', sum(1 for x in d1 if x), 'distinct', len(set(d1)), 'sha', hashlib.sha256(d1).hexdigest()[:12])
ref1 = b''.join(struct.pack('<I', aper_r32(0x100000 + o)) for o in range(0, 64, 4))
log('page1 APER[0:64] =', ref1.hex())
log('page1 DMA [0:64] =', d1[:64].hex())
