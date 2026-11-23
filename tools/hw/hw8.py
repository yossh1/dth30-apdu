#!/usr/bin/env python3
# hw8: card pull/insert differential monitor (for N-003 + N-005 localization).
# Assumes firmware is already booted + session open (run hw1 stages A+B first if not).
# Every 5 s, dumps: shared region (field 0, 0..0x10000) and DDR heap (0x200000..0x290000)
# into ~/dth30-lab/mon_<timestamp>.bin / heap_<timestamp>.bin . Runs ~30 min.
# The user pulls the B-CAS card, waits ~20 s, re-inserts it, waits ~20 s, within the window.
# Analysis (separate step): diff consecutive dumps; the return structure is where a
# flag word flips INSERTED(0x2000) <-> REMOVED(0x4000) and the data region changes.
import sys, time, struct, os
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
LOGF = open(os.path.join(HERE, 'hw8.log'), 'w', buffering=1)
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
def dump(path, field, base, size):
    set_field(field)
    with open(path, 'wb') as fo:
        for off in range(0, size, 4):
            fo.write(struct.pack('<I', R(APER + base + off)))
log('chip =', hex(R(MMR + 0x478)), ' monitor start')
for n in range(360):
    ts = time.strftime('%H%M%S')
    dump(os.path.join(HERE, f'mon_{ts}.bin'), 0, 0, 0x10000)
    # DDR heap: fields 3 covers 0x200000..0x300000; dump 0x200000..0x290000 via field 3 offsets 0..0x90000
    set_field(3)
    with open(os.path.join(HERE, f'heap_{ts}.bin'), 'wb') as fo:
        for off in range(0, 0x90000, 4):
            fo.write(struct.pack('<I', R(APER + off)))
    log('dump', n, ts)
    time.sleep(5)
log('monitor end')
