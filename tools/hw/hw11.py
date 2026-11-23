#!/usr/bin/env python3
# hw11: extended differential monitor for N-007 (MMR ride-along) + N-008 (DDR field 2).
# Assumes firmware is already booted + session open on 検証ホスト (do NOT set_configuration;
# connection pattern copied from hw8.py). READ-ONLY: no MMR writes except the aperture
# page register 0x43C field bits, which hw7/hw8 already cycle routinely.
# Each cycle:
#   1. MMR snapshot (candidate card-path registers, read-only):
#      0x1418, 0x1420, 0x1434..0x1464 step 4, 0x10D0, 0x10B8, 0x1094
#   2. shared region dump (field 0, 64KB)      -> mon2_<HHMMSS>.bin
#   3. DDR field 2 dump (0x100000..0x200000)   -> f2_<HHMMSS>.bin
#   Heap (0x200000..0x290000) is intentionally omitted: hw8/hw9 proved it never changes.
# Cycle start time + MMR snapshot + elapsed are logged to hw11.log.
# Usage: hw11.py [--cycles N] [--sleep S]   (trial: --cycles 1)
import sys, time, struct, os, argparse
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
LOGF = open(os.path.join(HERE, 'hw11.log'), 'a', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)

ap = argparse.ArgumentParser()
ap.add_argument('--cycles', type=int, default=120)
ap.add_argument('--sleep', type=float, default=2.0)
args = ap.parse_args()

dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None, 'device not found'
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
def dump(path, field, size):
    set_field(field)
    with open(path, 'wb') as fo:
        for off in range(0, size, 4):
            fo.write(struct.pack('<I', R(APER + off)))

MMR_SET = [0x1418, 0x1420] + list(range(0x1434, 0x1468, 4)) + [0x10D0, 0x10B8, 0x1094]
log('chip =', hex(R(MMR + 0x478)), ' hw11 monitor start, cycles =', args.cycles)
for n in range(args.cycles):
    t0 = time.time(); ts = time.strftime('%H%M%S')
    try:
        snap = ' '.join('%04x=%08x' % (a, R(MMR + a)) for a in MMR_SET)
        log('cycle', n, 'start', ts, 'mmr', snap)
        dump(os.path.join(HERE, f'mon2_{ts}.bin'), 0, 0x10000)
        dump(os.path.join(HERE, f'f2_{ts}.bin'), 2, 0x100000)
        set_field(0)
        log('cycle', n, 'done elapsed=%.1fs' % (time.time() - t0))
    except Exception as e:
        log('cycle', n, 'ERROR', repr(e))
        try: set_field(0)
        except Exception: pass
        time.sleep(5)
    time.sleep(args.sleep)
log('hw11 monitor end')
