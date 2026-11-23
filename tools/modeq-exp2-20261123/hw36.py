#!/usr/bin/env python3
# hw36: N-057 Mode Q handler device verification ROUND 2 (successor of hw35).
# Round-2 differences vs hw35: fixed handler build (true $gp-derived globals
# 0x80227050 / 0x8022700C per GLOBALS-FIX.md), and a mandatory PREFLIGHT
# globals check in stage B before any Func 0x04 issue: the state-ptr and
# pool-ptr globals are spot-read and must exactly match the desk-derived
# stored values (0xA0237ED8 / 0xA022F254); if the re-check fails, the Mode Q
# issues are skipped. The full pre-flight (incl. negative control at the old
# addresses) is done by the companion spot2.py against the stock A1 boot.
# Stage A: boot replay (stock or modeq), pre-release readbacks: field1 low
# full diff, cave span, worker-table window, AND the Func 0x04 stub body
# window [0x534D0,0x5359C) vs the run's stream reference.
# Stage B: session replay, TS check, post readbacks, optional control Func
# (--funcs), optional Mode Q Func 0x04 issues (--apdu04 N) carrying the
# INITIAL_SETTING APDU 90 30 00 00 00 at slot+0x44 per the handler host
# contract (+0x40 len u16 / +0x42 status u16 / +0x44 bytes). The response
# bytes are NEVER persisted (they contain card ID / system key): only
# length, return-code field, trailing SW and a SHA-256 fingerprint are
# logged.
# Invariants kept from hw34: no set_configuration outside the recorded
# replay, no MMR 0x58 bit2, no standalone Func 0x19.
import gzip, json, sys, time, struct, threading, os, argparse, hashlib
import usb.core, usb.util

ap = argparse.ArgumentParser()
ap.add_argument('--stage', choices=['A', 'B'], required=True)
ap.add_argument('--ops', required=True)
ap.add_argument('--tag', required=True)
ap.add_argument('--funcs', default='', help='comma list of control Func numbers (hex), e.g. 05')
ap.add_argument('--apdu04', type=int, default=0, help='number of Mode Q Func 0x04 issues in stage B')
ap.add_argument('--expect-table', choices=['stock', 'hook'], default='stock')
ap.add_argument('--expect-cave', choices=['zero', 'modeq'], required=True)
ap.add_argument('--expect-stub', choices=['stock', 'modeq'], required=True)
args = ap.parse_args()
STAGE = args.stage
TAG = args.tag
FUNCS = [int(x, 16) for x in args.funcs.split(',') if x] if args.funcs else []
EXPECT_TABLE = args.expect_table
EXPECT_CAVE = args.expect_cave
EXPECT_STUB = args.expect_stub

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(args.ops, 'rt'))
STREAM_REF = open(os.path.join(HERE, 'stream_modeq.bin' if EXPECT_STUB == 'modeq' else 'stream_base.bin'), 'rb').read()
LOGF = open(os.path.join(HERE, f'hw36_{TAG}{STAGE}.log'), 'w', buffering=1)
OPSF = open(os.path.join(HERE, f'hw36_{TAG}{STAGE}_ops.jsonl'), 'w', buffering=1)
CAPIDX = open(os.path.join(HERE, 'cap36_index.jsonl'), 'a', buffering=1)
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
            cap_files[ep] = open(os.path.join(HERE, f'cap36_ep{ep:02x}.bin'), 'wb', buffering=0)
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
    try:
        set_field(2)
        ff0 = R(APER + 0x37FF0); fd8 = R(APER + 0x37FD8)
        return ff0, fd8
    finally:
        try: set_field(0)
        except Exception: pass

CAVE_LO, CAVE_HI = 0x1E238, 0x1FBFC   # stream offsets == field1 offsets
TBL_WIN_LO = 0xFF100                  # table window [0xFF100, 0xFF200)
STUB_LO, STUB_HI = 0x534D0, 0x5359C   # Func 0x04 stub body window
TRAMP = bytes.fromhex('8e78040800000000')
def payload_bytes(opidx):
    return bytes.fromhex(ops[opidx][3])
