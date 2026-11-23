#!/usr/bin/env python3
# hw33: code-region 1-byte experiment (successor of hw29/phase-2). Stage A: after download (ops[0:355]) dump field1 [0x48000,0x58000) sequentially, locate the ops[339] payload context of the boot-publish addiu (file 0x5238C) and check the immediate byte; segment 2 spot-reads MMR 0x3028 every 5 ops to catch the published boot-state value (5 stock / 6 modified). Stage B: same as hw29.
# Based on hw14_boot (Stage A) / hw15 (Stage B), with ONE behavioural addition:
# EVERY op is recorded to hw22_ops.jsonl with its op index and wall-clock time.
# For 'I' ops the expected vs actual values and the match flag are recorded
# per op (hw1/hw14_boot only counted mismatches in aggregate), so the Stage A
# read-mismatch ops can be identified exactly and diffed between the card-in
# run (S1) and the card-out run (S2) for N-015.
# In Stage B mode, a band spot read (field2 +0x37FF0 / +0x37FD8, 2 dword,
# read-only) is interleaved every 250 ops and recorded in the same jsonl as
# kind='SPOT', so bit1 / +0x37FD8 changes can be attributed to an op interval
# (design A.1 step 2). The spot reads do not alter replay semantics.
# 'S' op drains use the capturing drain (same format as hw20: cap22_ep<XX>.bin
# + cap22_index.jsonl, lab dir only) so the capturing drain stays ON for the
# whole session even when hw22 runs the replay (design: capturing drain ON
# throughout S1/S2).
# Usage:
#   hw22.py --stage A   (USB reset, then ops[0:660]; per-op log; effect check)
#   hw22.py --stage B   (no reset, no set_configuration; ops[660:]; spot reads;
#                        TS effect check)
# No writes to candidate card-controller MMRs. Func 0x19 is NOT resent outside
# the recorded replay stream (the replay is the phase-1 proven sequence).
import gzip, json, sys, time, struct, threading, os, argparse
import usb.core, usb.util

ap = argparse.ArgumentParser()
ap.add_argument('--stage', choices=['A', 'B'], required=True)
ap.add_argument('--ops', required=True)
ap.add_argument('--tag', required=True)
ap.add_argument('--expect', default=None, help='expected immediate byte at file 0x5238C (addiu $v0,$zero,imm), hex e.g. 06')
args = ap.parse_args()
STAGE = args.stage
TAG = args.tag
EXPECT = int(args.expect, 16) if args.expect else None

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(args.ops, 'rt'))
LOGF = open(os.path.join(HERE, f'hw33_{TAG}{STAGE}.log'), 'w', buffering=1)
OPSF = open(os.path.join(HERE, f'hw33_{TAG}{STAGE}_ops.jsonl'), 'w', buffering=1)
CAPIDX = open(os.path.join(HERE, 'cap33_index.jsonl'), 'a', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)
def oplog(rec):
    rec.setdefault('t', time.time()); rec.setdefault('wall', time.strftime('%H:%M:%S'))
    OPSF.write(json.dumps(rec) + '\n')
MINDT = 0.03
dev = None
drain_stats = {}
cap_files = {}
cap_lock = threading.Lock()
def cap_open(ep):
    with cap_lock:
        if ep not in cap_files:
            cap_files[ep] = open(os.path.join(HERE, f'cap33_ep{ep:02x}.bin'), 'wb', buffering=0)
        return cap_files[ep]
def drain(ep, n):
    f = cap_open(ep); off = 0
    while True:
        try: b = bytes(dev.read(ep, n, timeout=1000))
        except usb.core.USBTimeoutError: continue
        except Exception: return
        f.write(b)
        with cap_lock:
            CAPIDX.write(json.dumps({'t': time.time(), 'wall': time.strftime('%H:%M:%S'),
                                     'ep': ep, 'len': len(b), 'off': off}) + '\n')
        off += len(b)
        drain_stats[ep] = drain_stats.get(ep, 0) + len(b)
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

MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def band_spot():
    # read-only: field2 +0x37FF0 / +0x37FD8 (hw19 convention), aperture restored
    try:
        set_field(2)
        ff0 = R(APER + 0x37FF0); fd8 = R(APER + 0x37FD8)
        return ff0, fd8
    finally:
        try: set_field(0)
        except Exception: pass

def readback_target():
    # Sequential dump of field 1 [0x48000, 0x58000) before core release.
    # Locate the ops[339] payload context (16B around the boot-publish
    # addiu at image file 0x5238C) inside the dump; the immediate byte is
    # at context+8. Full dump saved for offline cross-run diff.
    try:
        set_field(1)
        dump = bytearray()
        for off in range(0x48000, 0x58000, 4):
            dump += struct.pack('<I', R(APER + off))
        open(os.path.join(HERE, f'hw33_{TAG}_f1dump.bin'), 'wb').write(bytes(dump))
        ctx = bytes.fromhex(ops[339][3])[74500:74516]
        j = bytes(dump).find(ctx)
        if j < 0:
            log('READBACK context NOT FOUND in field1 [0x48000,0x58000)')
            oplog({'kind': 'READBACK', 'found': False})
            return b''
        tgt = dump[j + 8]
        win = bytes(dump[j:j + 32])
        log(f'READBACK context at field1 offset {0x48000 + j:#x} (dump idx {j}), window {win.hex()}')
        log(f'READBACK target byte (addiu imm, file 0x5238C) = {tgt:#04x} (expect {EXPECT:#04x}) -> {"PASS" if tgt == EXPECT else "FAIL"}')
        oplog({'kind': 'READBACK', 'found': True, 'field1_off': 0x48000 + j, 'window': win.hex(), 'target': tgt, 'expect': EXPECT, 'pass': tgt == EXPECT})
        return win
    finally:
        try: set_field(0)
        except Exception: pass

