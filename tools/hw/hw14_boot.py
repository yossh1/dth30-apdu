#!/usr/bin/env python3
# hw14_boot: N-009 front half - reboot firmware with B-CAS card REMOVED, Stage A only.
# Reuses hw1.py's replay machinery verbatim (ops[0:660] = boot only; boot completes
# ~op648 when MMR 0x3028 Q-poll goes 5->0). Stage B (session open) is NOT run here;
# it belongs to the post-insertion phase.
# After boot: effect check (chip id 0x478, MMR 0x3028), one candidate-MMR snapshot
# (read-only; compare against hw11 card-inserted baseline), and the N-012 trigger-pre
# snapshot pair: shared region (field 0, 64KB) -> pre_shared_<ts>.bin,
# DDR field 2 (1MB) -> pre_f2_<ts>.bin, in the lab dir (raw dumps stay on 検証ホスト).
# No writes to candidate card-controller MMRs.
import gzip, json, sys, time, struct, threading, os
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw14_boot.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)
MINDT = 0.03
dev = None
def drain(ep, n):
    while True:
        try: dev.read(ep, n, timeout=1000)
        except usb.core.USBTimeoutError: continue
        except Exception: return
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

def run_ops(a, b):
    global dev
    mism = 0
    for k in range(a, b):
        o = ops[k]; kind = o[0]
        if kind == 'S':
            threading.Thread(target=drain, args=(o[2], o[3]), daemon=True).start(); continue
        if kind == 'P': continue
        if o[1] >= MINDT: time.sleep(o[1])
        if dev is None: dev = find()
        if kind == 'C':
            dev.set_configuration(1)
            for i in range(3):
                try: usb.util.claim_interface(dev, i)
                except Exception: pass
        elif kind == 'D':
            dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
        elif kind == 'X':
            rt, req, val, idx, data, ln = o[2:8]
            dev.ctrl_transfer(rt, req, val, idx, ln if rt & 0x80 else bytes.fromhex(data))
        elif kind == 'O':
            dev.write(o[2], bytes.fromhex(o[3]), timeout=5000)
        elif kind == 'I':
            d = bytes(dev.read(o[2], o[3], timeout=5000))
            if o[4] is not None and d.hex() != o[4]: mism += 1
        elif kind == 'Q':
            _, _, epo, req, epi, final, tmo = o; tq = time.time() + tmo
            while True:
                dev.write(epo, bytes.fromhex(req), timeout=5000)
                d = bytes(dev.read(epi, 4, timeout=5000))
                if final is None or d.hex() == final or time.time() > tq: break
    return mism

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
    set_field(0)

CAND = [0x1418, 0x1420] + list(range(0x1434, 0x1468, 4)) + [0x10d0, 0x10b8, 0x1094]
def read_cand(tag):
    vals = {}
    for off in CAND:
        try: vals[off] = R(MMR + off)
        except Exception as e: vals[off] = 'ERR'; log(tag, f'read {off:#x} ERR {e}')
    log(tag, ' '.join(f'{o:#x}={v if isinstance(v,str) else format(v,"#010x")}' for o, v in vals.items()))
    return vals

def main():
    global dev
    log('== hw14_boot start: firmware reboot with card REMOVED (user declared 06:55:21 JST) ==')
    dev = find()
    try: dev.reset()
    except Exception as e: log('reset:', e)
    time.sleep(1.5); dev = find()
    log('== STAGE A: replay ops[0:660] (boot only, no session) ==')
    m = run_ops(0, 660)
    log(f'stage A done, read mismatches {m}')
    chip = R(MMR + 0x478); hs = R(MMR + 0x3028)
    log(f'effect check: chip id = {chip:#x} (expect 0x030000b3), MMR 0x3028 = {hs} (expect 0)')
    if chip != 0x030000b3 or hs != 0:
        log('STAGE A FAIL - firmware not up, stop'); return
    log('== candidate MMR snapshot: card-removed, booted, session NOT started ==')
    read_cand('NOCARD')
    ts = time.strftime('%H%M%S')
    log(f'== N-012 trigger-pre snapshot at {ts} ==')
    dump(os.path.join(HERE, f'pre_shared_{ts}.bin'), 0, 0x10000)
    dump(os.path.join(HERE, f'pre_f2_{ts}.bin'), 2, 0x100000)
    log(f'trigger-pre snapshot saved: pre_shared_{ts}.bin (64KB), pre_f2_{ts}.bin (1MB)')
    log('== hw14_boot done ==')

if __name__ == '__main__':
    main()
