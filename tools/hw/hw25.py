#!/usr/bin/env python3
# 【無効】このスクリプトの観測は無効: 旧 EP 0x0d 読み経路の不具合で全読みが固定値 0x228217cc を返したため、観測結果は使用不可。詳細は artifacts/n024_summary.md。
# hw25.py - N-024 retry: Func 0x08 type-4 open with opener gates satisfied.
#
# Static basis (disasm/firmware.asm, opener 0xa019702c for types 2/3/4):
#   gate A @0xa0197158: param+0x60 & 0x000dffe0 != 0   (0x40000 passes)
#   gate B @0xa01971dc: (param+0x68 & 0x7fffffff) in {1,2}, else exit status 4
#   gate C @0xa0197208: (param+0x84 & 0x7fffffff) in {2,3}, else exit status 4
#   then @0xa0197324/7334/7360: param+0x60 bit 0x20000 clear -> straight to
#   constructor block @0xa01973cc: param+0x5c bit1 cleared; bit0 set ->
#   jal constructor 0xa019c754 ($a1=0). Constructor: bit 0x40000 of
#   param+0x60 -> embedded descriptor at ctx+0x7a68, linked at ctx+0x318.
# hw24's image had param+0x68 = param+0x84 = 0 -> status 4, nothing built.
# This run sets param+0x68=1, param+0x84=2 (minimal valid enum values).
#
# Also adds a PRE-DOORBELL landing check: after the EP4 image write, read the
# slot back via APER before ringing the doorbell (hw24 could not distinguish
# "image never landed" from "opener rejected it").
#
# Slot index 7 (0x11280). Read-only MMR use; no writes to 0x14xx / 0x10AC-0x10DC;
# no Func 0x19; no set_configuration. Completion ACK mirrors recorded op 5993
# (W MMR+0x30e0, 2) once 0x3048 shows our slot.
import usb.core, usb.util, time, sys, gzip, json, struct, subprocess, os, threading

VID, PID = 0x0411, 0x0128
HERE = os.path.dirname(os.path.abspath(__file__))
LOG = open(os.path.join(HERE, 'hw25.log'), 'a', buffering=1)
def log(*a):
    s = time.strftime('%H:%M:%S ') + ' '.join(str(x) for x in a)
    print(s); LOG.write(s + '\n')

def throttled(tag):
    try:
        out = subprocess.check_output(['vcgencmd', 'get_throttled'], text=True).strip()
    except Exception as e:
        out = f'ERR {e}'
    log(f'throttled[{tag}]:', out)

dev = usb.core.find(idVendor=VID, idProduct=PID)
assert dev, 'device not found'
# NOTE: no set_configuration (per project rule for reconnects).
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
usb.util.claim_interface(dev, 0)
def W(ep, data, to=3000): return dev.write(ep, data, to)
def R(ep, n, to=3000):
    try: return bytes(dev.read(ep, n, to))
    except usb.core.USBTimeoutError: return b''
def aper_w32(a, v): W(0x0d, b'\x0e\xc0' + struct.pack('<II', a, v))
def aper_r32(a):
    W(0x0d, b'\x0d\xc0' + struct.pack('<I', a)); return struct.unpack('<I', R(0x8d, 4)[:4])[0]
def mmr_r(off):
    W(0x0e, b'\x0f\xc0' + struct.pack('<I', 0x20000000 + off)); return struct.unpack('<I', R(0x8e, 4)[:4])[0]
def mmr_w(off, v): W(0x0e, b'\x2f\x40' + struct.pack('<II', 0x20000000 + off, v))
def set_field(f):
    # hw22-proven form: read-modify-write of MMR 0x43c via the MMR channel,
    # preserving all bits outside the field field (mask 0xFFFF80FF).
    # (hw24/hw25's earlier blind APER write of f<<8 to 0x100004 clobbered the
    # other bits and desynced every APER read: chip id came back 0x228217cc.)
    cur = mmr_r(0x43c); mmr_w(0x43c, (cur & 0xFFFF80FF) | (f << 8))
def rd32(f, off):
    set_field(f); return aper_r32(0x100000 + off)

CTX = 0x88DC            # field-2 offset of phys 0x1088DC
SLOT_IDX = 7
SLOT = 0x1840 + SLOT_IDX * 0x23C0   # 0x11280

def read_ctx(tag):
    d = {}
    for name, off in [('marker_8E24', CTX+0x8E24), ('marker_4B1C', CTX+0x4B1C),
                      ('ctx+0x30', CTX+0x30), ('ctx+0x318', CTX+0x318), ('ctx+0x324', CTX+0x324),
                      ('ctx+0x2408=obj+0x1000', CTX+0x2408), ('ctx+0x4bdc', CTX+0x4BDC),
                      ('obj+0x334', CTX+0x1408+0x334), ('obj+0x808', CTX+0x1408+0x808)]:
        d[name] = rd32(2, off)
    log(tag, ' '.join(f'{k}={v:#010x}' for k, v in d.items()),
        f'band_ff0={rd32(2, 0x37FF0):#x}')
    return d

def read_slot(tag):
    vals = {}
    for name, off in [('+0x10', 0x10), ('+0x1c', 0x1c), ('+0x3c', 0x3c),
                      ('param+0x58', 0x24+0x58), ('param+0x68', 0x24+0x68), ('param+0x84', 0x24+0x84)]:
        vals[name] = rd32(1, SLOT + off)
    log(tag, ' '.join(f'slot{k}={v:#010x}' for k, v in vals.items()),
        f'MMR3048={mmr_r(0x3048):#x} MMR30e0={mmr_r(0x30e0):#x}')
    return vals