def dump_f1(lo, hi):
    set_field(1)
    out = bytearray()
    for off in range(lo, hi, 4):
        out += struct.pack('<I', R(APER + off))
    return bytes(out)
def cave_expected():
    return payload_bytes(338)[CAVE_LO:CAVE_HI]
def stub_check(data, label):
    exp = STREAM_REF[STUB_LO:STUB_HI]
    nd = sum(1 for i in range(len(exp)) if data[i] != exp[i])
    t_ok = (data[:8] == TRAMP) if EXPECT_STUB == 'modeq' else (data[:8] == exp[:8])
    log(f'STUB {label}: window [{STUB_LO:#x},{STUB_HI:#x}) diff vs {EXPECT_STUB} stream ref: {nd} bytes; first8={data[:8].hex()} trampoline {"PASS" if t_ok else "FAIL"}')
    oplog({'kind': 'STUB', 'label': label, 'diff': nd, 'first8': data[:8].hex(), 'tramp_pass': t_ok})
    return nd
def readback_stageA():
    try:
        dump = dump_f1(0, 0x40000)
        open(os.path.join(HERE, f'hw36_{TAG}_f1low.bin'), 'wb').write(dump)
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
        open(os.path.join(HERE, f'hw36_{TAG}_tblwin.bin'), 'wb').write(win)
        texp = payload_bytes(341)[0x3F100:0x3F200]
        td = sum(1 for i in range(0x100) if win[i] != texp[i])
        e4 = struct.unpack('<I', win[0x80:0x84])[0]
        e5 = struct.unpack('<I', win[0x84:0x88])[0]
        want = 0x801534d0
        log(f'READBACK table window full diff vs payload: {td} bytes differ; entry[4]={e4:#010x} (expect {want:#010x}, variant B keeps stock entry) -> {"PASS" if e4 == want else "FAIL"}; entry[5]={e5:#010x}')
        oplog({'kind': 'READBACK_A_TBL', 'tbl_diff': td, 'entry4': e4, 'entry5': e5, 'expect4': want, 'pass': e4 == want})
        stub = dump_f1(STUB_LO, STUB_HI)
        open(os.path.join(HERE, f'hw36_{TAG}_stubwin.bin'), 'wb').write(stub)
        stub_check(stub, 'stageA')
        return dump
    finally:
        try: set_field(0)
        except Exception: pass

def readback_post(tag_suffix):
    try:
        set_field(1)
        cave = bytearray()
        for off in range(CAVE_LO, CAVE_HI, 4):
            cave += struct.pack('<I', R(APER + off))
        cave = bytes(cave)
        open(os.path.join(HERE, f'hw36_{TAG}_cave_{tag_suffix}.bin'), 'wb').write(cave)
        cexp = cave_expected()
        cdiff = sum(1 for i in range(len(cave)) if cave[i] != cexp[i])
        first = next((i for i in range(len(cave)) if cave[i] != cexp[i]), None)
        log(f'POSTREAD cave ({tag_suffix}, expect {EXPECT_CAVE}): {cdiff} bytes differ vs payload span, first {first}')
        win = dump_f1(TBL_WIN_LO, TBL_WIN_LO + 0x100)
        open(os.path.join(HERE, f'hw36_{TAG}_tblwin_{tag_suffix}.bin'), 'wb').write(win)
        e4 = struct.unpack('<I', win[0x80:0x84])[0]
        log(f'POSTREAD table ({tag_suffix}): entry[4]={e4:#010x} (expect 0x801534d0) -> {"PASS" if e4 == 0x801534d0 else "FAIL"}')
        stub = dump_f1(STUB_LO, STUB_HI)
        open(os.path.join(HERE, f'hw36_{TAG}_stubwin_{tag_suffix}.bin'), 'wb').write(stub)
        sd = stub_check(stub, f'post-{tag_suffix}')
        oplog({'kind': 'POSTREAD', 'suffix': tag_suffix, 'cave_diff': cdiff, 'cave_first': first, 'entry4': e4, 'stub_diff': sd})
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
def slot_setup_header(func):
    for off, val in ((0x00, 0), (0x04, 0), (0x08, 1), (0x0C, func), (0x10, 0),
                     (0x14, SLOT + 0x24), (0x18, 0), (0x1C, 0)):
        aper_w(SLOT + off, val)
    for off in range(0x24, 0x24 + 0x100, 4):
        aper_w(SLOT + off, 0)
    set_field(0)
