#!/usr/bin/env python3
# hw14: baseline monitor for N-009/N-012 front half - card REMOVED, firmware rebooted,
# session NOT started. Same composition as hw11 (MMR snapshot + shared + field 2),
# distinct file prefixes so hw11 evidence is untouched.
# Assumes firmware is booted (hw14_boot) and NOT session-open. Do NOT set_configuration;
# connection pattern copied from hw11.py. READ-ONLY except aperture page bits (0x43C).
# Each cycle:
#   1. MMR snapshot: 0x1418, 0x1420, 0x1434..0x1464 step 4, 0x10D0, 0x10B8, 0x1094
#   2. shared region dump (field 0, 64KB)      -> mon3_<HHMMSS>.bin
#   3. DDR field 2 dump (0x100000..0x200000)   -> f3_<HHMMSS>.bin
# Usage: hw14.py [--cycles N] [--sleep S]
import sys, time, struct, os, argparse
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
LOGF = open(os.path.join(HERE, 'hw14.log'), 'a', buffering=1)
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
log('chip =', hex(R(MMR + 0x478)), ' hw14 monitor start (card REMOVED, no session), cycles =', args.cycles)
for n in range(args.cycles):
    t0 = time.time(); ts = time.strftime('%H%M%S')
    try:
        snap = ' '.join('%04x=%08x' % (a, R(MMR + a)) for a in MMR_SET)
        log('cycle', n, 'start', ts, 'mmr', snap)
        dump(os.path.join(HERE, f'mon3_{ts}.bin'), 0, 0x10000)
        dump(os.path.join(HERE, f'f3_{ts}.bin'), 2, 0x100000)
        set_field(0)
        log('cycle', n, 'done elapsed=%.1fs' % (time.time() - t0))
    except Exception as e:
        log('cycle', n, 'ERROR', repr(e))
        try: set_field(0)
        except Exception: pass
        time.sleep(5)
    time.sleep(args.sleep)
log('hw14 monitor end')
