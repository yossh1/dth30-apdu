#!/usr/bin/env python3
# hw28: N-038 follow-up - guarded retry of the hw27 type 4 open.
#
# Purpose: hw27 was an INVALID run for H-043: the issued image never landed
# in the slot (LANDING/POST all zero, signature scan 0 hits) and the doorbell
# was never processed (MMR 0x3048 stayed 0xcb00), after which TS collapsed.
# hw28 separates the LANDING stage from the doorbell stage and controls the
# startup-ACK variable explicitly.
#
# Deltas vs hw27 (everything else, including the issued image with
# param+0x08 = 1, slot index 7, gates B/C, observation set, is identical):
#   1. LANDING GUARD: after the bulk OUT (op 5976), the slot is read back up
#      to --guard-tries times. The image counts as landed only if the
#      signature matches (param+0x58==4, +0x5c==1, +0x60==0x40000,
#      +0x08==1, +0x68==1, +0x84==2). If the guard fails, the B-channel
#      teardown ops (5977-5981) are still executed but the doorbell pair
#      (op 5982 W(MMR+0x3030, slot) / op 5983 W(MMR+0x3020, 8)) is NOT rung,
#      and the run ends after a TS-impact check. This makes landing-only
#      retries safe to repeat.
#   2. STARTUP ACK IS AN EXPLICIT VARIABLE: hw27 found MMR 0x30e0 bit0
#      (unsolicited-side pending) set at startup (0x30e0=0x80000001) and
#      cleared it with W(0x30e0, 0x1) before issuing; hw26 had no pending
#      bits and performed no such write. hw28 logs the startup pending bits
#      either way, and performs the clearing write ONLY with --start-ack.
#      Default is NO startup ACK.
#   3. --tag names the log/dump files (default hw28); --probe skips the
#      field dumps / tag scan / field2 diff for quick landing retries.
# The final ACK after the doorbell (completion bits) is unchanged from
# hw26/hw27: it is part of normal open processing, not the startup variable.
#
# Background (static): constructor key gate @0xa019c79c-0xa019c7b0 aborts
# status 3 when param+0x08==0 AND param+0x0c==0 (n037_trace.md). H-043 is
# judged ONLY on a run where landing + doorbell processing are confirmed
# equivalent to hw26 (0x3048 updates to the slot address, 0x30e0 bit1
# completion notification).
# No writes to candidate card-controller MMRs. No Func 0x19. No
# set_configuration (device already configured; find() only claims).
import argparse, gzip, json, sys, time, struct, threading, os, subprocess
import usb.core, usb.util

ap = argparse.ArgumentParser()
ap.add_argument('--start-ack', action='store_true',
                help='clear pending 0x30e0 bits 0/1 at startup (hw27 behaviour); default: do not')
ap.add_argument('--tag', default='hw28')
ap.add_argument('--probe', action='store_true',
                help='skip field dumps/tag scan/diff (landing-focused retry)')
ap.add_argument('--guard-tries', type=int, default=5)
ap.add_argument('--verbatim', action='store_true',
                help='issue the recorded segment byte-for-byte (recorded image, no rewrites); use with --slot 5')
ap.add_argument('--prefix', action='store_true',
                help='start the issue segment at op 5961 (recorded MMR writes/reads) instead of 5967')
ap.add_argument('--slot', type=int, default=7,
                help='slot index (default 7 = 0x11280; 6 = 0xeec0 as in hw24, 5 = 0xcb00 recorded slot)')
ARGS = ap.parse_args()
TAG = ARGS.tag

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, f'{TAG}.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)

SLOT_INDEX = ARGS.slot
SLOT_ADDR = 0x1840 + SLOT_INDEX * 0x23c0
CTX = 0x88DC  # offset within field 2 (phys 0x1088DC)
OBJ = CTX + 0x1408
EXACT_TAGS = {0x731c00c0, 0x731000c0, 0x730c00c0, 0x728400c0,
              0x728800c0, 0x730800c0, 0x732000c0, 0x72d000c0}

dev = None
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

def throttled(tag):
    try:
        out = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:
        out = f'ERR {e}'
    log(f'throttled[{tag}]: {out}')

