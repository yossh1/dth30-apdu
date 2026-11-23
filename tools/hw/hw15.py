#!/usr/bin/env python3
# hw15: N-009 back half - Stage B (session open + tune ch27) after card insertion,
# on firmware that was rebooted with the card REMOVED (hw14_boot) and monitored
# by hw14 (insertion 07:08:32 JST, session not yet started).
# - Takes pre-B snapshots (shared field0 + DDR field2 + candidate MMR) immediately
#   before Stage B: state = card IN, session NOT started (3rd no-session sample).
# - Replays ops[660:] exactly like hw1.py (no reset, no set_configuration; ops[660:]
#   contains no 'C'/'P' ops). Every 'I' response and every 'Q' poll outcome is
#   recorded to hw15_resp.jsonl IN THE LAB DIR ONLY (raw responses may carry
#   card-related payload; they never leave 検証ホスト). Mismatches are counted
#   per op index, like-for-like with hw1/hw14_boot accounting.
# - Effect check: TS flow on EP 0x83 for 10 s (sync packet count), as in hw1.
# - Takes post-B snapshots immediately after, and again after 45 s
#   (consumption / late-change observation).
# No writes to candidate card-controller MMRs. Func 0x19 is NOT resent outside
# the recorded replay stream (the replay is the phase-1 proven sequence).
import gzip, json, sys, time, struct, threading, os
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw15.log'), 'w', buffering=1)
RESPF = open(os.path.join(HERE, 'hw15_resp.jsonl'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)
MINDT = 0.03
dev = None
drain_stats = {}
def drain(ep, n):
    while True:
        try:
            b = dev.read(ep, n, timeout=1000); drain_stats[ep] = drain_stats.get(ep, 0) + len(b)
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
            dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
        elif kind == 'X':
            rt, req, val, idx, data, ln = o[2:8]
            dev.ctrl_transfer(rt, req, val, idx, ln if rt & 0x80 else bytes.fromhex(data))
        elif kind == 'O':
            dev.write(o[2], bytes.fromhex(o[3]), timeout=5000)
        elif kind == 'I':
            d = bytes(dev.read(o[2], o[3], timeout=5000))
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
            RESPF.write(json.dumps({'op': k, 'kind': 'Q', 'ep': epi, 'iters': it, 'matched': ok, 'last': last}) + '\n')
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

def snap(tag):
    ts = time.strftime('%H%M%S')
    dump(os.path.join(HERE, f'{tag}_shared_{ts}.bin'), 0, 0x10000)
    dump(os.path.join(HERE, f'{tag}_f2_{ts}.bin'), 2, 0x100000)
    log(f'snapshot {tag} at {ts}: {tag}_shared_{ts}.bin, {tag}_f2_{ts}.bin')
    read_cand(tag.upper())
    return ts

def main():
    global dev
    log('== hw15 start: Stage B after insertion (card IN at 07:08:32 JST, session not started) ==')
    dev = find()
    log(f'pre-check: chip = {R(MMR + 0x478):#x}, MMR 0x3028 = {R(MMR + 0x3028)}')
    snap('preB')
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
    snap('postB')
    log('== waiting 45 s, then postB2 snapshot ==')
    time.sleep(45)
    snap('postB2')
    log('== hw15 done ==')

if __name__ == '__main__':
    main()