# TS drain (continuity check)
ts_stop = False; ts_count = [0]
def ts_drain():
    while not ts_stop:
        try:
            d = dev.read(0x83, 1024 * 188, 200)
            ts_count[0] += len(d)
        except Exception:
            time.sleep(0.02)

log('== hw25 N-024 retry: Func 0x08 type 4, gates param+0x68=1 param+0x84=2 ==')
throttled('start')
_pending = mmr_r(0x30e0)
log(f'startup: 0x30e0={_pending:#x} 0x3048={mmr_r(0x3048):#x} MMR0x43c={mmr_r(0x43c):#x}')
if _pending & 0x3:
    mmr_w(0x30e0, _pending & 0x3); time.sleep(0.5)
    log(f'startup ACK of pending bits done; 0x30e0={mmr_r(0x30e0):#x}')
log('chip id =', hex(aper_r32(0x100000)), '(expect 0x030000b3)')
read_ctx('PRE ctx:')
read_slot('PRE slot:')

ops = json.load(gzip.open(os.path.join(HERE, 'replay_base.json.gz'), 'rt'))
seg = [o for o in ops[5967:5984]]
tmpl = None
for o in seg:
    if o[0] == 'O' and o[2] == 4:
        tmpl = bytearray.fromhex(o[3])
img = bytearray(tmpl)
struct.pack_into('<I', img, 0x1c, SLOT_IDX)
struct.pack_into('<I', img, 0x14, SLOT + 0x24)
struct.pack_into('<I', img, 0x24 + 0x58, 4)        # type 4
struct.pack_into('<I', img, 0x24 + 0x5c, 1)        # bit0 -> constructor
struct.pack_into('<I', img, 0x24 + 0x60, 0x40000)  # embedded descriptor bit
struct.pack_into('<I', img, 0x24 + 0x68, 1)        # opener gate B
struct.pack_into('<I', img, 0x24 + 0x84, 2)        # opener gate C

t = threading.Thread(target=ts_drain, daemon=True); t.start()
ts0 = ts_count[0]; time.sleep(10)
log(f'PRE TS: {ts_count[0]-ts0} bytes in 10s')

log(f'== issuing: slot index {SLOT_IDX} addr {SLOT:#x} ==')
for o in seg:
    kind, dt, ep = o[0], o[1], o[2]
    if kind == 'O':
        data = bytes.fromhex(o[3])
        if ep == 4:
            data = bytes(img)
        elif ep == 0x0d and len(data) >= 10:
            cmd, a, v = struct.unpack('<HII', data[:10])
            if a == 0x194:
                v = 0x10000000 + SLOT
                data = struct.pack('<HII', cmd, a, v) + data[10:]
        W(ep, data)
    else:
        got = R(ep, o[3])
        log(f'  issue I ep={ep:#x} actual={got.hex()} expect={o[4]}')
    if kind == 'O' and ep == 4:  # image just sent; landing check BEFORE doorbell ops
        time.sleep(0.3)
        read_slot('LANDING (pre-doorbell) slot:')
    if dt and dt >= 0.03: time.sleep(min(dt, 1.0))
log('doorbell done; fast polling 40s')
for i in range(80):
    read_slot(f'POST[{i}] slot:')
    if i % 4 == 0:
        read_ctx(f'POST[{i}] ctx:')
    time.sleep(0.5)
# ACK completion if ours (mirrors recorded op 5993); ACK any pending bits
if mmr_r(0x3048) == SLOT:
    mmr_w(0x30e0, 2)
    log('completion ACK written (W 0x30e0=2); 0x30e0 now', hex(mmr_r(0x30e0)))
_pend2 = mmr_r(0x30e0)
if _pend2 & 0x3:
    mmr_w(0x30e0, _pend2 & 0x3)
    log(f'final ACK of pending bits {_pend2 & 0x3:#x}; 0x30e0 now {mmr_r(0x30e0):#x}')

ts0 = ts_count[0]; time.sleep(10)
log(f'POST TS: {ts_count[0]-ts0} bytes in 10s')
ts_stop = True

log('scanning field2 for embedded-descriptor self-ref (ctx+0x318 -> own +0x7a68, desc+0x10==0x14)...')
base = 0x100000
hits = 0
buf = bytearray()
set_field(2)
for off in range(0, 0x100000, 4):
    buf += struct.pack('<I', aper_r32(0x100000 + off))
for off in range(0, len(buf) - 0x7A78, 4):
    p318 = struct.unpack('<I', buf[off+0x318:off+0x31c])[0]
    if p318 and (p318 & 0x1FFFFFFF) == ((base + off + 0x7A68) & 0x1FFFFFFF):
        d10 = struct.unpack('<I', buf[off+0x7A78:off+0x7A7c])[0]
        log(f'  SELFREF phys {base+off:#x}: +0x318={p318:#010x} desc+0x10={d10:#x} '
            f'+0x2408={struct.unpack("<I", buf[off+0x2408:off+0x240c])[0]:#010x} '
            f'+0x4bdc={struct.unpack("<I", buf[off+0x4BDC:off+0x4BE0])[0]:#010x}')
        hits += 1
log('field2 self-ref hits:', hits)
read_ctx('FINAL ctx:')
read_slot('FINAL slot:')
throttled('end')
log('== hw25 done ==')