def issue_func(func):
    log(f'ISSUE Func {func:#04x} (control): building slot at {SLOT:#x}')
    log(f'  trace before: {[hex(x) for x in trace_page()]}')
    slot_setup_header(func)
    log(f'  slot hdr: {[hex(aper_r(SLOT + 4 * i)) for i in range(8)]}')
    W(MMR + 0x3030, SLOT); W(MMR + 0x3020, func)
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

def preflight_recheck():
    # GLOBALS-FIX.md pre-flight items 1-3 + 5, re-run on the patched boot
    # right before the Func 0x04 issues. Read-only APER spot reads.
    ok = True
    def chk(label, cond, val):
        nonlocal ok
        log(f'  PREFLIGHT {label}: {val} -> {"PASS" if cond else "FAIL"}')
        oplog({'kind': 'PREFLIGHT', 'item': label, 'val': val, 'pass': bool(cond)})
        ok = ok and bool(cond)
    try:
        sp = aper_r(0x227050)
        chk('state-ptr *(0x80227050)==0xA0237ED8', sp == 0xA0237ED8, hex(sp))
        if sp == 0xA0237ED8:
            sph = sp & 0x1FFFFFFF
            g118 = aper_r(sph + 0x118)
            chk('state+0x118 bit1 (ATR parsed)', g118 & 2, hex(g118))
            ns = aper_r(sph + 0x110); nr = aper_r(sph + 0x114)
            chk('NS/NR small', ns < 0x100 and nr < 0x100, f'NS={ns:#x} NR={nr:#x}')
            rx0 = aper_r(sph + 0x130); rx1 = aper_r(sph + 0x134)
            chk('RX fill/done <= 0x200', rx0 <= 0x200 and rx1 <= 0x200, f'{rx0:#x}/{rx1:#x}')
        pp = aper_r(0x22700C)
        chk('pool-ptr *(0x8022700C)==0xA022F254', pp == 0xA022F254, hex(pp))
        if pp == 0xA022F254:
            pph = pp & 0x1FFFFFFF
            p0 = aper_r(pph); p14 = aper_r(pph + 0x14)
            def va_ok(v): return v == 0 or (v & 0x1FFFFFFF) < 0x3F00000 and (v >> 29) in (4, 5)
            chk('pool desc words sane', va_ok(p0) and va_ok(p14), f'{p0:#x}/{p14:#x}')
        head = aper_r(0x253308)
        f30 = aper_r((head & 0x1FFFFFFF) + 0x30) if head and head != 0x80253308 else 0
        chk('ctx anchor head + bit0x10 node', head not in (0, 0x80253308) and (f30 & 0x10), f'head={head:#x} +0x30={f30:#x}')
    finally:
        try: set_field(0)
        except Exception: pass
    log(f'  PREFLIGHT re-check overall: {"PASS" if ok else "FAIL"}')
    return ok