mism_ops = []
def run_ops(a, b, spot_every=0, spot3028_every=0):
    global dev
    mism = 0
    last3028 = None
    for k in range(a, b):
        o = ops[k]; kind = o[0]
        if spot3028_every and k > a and (k - a) % spot3028_every == 0:
            try:
                v = R(MMR + 0x3028)
                oplog({'op': k, 'kind': 'SPOT3028', 'v': v})
                if v != last3028:
                    log(f'SPOT3028 op {k}: MMR 0x3028 = {v}'); last3028 = v
            except Exception as e:
                oplog({'op': k, 'kind': 'SPOT3028', 'error': repr(e)})
        if spot_every and k > a and (k - a) % spot_every == 0:
            try:
                ff0, fd8 = band_spot()
                oplog({'op': k, 'kind': 'SPOT', 'ff0': ff0, 'fd8': '%08x' % fd8})
            except Exception as e:
                oplog({'op': k, 'kind': 'SPOT', 'error': repr(e)})
        if kind == 'S':
            oplog({'op': k, 'kind': 'S', 'ep': o[2], 'len': o[3]})
            threading.Thread(target=drain, args=(o[2], o[3]), daemon=True).start(); continue
        if kind == 'P':
            oplog({'op': k, 'kind': 'P'}); continue
        if o[1] >= MINDT: time.sleep(o[1])
        if dev is None: dev = find()
        if kind == 'C':
            dev.set_configuration(1)
            for i in range(3):
                try: usb.util.claim_interface(dev, i)
                except Exception: pass
            oplog({'op': k, 'kind': 'C'})
        elif kind == 'D':
            dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
            oplog({'op': k, 'kind': 'D', 'type': o[2], 'req': o[3], 'len': o[4]})
        elif kind == 'X':
            rt, req, val, idx, data, ln = o[2:8]
            dev.ctrl_transfer(rt, req, val, idx, ln if rt & 0x80 else bytes.fromhex(data))
            oplog({'op': k, 'kind': 'X', 'rt': rt, 'req': req, 'val': val, 'idx': idx, 'len': ln})
        elif kind == 'O':
            dev.write(o[2], bytes.fromhex(o[3]), timeout=5000)
            oplog({'op': k, 'kind': 'O', 'ep': o[2], 'len': len(bytes.fromhex(o[3])), 'head': o[3][:8]})
        elif kind == 'I':
            d = bytes(dev.read(o[2], o[3], timeout=5000))
            match = (o[4] is None) or (d.hex() == o[4])
            if not match: mism += 1; mism_ops.append(k)
            oplog({'op': k, 'kind': 'I', 'ep': o[2], 'len': o[3],
                   'expect': o[4], 'actual': d.hex(), 'match': match})
        elif kind == 'Q':
            _, _, epo, req, epi, final, tmo = o; tq = time.time() + tmo; it = 0; last = None; ok = False
            while True:
                dev.write(epo, bytes.fromhex(req), timeout=5000)
                d = bytes(dev.read(epi, 4, timeout=5000)); it += 1; last = d.hex()
                if final is None or d.hex() == final: ok = True; break
                if time.time() > tq: break
            oplog({'op': k, 'kind': 'Q', 'ep': epi, 'iters': it, 'matched': ok, 'last': last})
    return mism

def main():
    global dev
    if STAGE == 'A':
        log(f'== hw33 stage A [{TAG}]: code-region 1-byte experiment boot replay, ops={args.ops} ==')
        dev = find()
        try: dev.reset()
        except Exception as e: log('reset:', e)
        time.sleep(1.5); dev = find()
        m = run_ops(0, 355)
        log(f'stage A segment 1 (download) done, read mismatches {m}, mismatch ops {mism_ops}')
        mism_ops.clear()
        raw = readback_target()
        open(os.path.join(HERE, f'hw33_{TAG}_readback.bin'), 'wb').write(raw)
        m2 = run_ops(355, 660, spot3028_every=5)
        log(f'stage A segment 2 (vectors/FB/release/handshake) done, read mismatches {m2}, mismatch ops {mism_ops}')
        m = m + m2
        chip = R(MMR + 0x478); hs = R(MMR + 0x3028)
        log(f'effect check: chip id = {chip:#x} (expect 0x030000b3), MMR 0x3028 = {hs} (expect 0)')
        if chip != 0x030000b3 or hs != 0:
            log('STAGE A FAIL - firmware not up, stop'); return
    else:
        log(f'== hw33 stage B [{TAG}]: session replay + band spot every 250 ops ==')
        dev = find()
        t0 = time.time()
        m = run_ops(660, len(ops), spot_every=250)
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
    log(f'== hw33 stage {STAGE} [{TAG}] done ==')

if __name__ == '__main__':
    main()