CTX_FIELDS = [
    ('marker_8E24', CTX + 0x8E24), ('marker_4B1C', CTX + 0x4B1C),
    ('ctx+0x30', CTX + 0x30), ('ctx+0x318', CTX + 0x318), ('ctx+0x324', CTX + 0x324),
    ('ctx+0x2408=obj+0x1000', CTX + 0x2408), ('ctx+0x2640', CTX + 0x2640),
    ('ctx+0x4bdc', CTX + 0x4BDC),
    ('obj+0x8c', OBJ + 0x8C), ('obj+0x90', OBJ + 0x90), ('obj+0xe8', OBJ + 0xE8),
    ('obj+0x334', OBJ + 0x334), ('obj+0x808', OBJ + 0x808),
    ('obj+0x834', OBJ + 0x834), ('obj+0x85c', OBJ + 0x85C),
    ('obj+0xff0', OBJ + 0xFF0), ('obj+0xff8', OBJ + 0xFF8),
    ('band_ff0', 0x37FF0), ('band_fd8', 0x37FD8),
]
def read_ctx(tag):
    vals = {}
    try:
        set_field(2)
        for name, off in CTX_FIELDS:
            vals[name] = R(APER + off)
    finally:
        try: set_field(0)
        except Exception: pass
    log(tag, ' '.join(f'{n}={v:#010x}' for n, v in vals.items()))
    return vals

def read_slot(tag):
    vals = {}
    try:
        set_field(1)
        for name, off in [('slot+0x10', 0x10), ('slot+0x18', 0x18), ('slot+0x1c', 0x1c), ('slot+0x3c', 0x3c),
                          ('param+0x08', 0x24 + 0x08), ('param+0x0c', 0x24 + 0x0c),
                          ('param+0x18', 0x24 + 0x18), ('param+0x1c', 0x24 + 0x1c),
                          ('param+0xc8', 0x24 + 0xC8), ('param+0xcc', 0x24 + 0xCC),
                          ('param+0x58', 0x24 + 0x58), ('param+0x5c', 0x24 + 0x5c), ('param+0x60', 0x24 + 0x60),
                          ('param+0x68', 0x24 + 0x68), ('param+0x84', 0x24 + 0x84)]:
            vals[name] = R(APER + SLOT_ADDR + off)
    finally:
        try: set_field(0)
        except Exception: pass
    log(tag, ' '.join(f'{n}={v:#010x}' for n, v in vals.items()))
    return vals

def dump_field(field, path):
    set_field(field)
    try:
        with open(path, 'wb') as f:
            for off in range(0, 0x100000, 4):
                f.write(struct.pack('<I', R(APER + off)))
    finally:
        try: set_field(0)
        except Exception: pass

def tag_scan(path):
    data = open(path, 'rb').read()
    ex = fam = 0
    hits = []
    for i in range(0, len(data) - 3, 4):
        v = struct.unpack('<I', data[i:i+4])[0]
        if v in EXACT_TAGS:
            ex += 1; hits.append(i)
        elif (v & 0xFFFF) == 0x00C0 and 0x7200 <= (v >> 16) <= 0x73FF:
            fam += 1
    return ex, fam, hits[:20]

stop_drain = threading.Event()
def drain(ep, n):
    while not stop_drain.is_set():
        try: dev.read(ep, n, timeout=1000)
        except usb.core.USBTimeoutError: continue
        except Exception: return

def ts_check(tag, secs=10):
    total = sync = scr = pk = 0
    t1 = time.time()
    while time.time() - t1 < secs:
        try: b = bytes(dev.read(0x83, 0x17800 * 4, timeout=2000))
        except usb.core.USBTimeoutError: continue
        except Exception as e:
            log(tag, 'TS read err', e); break
        total += len(b)
        for j in range(0, len(b) - 187, 188):
            if b[j] == 0x47:
                sync += 1
                if (b[j + 3] >> 6) & 3: scr += 1
            pk += 1
    log(f'{tag} TS EP83: {total} bytes in {secs}s; sync {sync}/{pk}, scrambled {scr}')
    return total