APDU_INIT = bytes([0x90, 0x30, 0x00, 0x00, 0x00])  # INITIAL_SETTING, stock session-start APDU
def issue_modeq(nth):
    log(f'ISSUE Func 0x04 (Mode Q #{nth}): APDU=INITIAL_SETTING (5 bytes)')
    log(f'  trace before: {[hex(x) for x in trace_page()]}')
    slot_setup_header(4)
    # payload per host contract: +0x40 len u16 | status u16=0 ; +0x44 APDU
    aper_w(SLOT + 0x40, len(APDU_INIT))
    pad = APDU_INIT + bytes((-len(APDU_INIT)) % 4)
    for i in range(0, len(pad), 4):
        aper_w(SLOT + 0x44 + i, struct.unpack('<I', pad[i:i + 4])[0])
    set_field(0)
    # landing verification before doorbell
    d40 = aper_r(SLOT + 0x40)
    got = b''.join(struct.pack('<I', aper_r(SLOT + 0x44 + i)) for i in range(0, len(pad), 4))[:len(APDU_INIT)]
    land_ok = (d40 == len(APDU_INIT)) and (got == APDU_INIT)
    log(f'  landing: slot+0x40={d40:#x} (len {d40 & 0xFFFF}, status {d40 >> 16:#x}), APDU bytes match={got == APDU_INIT} -> {"PASS" if land_ok else "FAIL"}')
    oplog({'kind': 'MQ_LAND', 'nth': nth, 'd40': d40, 'ok': land_ok})
    if not land_ok:
        log('  ABORT: slot payload did not land; not ringing doorbell')
        return None
    W(MMR + 0x3030, SLOT); W(MMR + 0x3020, 4)
    t0 = time.time()
    # phase 1: acceptance via slot+0x10
    s10 = 0; e0 = 0; acc_t = None
    while time.time() - t0 < 10:
        e0 = R(MMR + 0x30e0); s10 = aper_r(SLOT + 0x10)
        if (e0 & 0x2) or s10 != 0:
            acc_t = time.time() - t0; break
        time.sleep(0.02)
    c302c = R(MMR + 0x302c); c3048 = R(MMR + 0x3048)
    log(f'  acceptance: slot+0x10={s10:#x} after {acc_t if acc_t is not None else -1:.3f}s, 0x30E0={e0:#x} 0x302C={c302c:#x} 0x3048={c3048:#x}')
    oplog({'kind': 'MQ_ACC', 'nth': nth, 'slot10': s10, 'acc_t': acc_t, 'e0': e0, 'r302c': c302c, 'r3048': c3048})
    if e0 & 0x2:
        W(MMR + 0x30e0, 2); log('  ACK sent (0x30E0=2)')
    if s10 != 1:
        d40 = aper_r(SLOT + 0x40)
        log(f'  NOT ACCEPTED: slot+0x42 status now {d40 >> 16:#x}; stopping this issue')
        return {'accepted': False, 'slot10': s10, 'status': d40 >> 16}
    # phase 2: poll status +0x42 until != 0x8000
    seen = []
    status = None; done_t = None
    while time.time() - t0 < 10:
        d40 = aper_r(SLOT + 0x40)
        st = d40 >> 16
        if not seen or seen[-1] != st:
            seen.append(st)
        if st != 0x8000:
            status = st; done_t = time.time() - t0; break
        time.sleep(0.02)
    log(f'  status transitions seen: {[hex(s) for s in seen]}; final={status if status is None else hex(status)} after {done_t if done_t is not None else -1:.3f}s')
    oplog({'kind': 'MQ_STATUS', 'nth': nth, 'seen': seen, 'final': status, 'done_t': done_t})
    if status != 0:
        log(f'  issue #{nth} ended with error/timeout status={status}')
        return {'accepted': True, 'status': status}
    d40 = aper_r(SLOT + 0x40)
    rlen = d40 & 0xFFFF
    raw = b''.join(struct.pack('<I', aper_r(SLOT + 0x44 + i)) for i in range(0, (rlen + 3) // 4 * 4, 4))[:rlen]
    fp = hashlib.sha256(raw).hexdigest()
    sw = raw[-2:].hex() if rlen >= 2 else ''
    ret = raw[4:6].hex() if rlen >= 6 else ''
    struct_ok = (rlen >= 56) and (sw == '9000')
    log(f'  RESPONSE #{nth}: len={rlen} retcode={ret} SW={sw} sha256={fp} structure {"PASS" if struct_ok else "FAIL"}')
    oplog({'kind': 'MQ_RESP', 'nth': nth, 'len': rlen, 'retcode': ret, 'sw': sw, 'sha256': fp, 'struct_ok': struct_ok})
    log(f'  trace after: {[hex(x) for x in trace_page()]}')
    return {'accepted': True, 'status': 0, 'len': rlen, 'sha256': fp, 'struct_ok': struct_ok}

def ts_measure(seconds, label):
    total = 0; sync = 0; scr = 0; pk = 0; t1 = time.time()
    while time.time() - t1 < seconds:
        try: b = bytes(dev.read(0x83, 0x17800 * 4, timeout=2000))
        except usb.core.USBTimeoutError: continue
        except Exception as e: log(f'TS read err ({label})', e); break
        total += len(b)
        for j in range(0, len(b) - 187, 188):
            if b[j] == 0x47:
                sync += 1
                if (b[j + 3] >> 6) & 3: scr += 1
            pk += 1
    log(f'TS {label}: {total} bytes in {seconds}s; sync pkts {sync}/{pk}, scrambled-flag pkts {scr}')
    oplog({'kind': 'TS', 'label': label, 'bytes': total, 'sync': sync, 'pkts': pk, 'scr': scr})
    return total, sync, pk, scr

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
        log(f'== hw36 stage A [{TAG}]: boot replay, ops={args.ops} expect_stub={EXPECT_STUB} ==')
        dev = find()
        try: dev.reset()
        except Exception as e: log('reset:', e)
        time.sleep(1.5); dev = find()
        m = run_ops(0, 355)
        log(f'stage A segment 1 (download) done, read mismatches {m}, mismatch ops {mism_ops}')
        mism_ops.clear()
        readback_stageA()
        m2 = run_ops(355, 660, spot3028_every=5)
        log(f'stage A segment 2 (vectors/FB/release/handshake) done, read mismatches {m2}, mismatch ops {mism_ops}')
        m = m + m2
        chip = R(MMR + 0x478); hs = R(MMR + 0x3028)
        log(f'effect check: chip id = {chip:#x} (expect 0x030000b3), MMR 0x3028 = {hs} (expect 0)')
        if chip != 0x030000b3 or hs != 0:
            log('STAGE A FAIL - firmware not up, stop'); return
    else:
        log(f'== hw36 stage B [{TAG}]: session replay + post readbacks + Func issues ==')
        dev = find()
        t0 = time.time()
        m = run_ops(660, len(ops), spot_every=250)
        log(f'stage B done in {time.time()-t0:.1f}s, read mismatches {m}, mismatch ops {mism_ops[:60]}')
        log(f'chip = {R(MMR + 0x478):#x}')
        ts_measure(10, 'stageB baseline')
        log(f'drains { {hex(k): v for k, v in drain_stats.items()} }')
        readback_post('postB')
        for f in FUNCS:
            issue_func(f)
        results = []
        n_issues = args.apdu04
        if n_issues:
            if not preflight_recheck():
                log('PREFLIGHT re-check FAILED on patched boot: Mode Q issues SKIPPED')
                results = ['preflight-fail']
                n_issues = 0
        for n in range(1, n_issues + 1):
            results.append(issue_modeq(n))
        if results == ['preflight-fail']:
            log('Mode Q results: SKIPPED (preflight re-check failed)')
        if args.apdu04:
            log(f'Mode Q results: {results}')
            ts_measure(10, 'after Mode Q issues (descramble check)')
            readback_post('postF')
        elif FUNCS:
            ts_measure(5, 'recheck after control Func issues')
    log(f'== hw36 stage {STAGE} [{TAG}] done ==')

if __name__ == '__main__':
    main()
