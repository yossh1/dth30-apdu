#!/usr/bin/env python3
# hw20: capturing-drain harness for N-031 (design n016_n014_design.md B.2, N-030 item 1).
# Full-session replay (Stage A ops[0:660] + Stage B ops[660:]) based on hw1/hw15,
# with ONE behavioural change vs hw15: the 'S' op drain threads no longer discard
# what they read. Every drained chunk is appended to a per-EP raw file
# (cap_ep<XX>.bin) in THIS (lab) directory, and indexed in cap_index.jsonl with
# wall-clock timestamp, EP, length and running offset, so any device->host payload
# that the old harness silently threw away is captured verbatim.
# Additionally every 'I'/'Q'/'O'/'X' transfer is entered into a transfer ledger
# (hw20_xfer.jsonl: op index, kind, EP, direction, length, first-bytes class),
# and 'I'/'Q' raw responses keep being recorded to hw20_resp.jsonl like hw15.
# Raw captures may carry card-related payload: they stay in the lab dir only
# (same handling as hw15_resp.jsonl) and never leave 検証ホスト.
# No writes to candidate card-controller MMRs. Func 0x19 is NOT resent outside
# the recorded replay stream (the replay is the phase-1 proven sequence).
# Effect check at the end: TS flow on EP 0x83 for 10 s, as in hw1/hw15.
import gzip, json, sys, time, struct, threading, os
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw20.log'), 'w', buffering=1)
RESPF = open(os.path.join(HERE, 'hw20_resp.jsonl'), 'w', buffering=1)
XFERF = open(os.path.join(HERE, 'hw20_xfer.jsonl'), 'w', buffering=1)
CAPIDX = open(os.path.join(HERE, 'cap_index.jsonl'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)
MINDT = 0.03
dev = None
drain_stats = {}
cap_files = {}
cap_lock = threading.Lock()
def cap_open(ep):
    with cap_lock:
        if ep not in cap_files:
            cap_files[ep] = open(os.path.join(HERE, f'cap_ep{ep:02x}.bin'), 'wb', buffering=0)
        return cap_files[ep]
def drain(ep, n):
    # capturing drain: identical read loop to hw1/hw15 drain(), but the content
    # is appended to cap_ep<XX>.bin and indexed instead of being discarded.
    f = cap_open(ep)
    off = 0
    while True:
        try:
            b = bytes(dev.read(ep, n, timeout=1000))
        except usb.core.USBTimeoutError: continue
        except Exception: return
        f.write(b)
        with cap_lock:
            CAPIDX.write(json.dumps({'t': time.time(), 'wall': time.strftime('%H:%M:%S'),
                                     'ep': ep, 'len': len(b), 'off': off}) + '\n')
        off += len(b)
        drain_stats[ep] = drain_stats.get(ep, 0) + len(b)
def xfer(op, kind, ep, direction, data):
    XFERF.write(json.dumps({'t': time.time(), 'wall': time.strftime('%H:%M:%S'),
                            'op': op, 'kind': kind, 'ep': ep, 'dir': direction,
                            'len': len(data), 'head': data[:4].hex()}) + '\n')
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

mism_ops = []
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
            r = dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
            xfer(k, 'D', 0, 'in', bytes(r) if r is not None else b'')
        elif kind == 'X':
            rt, req, val, idx, data, ln = o[2:8]
            r = dev.ctrl_transfer(rt, req, val, idx, ln if rt & 0x80 else bytes.fromhex(data))
            xfer(k, 'X', 0, 'in' if rt & 0x80 else 'out',
                 bytes(r) if (rt & 0x80 and r is not None) else bytes.fromhex(data or ''))
        elif kind == 'O':
            payload = bytes.fromhex(o[3])
            dev.write(o[2], payload, timeout=5000)
            xfer(k, 'O', o[2], 'out', payload)
        elif kind == 'I':
            d = bytes(dev.read(o[2], o[3], timeout=5000))
            xfer(k, 'I', o[2], 'in', d)
            RESPF.write(json.dumps({'op': k, 'kind': 'I', 'ep': o[2], 'len': o[3], 'hex': d.hex()}) + '\n')
            if o[4] is not None and d.hex() != o[4]:
                mism += 1; mism_ops.append(k)
        elif kind == 'Q':
            _, _, epo, req, epi, final, tmo = o; tq = time.time() + tmo; it = 0; last = None; ok = False
            while True:
                dev.write(epo, bytes.fromhex(req), timeout=5000)
                d = bytes(dev.read(epi, 4, timeout=5000)); it += 1; last = d.hex()
                if final is None or d.hex() == final: ok = True; break
                if time.time() > tq: break
            xfer(k, 'Q', epi, 'in', bytes.fromhex(last) if last else b'')
            RESPF.write(json.dumps({'op': k, 'kind': 'Q', 'ep': epi, 'iters': it, 'matched': ok, 'last': last}) + '\n')
    return mism

MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]

def main():
    global dev
    log('== hw20 start: full session with capturing drain (raw stays in lab dir) ==')
    dev = find()
    try: dev.reset()
    except Exception as e: log('reset:', e)
    time.sleep(1.5); dev = find()
    log('== STAGE A: replay ops[0:660] (boot only) ==')
    m = run_ops(0, 660)
    log(f'stage A done, read mismatches {m}')
    chip = R(MMR + 0x478); hs = R(MMR + 0x3028)
    log(f'effect check: chip id = {chip:#x} (expect 0x030000b3), MMR 0x3028 = {hs} (expect 0)')
    if chip != 0x030000b3:
        log('STAGE A FAIL - firmware not up, stop'); return
    log('== STAGE B: replay ops[660:] (session open + tune ch27) ==')
    t0 = time.time()
    m = run_ops(660, len(ops))
    log(f'stage B done in {time.time()-t0:.1f}s, read mismatches {m}, mismatch ops {mism_ops[:60]}')
    log(f'chip = {R(MMR + 0x478):#x}')
    total = 0; sync = 0; scr = 0; pk = 0; t1 = time.time()
    while time.time() - t1 < 10:
        try: b = bytes(dev.read(0x83, 0x17800 * 4, timeout=2000))
        except usb.core.USBTimeoutError: continue
        except Exception as e: log('TS read err', e); break
        total += len(b)
        for j in range(0, len(b) - 187, 188):
            if b[j] == 0x47:
                sync += 1
                if (b[j + 3] >> 6) & 3: scr += 1
            pk += 1
    log(f'TS EP83: {total} bytes in 10s; sync pkts {sync}/{pk}, scrambled-flag pkts {scr}; drains { {hex(k): v for k, v in drain_stats.items()} }')
    log('== hw20 done (captures: cap_ep*.bin + cap_index.jsonl + hw20_xfer.jsonl in lab dir) ==')

if __name__ == '__main__':
    main()
