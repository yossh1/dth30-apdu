#!/usr/bin/env python3
# hw34: N-053 cave proof + N-047 hook experiment (successor of hw33). Stage A: after download (ops[0:355]) dump field1 [0,0x40000) and the worker-table window pre-release and diff vs the loaded payload (cave span + entry[4] checks); segment 2 spot-reads MMR 0x3028 every 5 ops. Stage B: session replay, TS check, post-op cave/table readbacks, then host-issued Funcs (--funcs) at slot 0x1840 with completion polling.
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
ap.add_argument('--funcs', default='', help='comma list of Func numbers (hex) to issue in stage B, e.g. 05 or 05,04')
ap.add_argument('--expect-table', choices=['stock', 'hook'], required=True)
ap.add_argument('--expect-cave', choices=['zero', 'pattern'], required=True)
args = ap.parse_args()
STAGE = args.stage
TAG = args.tag
FUNCS = [int(x, 16) for x in args.funcs.split(',') if x] if args.funcs else []
EXPECT_TABLE = args.expect_table
EXPECT_CAVE = args.expect_cave

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(args.ops, 'rt'))
LOGF = open(os.path.join(HERE, f'hw34_{TAG}{STAGE}.log'), 'w', buffering=1)
OPSF = open(os.path.join(HERE, f'hw34_{TAG}{STAGE}_ops.jsonl'), 'w', buffering=1)
CAPIDX = open(os.path.join(HERE, 'cap34_index.jsonl'), 'a', buffering=1)
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
            cap_files[ep] = open(os.path.join(HERE, f'cap34_ep{ep:02x}.bin'), 'wb', buffering=0)
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

CAVE_LO, CAVE_HI = 0x1E238, 0x1FBFC   # stream offsets == field1 offsets
TBL_WIN_LO = 0xFF100                  # table window [0xFF100, 0xFF200)
def payload_bytes(opidx):
    return bytes.fromhex(ops[opidx][3])
def dump_f1(lo, hi):
    # sequential APER dump of field1 [lo, hi); caller manages field restore
    set_field(1)
    out = bytearray()
    for off in range(lo, hi, 4):
        out += struct.pack('<I', R(APER + off))
    return bytes(out)
def cave_expected():
    return payload_bytes(338)[CAVE_LO:CAVE_HI]
def readback_stageA():
    # Pre-release readbacks: (1) field1 [0,0x40000) full dump -> full diff vs
    # ops[338] payload and cave span check; (2) table window diff vs ops[341]
    # payload local [0x3F100,0x3F200) + entry[4] check.
    try:
        dump = dump_f1(0, 0x40000)
        open(os.path.join(HERE, f'hw34_{TAG}_f1low.bin'), 'wb').write(dump)
        exp = payload_bytes(338)
        nd = sum(1 for i in range(0x40000) if dump[i] != exp[i])
        log(f'READBACK f1low [0,0x40000) full diff vs ops[338] payload: {nd} bytes differ')
        cave = dump[CAVE_LO:CAVE_HI]
        cexp = cave_expected()
        cdiff = sum(1 for i in range(len(cave)) if cave[i] != cexp[i])
        first = next((i for i in range(len(cave)) if cave[i] != cexp[i]), None)
        log(f'READBACK cave span [{CAVE_LO:#x},{CAVE_HI:#x}) vs payload ({EXPECT_CAVE}): {cdiff} bytes differ, first at {first}')
        oplog({'kind': 'READBACK_A', 'f1low_diff': nd, 'cave_diff': cdiff, 'cave_first_diff': first})
        win = dump_f1(TBL_WIN_LO, TBL_WIN_LO + 0x100)
        open(os.path.join(HERE, f'hw34_{TAG}_tblwin.bin'), 'wb').write(win)
        texp = payload_bytes(341)[0x3F100:0x3F200]
        td = sum(1 for i in range(0x100) if win[i] != texp[i])
        e4 = struct.unpack('<I', win[0x80:0x84])[0]
        e5 = struct.unpack('<I', win[0x84:0x88])[0]
        want = 0x8015359c if EXPECT_TABLE == 'hook' else 0x801534d0
        log(f'READBACK table window full diff vs payload: {td} bytes differ; entry[4]={e4:#010x} (expect {want:#010x}) -> {"PASS" if e4 == want else "FAIL"}; entry[5]={e5:#010x}')
        oplog({'kind': 'READBACK_A_TBL', 'tbl_diff': td, 'entry4': e4, 'entry5': e5, 'expect4': want, 'pass': e4 == want})
        return dump
    finally:
        try: set_field(0)
        except Exception: pass