def build_image():
    if ARGS.verbatim:
        return bytes.fromhex(ops[5976][3])
    img = bytearray(bytes.fromhex(ops[5976][3]))
    assert len(img) == 9152
    struct.pack_into('<I', img, 0x14, SLOT_ADDR + 0x24)
    struct.pack_into('<I', img, 0x1c, SLOT_INDEX)
    struct.pack_into('<I', img, 0x24 + 0x58, 4)        # param+0x58 type = 4
    struct.pack_into('<I', img, 0x24 + 0x5c, 1)        # param+0x5c bit0
    struct.pack_into('<I', img, 0x24 + 0x60, 0x40000)  # param+0x60 bit 0x40000
    struct.pack_into('<I', img, 0x24 + 0x68, 1)        # opener gate B: in {1,2}
    struct.pack_into('<I', img, 0x24 + 0x84, 2)        # opener gate C: in {2,3}
    struct.pack_into('<I', img, 0x24 + 0x08, 1)        # param+0x08 key low half (hw27 delta, kept)
    return bytes(img)

def run_op(k, img):
    o = ops[k]; kind = o[0]
    if o[1] >= 0.03: time.sleep(o[1])
    if kind == 'O':
        ep, data = o[2], bytes.fromhex(o[3])
        if ARGS.verbatim:
            pass  # recorded bytes as-is (5972/5976/5982 included)
        elif k == 5972:
            data = struct.pack('<HII', 0x001f, 0x194, APER + SLOT_ADDR)
        elif k == 5976:
            data = img
        elif k == 5982:
            data = struct.pack('<HII', 0x402f, MMR + 0x3030, SLOT_ADDR)
        dev.write(ep, data, timeout=5000)
        log(f'issue op{k} O ep={ep:#x} len={len(data)}')
    elif kind == 'I':
        d = bytes(dev.read(o[2], o[3], timeout=5000))
        log(f'issue op{k} I ep={o[2]:#x} len={o[3]} actual={d.hex()} expect={o[4]}')
    else:
        log(f'issue op{k} unexpected kind {kind}')

def landing_ok(vals):
    if ARGS.verbatim:
        return (vals['param+0x58'] == 1 and vals['param+0x60'] == 0x100000
                and vals['slot+0x1c'] == SLOT_INDEX and vals['slot+0x3c'] == 0x1014a490)
    return (vals['param+0x58'] == 4 and vals['param+0x5c'] == 1
            and vals['param+0x60'] == 0x40000 and vals['param+0x08'] == 1
            and vals['param+0x68'] == 1 and vals['param+0x84'] == 2)

def issue_func8_type4_guarded():
    """Returns True if the image landed and the doorbell was rung."""
    img = build_image()
    seg_start = 5961 if ARGS.prefix else 5967
    for k in range(seg_start, 5977):  # (optional recorded prefix +) B-channel DMA setup + bulk OUT (5976)
        run_op(k, img)
    landed = False
    for t in range(ARGS.guard_tries):
        time.sleep(0.3 if t == 0 else 0.5)
        vals = read_slot(f'LANDING try{t} slot:')
        if landing_ok(vals):
            landed = True
            log(f'GUARD: image signature confirmed in slot on try{t} - proceeding to teardown + doorbell')
            break
        log(f'GUARD: try{t} signature not present')
    if not landed:
        log('GUARD ABORT: image did NOT land - executing teardown ops 5977-5981, doorbell ops 5982/5983 SKIPPED')
        for k in range(5977, 5982):
            run_op(k, img)
        return False
    for k in range(5977, 5984):       # teardown + doorbell pair
        run_op(k, img)
    log('doorbell rung')
    return True

