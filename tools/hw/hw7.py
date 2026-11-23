#!/usr/bin/env python3
# hw7: differential dump of shared region (aperture field 0, offsets 0..0x10000)
# state A = boot only (replay ops[0:660]); state B = full replay (session open).
# Raw dumps stay on this host (検証ホスト lab dir); only the diff summary is printed.
import gzip, json, sys, time, struct, threading, os
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw7.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)
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
    assert d is not None
    for i in range(3):
        try:
            if d.is_kernel_driver_active(i): d.detach_kernel_driver(i)
        except Exception: pass
    return d
def run_ops(a, b):
    global dev
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
        elif kind == 'D': dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
        elif kind == 'X':
            rt, req, val, idx, data, ln = o[2:8]
            dev.ctrl_transfer(rt, req, val, idx, ln if rt & 0x80 else bytes.fromhex(data))
        elif kind == 'O': dev.write(o[2], bytes.fromhex(o[3]), timeout=5000)
        elif kind == 'I': dev.read(o[2], o[3], timeout=5000)
        elif kind == 'Q':
            _, _, epo, req, epi, final, tmo = o; tq = time.time() + tmo
            while True:
                dev.write(epo, bytes.fromhex(req), timeout=5000)
                d = bytes(dev.read(epi, 4, timeout=5000))
                if final is None or d.hex() == final or time.time() > tq: break
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def dump_shared(path):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, cur & 0xFFFF80FF)
    with open(path, 'wb') as f:
        for off in range(0, 0x10000, 4):
            f.write(struct.pack('<I', R(APER + off)))
    log('dumped', path)
def main():
    global dev
    dev = find()
    try: dev.reset()
    except Exception: pass
    time.sleep(1.5); dev = find()
    run_ops(0, 660)
    log('boot-only: chip =', hex(R(MMR + 0x478)))
    dump_shared(os.path.join(HERE, 'shared_A_bootonly.bin'))
    run_ops(660, len(ops))
    log('full: chip =', hex(R(MMR + 0x478)))
    time.sleep(3)
    dump_shared(os.path.join(HERE, 'shared_B_session.bin'))
    log('done')
if __name__ == '__main__':
    main()