def readback_post(tag_suffix):
    # Post-operation readbacks (stage B): cave span + table window.
    try:
        set_field(1)
        cave = bytearray()
        for off in range(CAVE_LO, CAVE_HI, 4):
            cave += struct.pack('<I', R(APER + off))
        cave = bytes(cave)
        open(os.path.join(HERE, f'hw34_{TAG}_cave_{tag_suffix}.bin'), 'wb').write(cave)
        cexp = cave_expected()
        cdiff = sum(1 for i in range(len(cave)) if cave[i] != cexp[i])
        first = next((i for i in range(len(cave)) if cave[i] != cexp[i]), None)
        last = next((len(cave) - 1 - i for i in range(len(cave)) if cave[len(cave) - 1 - i] != cexp[len(cave) - 1 - i]), None)
        log(f'POSTREAD cave ({tag_suffix}, expect {EXPECT_CAVE}): {cdiff} bytes differ vs payload span, first {first}, last-diff-idx {last}')
        win = dump_f1(TBL_WIN_LO, TBL_WIN_LO + 0x100)
        open(os.path.join(HERE, f'hw34_{TAG}_tblwin_{tag_suffix}.bin'), 'wb').write(win)
        e4 = struct.unpack('<I', win[0x80:0x84])[0]
        want = 0x8015359c if EXPECT_TABLE == 'hook' else 0x801534d0
        log(f'POSTREAD table ({tag_suffix}): entry[4]={e4:#010x} (expect {want:#010x}) -> {"PASS" if e4 == want else "FAIL"}')
        oplog({'kind': 'POSTREAD', 'suffix': tag_suffix, 'cave_diff': cdiff, 'cave_first': first, 'entry4': e4})
    finally:
        try: set_field(0)
        except Exception: pass

SLOT = 0x1840
def aper_w(phys, val):
    set_field(phys >> 20); W(APER + (phys & 0xFFFFF), val)
def aper_r(phys):
    set_field(phys >> 20); return R(APER + (phys & 0xFFFFF))
def trace_page():
    return [aper_r(0x530 + 4 * i) for i in range(8)]
def issue_func(func):
    # Replicates the recorded driver / func19_test slot format at slot 0x1840.
    log(f'ISSUE Func {func:#04x}: building slot at {SLOT:#x}')
    log(f'  trace before: {[hex(x) for x in trace_page()]}')
    for off, val in ((0x00, 0), (0x04, 0), (0x08, 1), (0x0C, func), (0x10, 0),
                     (0x14, SLOT + 0x24), (0x18, 0), (0x1C, 0)):
        aper_w(SLOT + off, val)
    for off in range(0x24, 0x24 + 0x100, 4):
        aper_w(SLOT + off, 0)
    set_field(0)
    log(f'  slot hdr: {[hex(aper_r(SLOT + 4 * i)) for i in range(8)]}')
    W(MMR + 0x3030, SLOT); W(MMR + 0x3020, func)
    log('  doorbell rung (0x3030=slot, 0x3020=func); polling completion (10s)')
    t0 = time.time(); done = False; s10 = 0; e0 = 0
    while time.time() - t0 < 10:
        e0 = R(MMR + 0x30e0); s10 = aper_r(SLOT + 0x10)
        if (e0 & 0x2) or s10 != 0:
            done = True; break
        time.sleep(0.05)
    c302c = R(MMR + 0x302c); c3048 = R(MMR + 0x3048)
    log(f'  result: completed={done} in {time.time()-t0:.2f}s slot+0x10={s10:#x} MMR 0x30E0={e0:#x} 0x302C={c302c:#x} 0x3048={c3048:#x}')
    oplog({'kind': 'ISSUE', 'func': func, 'completed': done, 'slot10': s10,
           'e0': e0, 'r302c': c302c, 'r3048': c3048})
    if e0 & 0x2:
        W(MMR + 0x30e0, 2); log('  ACK sent (0x30E0=2)')
    log(f'  trace after: {[hex(x) for x in trace_page()]}')
    return done, s10

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
    log(f'== hw34post [{TAG}]: post readbacks + Func issues against live firmware ==')
    dev = find()
    log(f'chip = {R(MMR + 0x478):#x}, MMR 0x3028 = {R(MMR + 0x3028)}')
    readback_post('postB')
    for f in FUNCS:
        issue_func(f)
    if FUNCS:
        total2 = 0; sync2 = 0; pk2 = 0; t2 = time.time()
        while time.time() - t2 < 5:
            try: b = bytes(dev.read(0x83, 0x17800 * 4, timeout=2000))
            except usb.core.USBTimeoutError: continue
            except Exception as e: log('TS recheck read err', e); break
            total2 += len(b)
            for j in range(0, len(b) - 187, 188):
                if b[j] == 0x47: sync2 += 1
                pk2 += 1
        log(f'TS recheck after Func issues: {total2} bytes in 5s; sync pkts {sync2}/{pk2}')
    log(f'== hw34post [{TAG}] done ==')

if __name__ == '__main__':
    main()