def main():
    global dev
    log(f'== hw28 guarded retry: Func 0x08 type 4, tag={TAG} start_ack={ARGS.start_ack} probe={ARGS.probe} ==')
    throttled('start')
    dev = find()
    chip = R(MMR + 0x478)
    log(f'chip id = {chip:#x} (expect 0x030000b3)')
    if chip != 0x030000b3:
        log('ABORT: firmware not up'); return
    pend = R(MMR + 0x30e0)
    log(f'startup MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={pend:#x} '
        f'(bit0 unsolicited pending={pend & 1}, bit1 completion pending={(pend >> 1) & 1})')
    if ARGS.start_ack:
        if pend & 0x3:
            W(MMR + 0x30e0, pend & 0x3); time.sleep(0.5)
            log(f'startup ACK (--start-ack) of pending bits {pend & 0x3:#x}; 0x30e0 now {R(MMR+0x30e0):#x}')
        else:
            log('startup ACK (--start-ack) requested but no pending bits set')
    else:
        log('startup ACK DISABLED for this run (variable control): pending bits left as-is')
    pre = read_ctx('PRE ctx:')
    if pre['marker_8E24'] != 1 or pre['marker_4B1C'] != 1:
        log('ABORT: init markers not 1/1 at phys 0x1088DC - observation untrustworthy, stop before issue')
        return
    read_slot('PRE slot:')
    log(f'PRE MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={R(MMR+0x30e0):#x} 0x3028={R(MMR+0x3028):#x}')
    for ep in (0x82, 0x8f):
        threading.Thread(target=drain, args=(ep, 0x10000), daemon=True).start()
    ts_check('PRE')
    if not ARGS.probe:
        log('dumping field2 pre (1MB, slow)...')
        dump_field(2, os.path.join(HERE, f'{TAG}_f2_pre.bin'))
        log('field2 pre dump done')
    log(f'pre-issue MMR 0x30e0={R(MMR+0x30e0):#x} (pending state at issue time)')
    log(f'== issuing Func 0x08 type 4: slot index {SLOT_INDEX} addr {SLOT_ADDR:#x} ==')
    landed = issue_func8_type4_guarded()
    if not landed:
        log(f'post-abort MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={R(MMR+0x30e0):#x} 0x3028={R(MMR+0x3028):#x}')
        read_ctx('POST-ABORT ctx:')
        ts_check('POST-ABORT')
        throttled('end')
        stop_drain.set()
        log('== hw28 done (guard abort; doorbell not rung) ==')
        return
    log('doorbell done; polling 60s')
    for i in range(30):
        time.sleep(2)
        v = read_ctx(f'POST[{i}] ctx:')
        read_slot(f'POST[{i}] slot:')
        log(f'POST[{i}] MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={R(MMR+0x30e0):#x}')
        if v['ctx+0x318'] != 0 and i >= 4:
            log('ctx+0x318 connected; extending poll by 10 more samples max')
    pend = R(MMR + 0x30e0)
    if pend & 0x3:
        W(MMR + 0x30e0, pend & 0x3); time.sleep(0.5)
        log(f'final ACK of pending bits {pend & 0x3:#x}; 0x30e0 now {R(MMR+0x30e0):#x}')
    ts_check('POST')
    if not ARGS.probe:
        for f in (1, 2, 3):
            p = os.path.join(HERE, f'{TAG}_f{f}_post.bin')
            log(f'dumping field{f} post...')
            dump_field(f, p)
            ex, fam, hits = tag_scan(p)
            log(f'field{f} post tag scan: exact={ex} family={fam} first_hits={hits}')
        pre_data = open(os.path.join(HERE, f'{TAG}_f2_pre.bin'), 'rb').read()
        post_data = open(os.path.join(HERE, f'{TAG}_f2_post.bin'), 'rb').read()
        chg = [i for i in range(0, 0x100000, 4)
               if pre_data[i:i+4] != post_data[i:i+4]]
        ctxwin = [i for i in chg if 0x8000 <= i < 0x12000]
        log(f'field2 diff: {len(chg)} dwords changed; in ctx window (0x8000-0x12000): {len(ctxwin)}')
        for i in ctxwin[:80]:
            log(f'  diff @{i:#x}: {pre_data[i:i+4].hex()} -> {post_data[i:i+4].hex()}')
        # slot writeback diff: compare post field1 slot image against issued image
        img = build_image()
        f1 = open(os.path.join(HERE, f'{TAG}_f1_post.bin'), 'rb').read()
        slot_post = f1[SLOT_ADDR:SLOT_ADDR + 0x23c0]
        sd = [i for i in range(0, 0x23c0, 4) if slot_post[i:i+4] != img[i:i+4]]
        log(f'slot writeback diff vs issued image: {len(sd)} dwords differ')
        for i in sd[:40]:
            log(f'  slot diff @{i:#x}: issued {img[i:i+4].hex()} -> post {slot_post[i:i+4].hex()}')
    read_ctx('FINAL ctx:')
    throttled('end')
    stop_drain.set()
    log('== hw28 done ==')

if __name__ == '__main__':
    main()
