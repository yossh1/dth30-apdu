#!/usr/bin/env python3
# hw21: band polling monitor for N-031 (design n016_n014_design.md A.1, N-030 item 2).
# Extension of the hw14 monitor: instead of dumping all of field 2, each cycle reads
# ONLY the band field2 +0x37E00..+0x38000 (128 dword) every --interval seconds
# (design: 2-5 s; default 3 s), plus the shared +0xF4 dword and the hw14 candidate
# MMR set (18 registers) riding along on the same sample. One JSONL record per
# sample in band_poll.jsonl: wall time, the full band as 128 hex dwords, the key
# values +0x37FF0 / +0x37FD8 broken out, shared +0xF4, and the MMR snapshot.
# Intended to be started BEFORE Stage B (design A.1 step 1: at least 3 baseline
# samples in the pre-B state) and kept running across it and for +15 min after.
# READ-ONLY except the aperture field bits (MMR 0x43C), which are restored to
# field 0 after every sample and on exit (finally + KeyboardInterrupt safe).
# Connection pattern copied from hw14.py: NO set_configuration, no reset.
# Usage: hw21.py [--interval 3] [--seconds 1800] [--cycles N]
import sys, time, struct, os, json, argparse
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
LOGF = open(os.path.join(HERE, 'hw21.log'), 'a', buffering=1)
OUTF = open(os.path.join(HERE, 'band_poll.jsonl'), 'a', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)

ap = argparse.ArgumentParser()
ap.add_argument('--interval', type=float, default=3.0, help='poll interval seconds (design: 2-5)')
ap.add_argument('--seconds', type=float, default=1800.0, help='total run time seconds')
ap.add_argument('--cycles', type=int, default=0, help='if >0, stop after this many samples')
args = ap.parse_args()
if not (2.0 <= args.interval <= 5.0):
    log(f'WARNING: interval {args.interval} outside design range 2-5 s')

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
BAND_OFF = 0x37E00            # in-field-2 offset of the band (DDR 0x137E00)
BAND_LEN = 0x200              # 128 dword up to +0x38000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def read_band():
    # hw19 convention: set_field(2) maps DDR 0x100000..0x200000 into APER,
    # so the band is read at APER + 0x37E00.. (DDR 0x137E00..0x138000)
    set_field(2)
    vals = [R(APER + BAND_OFF + 4 * i) for i in range(BAND_LEN // 4)]
    set_field(0)
    return vals
def read_shared(off):
    set_field(0)
    return R(APER + off)

MMR_SET = [0x1418, 0x1420] + list(range(0x1434, 0x1468, 4)) + [0x10D0, 0x10B8, 0x1094]
log('chip =', hex(R(MMR + 0x478)), f' hw21 band monitor start, interval={args.interval}s seconds={args.seconds}')
t_end = time.time() + args.seconds
n = 0
try:
    while True:
        if args.cycles and n >= args.cycles: break
        if not args.cycles and time.time() >= t_end: break
        t0 = time.time()
        try:
            band = read_band()
            f4 = read_shared(0xF4)
            mmr = {('%04x' % a): R(MMR + a) for a in MMR_SET}
            rec = {'n': n, 't': t0, 'wall': time.strftime('%H:%M:%S'),
                   'ff0': band[(0x37FF0 - 0x37E00) // 4], 'fd8': band[(0x37FD8 - 0x37E00) // 4],
                   'shared_f4': f4, 'mmr': mmr,
                   'band': ['%08x' % v for v in band]}
            OUTF.write(json.dumps(rec) + '\n')
            log('sample', n, rec['wall'], 'ff0=%d fd8=%08x f4=%08x' % (rec['ff0'], rec['fd8'], f4))
        except Exception as e:
            log('sample', n, 'ERROR', repr(e))
        finally:
            try: set_field(0)
            except Exception: pass
        n += 1
        dt = args.interval - (time.time() - t0)
        if dt > 0: time.sleep(dt)
finally:
    try: set_field(0)
    except Exception: pass
log('hw21 band monitor end, samples =', n)
