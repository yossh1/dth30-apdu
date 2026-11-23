#!/usr/bin/env python3
# hw4: read +0x9C flag & neighbours for the known Func param blocks in shared RAM (page 0),
# plus a redacted dump of block heads. No set_configuration (device state from hw1 persists).
import sys, time, struct, os, hashlib
import usb.core, usb.util
LOGF = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hw4.log'), 'w', buffering=1)
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
cur = R(MMR + 0x43c); W(MMR + 0x43c, cur & 0xFFFF80FF)   # page 0
def S(off): return R(APER + off)
log('chip =', hex(R(MMR + 0x478)))
for base in (0x1840, 0x3c00, 0xcb00):
    flag = S(base + 0x9c); f40 = S(base + 0x40)
    data = b''.join(struct.pack('<I', S(base + o)) for o in range(0x2c, 0x40, 4))
    log(f'block {base:#x}: +0x9c={flag:#010x} +0x40={f40:#x} data+0x2c..40 sha12={hashlib.sha256(data).hexdigest()[:12]}')
    head = b''.join(struct.pack('<I', S(base + o)) for o in range(0, 0x30, 4))
    log(f'  head dwords: {[hex(x) for x in struct.unpack("<12I", head)]}')
# periodic re-read of the Func19 block flag (0x1840 was reused by 0x19 upload)
log('periodic flag @0x1840+0x9c, 6 x 2s:')
for i in range(6):
    log(f'  [{i}] {S(0x1840 + 0x9c):#010x}')
    time.sleep(2)
