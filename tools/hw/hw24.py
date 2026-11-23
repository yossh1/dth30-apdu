#!/usr/bin/env python3
# hw24: N-024 - decode-type Func 0x08 open (type 4) replay addition.
# Basis (static): n020 (arrival conditions), n023 (constructor connects
# ctx+0x318 when param+0x60 bit 0x40000 set), n028 (param+0x58=4 -> opener
# 0xa019702c, param+0x5c bit0 -> constructor), n032 (type 4 is the decode
# open flavour; in replay we set param bits directly).
# Wire format taken from the recorded replay_base Func 8 issue sequence
# (ops 5967..5983, a type-1 open): B-channel (EP 0x0d) DMA setup ->
# EP 0x04 bulk OUT of the 9152-byte slot image (header included) ->
# B-channel teardown -> doorbell W(MMR+0x3030, slot) / W(MMR+0x3020, 8).
# Changes vs the recorded type-1 open (one variable set, the open flavour):
#   slot index 6 (addr 0x1840 + 6*0x23c0 = 0xF580; recorded used index 5)
#   param+0x58 = 4, param+0x5c = 1 (bit0), param+0x60 = 0x40000
# All other image dwords are the recorded type-1 image verbatim.
# Observations (effect side): ctx at phys 0x1088DC (init-marker signature),
# ctx+0x318 / obj+0x1000 (=ctx+0x2408) / ctx+0x4bdc / obj fields, slot
# completion fields, MMR 0x3048/0x30e0, band +0x37FF0/+0x37FD8, TS flow,
# record-tag scan on post dumps (field 1..3). Raw dumps stay in the lab dir.
# No writes to candidate card-controller MMRs. No Func 0x19. No
# set_configuration (device already configured; find() only claims).
import gzip, json, sys, time, struct, threading, os, subprocess
import usb.core, usb.util

HERE = os.path.dirname(os.path.abspath(__file__))
ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
LOGF = open(os.path.join(HERE, 'hw24.log'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a)
    LOGF.write(time.strftime('%H:%M:%S ') + s + '\n')
    print(s, file=sys.stderr, flush=True)

SLOT_INDEX = 6
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
        for name, off in [('slot+0x10', 0x10), ('slot+0x18', 0x18), ('slot+0x1c', 0x1c), ('slot+0x3c', 0x3c)]:
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
    img = bytearray(bytes.fromhex(ops[5976][3]))
    assert len(img) == 9152
    struct.pack_into('<I', img, 0x14, SLOT_ADDR + 0x24)
    struct.pack_into('<I', img, 0x1c, SLOT_INDEX)
    struct.pack_into('<I', img, 0x24 + 0x58, 4)        # param+0x58 type = 4
    struct.pack_into('<I', img, 0x24 + 0x5c, 1)        # param+0x5c bit0
    struct.pack_into('<I', img, 0x24 + 0x60, 0x40000)  # param+0x60 bit 0x40000
    return bytes(img)

def issue_func8_type4():
    img = build_image()
    for k in range(5967, 5984):
        o = ops[k]; kind = o[0]
        if o[1] >= 0.03: time.sleep(o[1])
        if kind == 'O':
            ep, data = o[2], bytes.fromhex(o[3])
            if k == 5972:
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

def main():
    global dev
    log('== hw24 N-024: Func 0x08 type-4 open addition ==')
    throttled('start')
    dev = find()
    chip = R(MMR + 0x478)
    log(f'chip id = {chip:#x} (expect 0x030000b3)')
    if chip != 0x030000b3:
        log('ABORT: firmware not up'); return
    pre = read_ctx('PRE ctx:')
    if pre['marker_8E24'] != 1 or pre['marker_4B1C'] != 1:
        log('WARN: init markers not 1/1 at phys 0x1088DC - ctx may be elsewhere; continuing (fields are still read at the N-018 candidate)')
    read_slot('PRE slot:')
    log(f'PRE MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={R(MMR+0x30e0):#x} 0x3028={R(MMR+0x3028):#x}')
    for ep in (0x82, 0x8f):
        threading.Thread(target=drain, args=(ep, 0x10000), daemon=True).start()
    ts_check('PRE')
    log('dumping field2 pre (1MB, slow)...')
    dump_field(2, os.path.join(HERE, 'n024_f2_pre.bin'))
    log('field2 pre dump done')
    log(f'== issuing Func 0x08 type 4: slot index {SLOT_INDEX} addr {SLOT_ADDR:#x} ==')
    issue_func8_type4()
    log('doorbell done; polling 60s')
    for i in range(30):
        time.sleep(2)
        v = read_ctx(f'POST[{i}] ctx:')
        read_slot(f'POST[{i}] slot:')
        log(f'POST[{i}] MMR 0x3048={R(MMR+0x3048):#x} 0x30e0={R(MMR+0x30e0):#x}')
        if v['ctx+0x318'] != 0 and i >= 4:
            log('ctx+0x318 connected; extending poll by 10 more samples max')
    ts_check('POST')
    for f in (1, 2, 3):
        p = os.path.join(HERE, f'n024_f{f}_post.bin')
        log(f'dumping field{f} post...')
        dump_field(f, p)
        ex, fam, hits = tag_scan(p)
        log(f'field{f} post tag scan: exact={ex} family={fam} first_hits={hits}')
    pre_data = open(os.path.join(HERE, 'n024_f2_pre.bin'), 'rb').read()
    post_data = open(os.path.join(HERE, 'n024_f2_post.bin'), 'rb').read()
    chg = [i for i in range(0, 0x100000, 4)
           if pre_data[i:i+4] != post_data[i:i+4]]
    ctxwin = [i for i in chg if 0x8000 <= i < 0x12000]
    log(f'field2 diff: {len(chg)} dwords changed; in ctx window (0x8000-0x12000): {len(ctxwin)}')
    for i in ctxwin[:80]:
        log(f'  diff @{i:#x}: {pre_data[i:i+4].hex()} -> {post_data[i:i+4].hex()}')
    read_ctx('FINAL ctx:')
    throttled('end')
    stop_drain.set()
    log('== hw24 done ==')

if __name__ == '__main__':
    main()
