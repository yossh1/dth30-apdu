#!/usr/bin/env python3
# hw1: DT-H30/U2 card project - hardware phase 1 (read-only observation)
# Stage A: replay ops[0:660] = firmware boot only (boot HS completes ~op648), then N-002 idle read.
# Stage B: replay ops[660:] = vendor session open + tune ch27, then TS flow check on EP 0x83.
# Stage C: N-005 DDR scan (in-memory only; card-ID-like patterns reported as offset+length+sha256,
#          never written out raw) + return-structure flag-word periodic read.
# Stage D: post-session MMR set re-read (N-003 baseline; card pull/insert needs the user).
# No writes to candidate card-controller MMRs (0x14xx / 0x10AC-0x10B8 / 0x10C8-0x10DC).
import gzip, json, sys, time, struct, threading, os, hashlib, re
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw1.log'), 'w', buffering=1)
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
def B(a, v):
    dev.write(0x0d, struct.pack('<HII', 0x001f, a, v), timeout=2000)
    dev.read(0x8d, 512, timeout=2000)
def set_page(p):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | ((p + 1) << 8))
def aper_r32(ddr):
    set_page(ddr >> 20)
    return R(APER + (ddr & 0xFFFFF))
def dma_in(count):
    B(0x1f4, APER); B(0x1f0, count | 0x40000000); B(0x1e0, 0x2); B(0x1e4, 1)
    return bytes(dev.read(0x81, count, timeout=15000))

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
    log('== hw1 start; usb reset (substitute for P op) ==')
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
    log('== N-002: candidate MMR idle observation (session NOT started), 16 samples x 2s ==')
    base = None; changed = []
    for i in range(16):
        vals = read_cand(f'N002[{i}]')
        if base is None: base = vals
        else:
            for off in CAND:
                if vals[off] != base[off]: changed.append((i, off, base[off], vals[off]))
        time.sleep(2)
    log('N-002 changed entries:', changed if changed else 'NONE (all static)')
    log('== STAGE B: replay ops[660:] (session open + tune) ==')
    m = run_ops(660, len(ops))
    log(f'stage B done, read mismatches {m}; chip = {R(MMR + 0x478):#x}')
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
    log('== STAGE C: N-005 DDR scan for card-ID-like data (in-memory only) ==')
    cands = []
    for p in range(32):
        try:
            set_page(p); data = dma_in(0x100000)
        except Exception as e:
            log(f'page {p}: DMA-IN failed {e}'); continue
        for mm in re.finditer(rb'\d{16,}', data):
            cands.append(('ascii', p * 0x100000 + mm.start(), len(mm.group()), hashlib.sha256(mm.group()).hexdigest()[:12]))
        # BCD run: >=10 consecutive bytes with both nibbles <= 9 and not all zero/ff
        run = 0
        for i2, by in enumerate(data):
            if (by >> 4) <= 9 and (by & 15) <= 9 and by not in (0, 0xff): run += 1
            else:
                if run >= 10: cands.append(('bcd', p * 0x100000 + i2 - run, run, hashlib.sha256(data[i2 - run:i2]).hexdigest()[:12]))
                run = 0
        if run >= 10: cands.append(('bcd', p * 0x100000 + len(data) - run, run, hashlib.sha256(data[len(data) - run:]).hexdigest()[:12]))
    set_page(0)
    log(f'scan candidates (kind, ddr_off, len, sha12): {cands[:40]}')
    struct_base = None
    for kind, off, ln, h in cands:
        for delta in (0x2c, 0x64, 0xa0, 0x80):
            baddr = off - delta
            if baddr < 0: continue
            try:
                flag = aper_r32(baddr + 0x9c); f40 = aper_r32(baddr + 0x40)
            except Exception: continue
            if (flag & 0x400000) and (flag & 0x2000):
                log(f'STRUCT MATCH: base={baddr:#x} (id at +{delta:#x}) flag(+0x9c)={flag:#010x} +0x40={f40:#x}')
                struct_base = baddr
        # also: maybe 'off' itself is inside data region +0x2c.. of a struct whose id starts earlier
    if struct_base is None:
        log('N-005: no return-structure signature matched in DDR scan')
    else:
        log('== N-005 periodic flag observation (10 x 2s) ==')
        prev = None
        for i in range(10):
            flag = aper_r32(struct_base + 0x9c)
            raw = b''.join(struct.pack('<I', aper_r32(struct_base + o)) for o in range(0x2c, 0x40, 4))
            dh = hashlib.sha256(raw).hexdigest()[:12]
            log(f'N005[{i}] flag={flag:#010x} data+0x2c..0x40 sha12={dh}')
            time.sleep(2)
    log('== STAGE D: post-session candidate MMR (N-003 baseline) ==')
    read_cand('POST')
    log('== hw1 done ==')

if __name__ == '__main__':
    main()
