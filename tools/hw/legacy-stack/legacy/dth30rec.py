#!/usr/bin/env python3
# dth30rec: record raw ISDB-T TS from a BUFFALO DT-H30/U2 (board id 0xB3) on Linux.
# Boots the device by replaying the vendor driver's USB sequence (recorded from the
# emulated Windows driver), retargets the tune to <ch>, then streams TS passthrough (EP 0x83).
# usage: dth30rec.py <physical_ch 13-52> <seconds|-> <out.ts|->
# files (same directory): replay_base.json.gz (ch27 lean replay), classA_seq.json
# env: DTH30_MINDT (default 0.03) keep only recorded gaps >= this many seconds
import gzip, json, os, sys, time, struct, subprocess, threading, queue, signal
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
SRC_CH = 27
RDSZ = 0x17800 * 4
MINDT = float(os.environ.get('DTH30_MINDT', '0.03'))

def log(*a): print('dth30rec:', *a, file=sys.stderr, flush=True)

def tx_word(frame):
    b = bytes(frame[:4]) + bytes(4)
    return struct.unpack('<I', b[:4])[0]

def load_ops(ch):
    ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
    if ch == SRC_CH: return ops
    seq = json.load(open(os.path.join(HERE, 'classA_seq.json')))
    src = [o for o in seq['tune'][str(SRC_CH)] if o[0] == 'W']
    dst = [o for o in seq['tune'][str(ch)] if o[0] == 'W']
    want = tx_word(src[0][2])
    tx = [k for k, o in enumerate(ops) if o[0] == 'O' and o[2] == 0x0e and o[3][:12] == '2f4004100020']
    start = max(k for k in tx if int.from_bytes(bytes.fromhex(ops[k][3][12:20]), 'little') == want)
    idx = [k for k in tx if k >= start][:len(src)]
    for k, s_op, d_op in zip(idx, src, dst):
        assert int.from_bytes(bytes.fromhex(ops[k][3][12:20]), 'little') == tx_word(s_op[2])
        ops[k][3] = ops[k][3][:12] + tx_word(d_op[2]).to_bytes(4, 'little').hex()
    return ops

def tsd_override(ops):
    # DTH30_TSD="54=3,60=0": patch the TSD config words written to APER 0x100000xx before Func 0x18
    spec = os.environ.get('DTH30_TSD')
    if not spec: return
    for item in spec.split(','):
        off, val = (int(x, 16) for x in item.split('='))
        key = '2f40' + (0x10000000 + off).to_bytes(4, 'little').hex()
        hit = [o for o in ops if o[0] == 'O' and o[2] == 0x0e and o[3][:12] == key]
        for o in hit: o[3] = key + val.to_bytes(4, 'little').hex()
        log(f'TSD override {off:#x}={val:#x} ({len(hit)} writes)')

def find():
    for _ in range(150):
        d = usb.core.find(idVendor=0x0411, idProduct=0x0128)
        if d is not None: break
        time.sleep(0.1)
    if d is None: raise SystemExit('dth30rec: tuner not found')
    for i in range(3):
        try:
            if d.is_kernel_driver_active(i): d.detach_kernel_driver(i)
        except Exception: pass
    return d

def boot(ops):
    dev = None; t0 = time.time(); fails = 0
    def drain(ep, n):
        dl = open('/run/dth30_debug.log', 'a', buffering=1) if os.environ.get('DTH30_DEBUG') == '1' else None
        while True:
            try:
                b = bytes(dev.read(ep, n, timeout=1000))
                if dl: dl.write(f'{time.time():.3f} EP{ep:02x} len={len(b)} {b[:16].hex()}\n')
            except usb.core.USBTimeoutError: continue
            except Exception: return
    for o in ops:
        kind = o[0]
        if kind == 'S':
            threading.Thread(target=drain, args=(o[2], o[3]), daemon=True).start(); continue
        if kind == 'P':
            subprocess.run(['/root/usbcycle.sh', '3'], check=False); time.sleep(1); dev = find(); continue
        if o[1] >= MINDT: time.sleep(o[1])
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
                if final is None or d.hex() == final: break
                if time.time() > tq: fails += 1; break
    log(f'booted in {time.time() - t0:.1f}s (poll timeouts {fails})')
    return dev

def main():
    if len(sys.argv) != 4:
        raise SystemExit('usage: dth30rec.py <ch 13-62> <seconds|-> <out.ts|->')
    ch = int(sys.argv[1]); secs = None if sys.argv[2] == '-' else float(sys.argv[2])
    out = sys.stdout.buffer if sys.argv[3] == '-' else open(sys.argv[3], 'wb')
    if not 13 <= ch <= 62: raise SystemExit('dth30rec: channel must be 13-62')
    ops = load_ops(ch); tsd_override(ops)
    dev = boot(ops)
    q = queue.Queue(maxsize=512); stop = threading.Event()
    def reader():
        while not stop.is_set():
            try: q.put(bytes(dev.read(0x83, RDSZ, timeout=2000)))
            except usb.core.USBTimeoutError: log('no TS data (timeout)')
            except Exception as e: log('read error', e); stop.set()
    threading.Thread(target=reader, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    total = 0; t1 = time.time()
    try:
        while not stop.is_set() and (secs is None or time.time() - t1 < secs):
            try: b = q.get(timeout=1)
            except queue.Empty: continue
            out.write(b); total += len(b)
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    stop.set()
    try: out.flush()
    except Exception: pass
    dt = max(time.time() - t1, 0.001)
    log(f'ch{ch}: {total} bytes in {dt:.0f}s ({total * 8 / dt / 1e6:.2f} Mbps)')
    os._exit(0)

if __name__ == '__main__':
    main()
