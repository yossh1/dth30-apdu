#!/usr/bin/env python3
# spot2: READ-ONLY pre-flight check for Mode Q round 2 (GLOBALS-FIX.md).
# Run against a HEALTHY STOCK boot after Stage B (session established),
# BEFORE any patched boot. Implements pre-flight items 1-5:
#   1. *(0x80227050) == 0xA0237ED8 (state-ptr global, exact)
#   2. state+0x118 bit1 set; NS/NR (+0x110/+0x114) small; +0x130/+0x134 <= 0x200
#   3. *(0x8022700C) == 0xA022F254 (pool-ptr global, exact); pool desc words sane
#   4. negative control: *(0x80237050)==0x2B75AAC9, *(0x8023700C)==0x2B55A2C9
#   5. ctx anchor *(0x80253308): head != anchor, node +0x30 bit 0x10 set
# No writes except the aperture field selector (restored to 0 at the end)
# and the standard EP0x0e read requests. No doorbell, no reset, no Func.
import sys, time, struct
import usb.core, usb.util

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

dev = find()
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def aper_r(phys):
    set_field(phys >> 20); return R(APER + (phys & 0xFFFFF))

results = []
def chk(label, cond, val):
    results.append(bool(cond))
    print(f'{"PASS" if cond else "FAIL"}  {label}: {val}')

print('chip', hex(R(MMR + 0x478)), 'MMR 0x3028', hex(R(MMR + 0x3028)))
# 1. state-ptr global (VA 0x80227050 -> phys 0x227050)
sp = aper_r(0x227050)
chk('1 state-ptr *(0x80227050)==0xA0237ED8', sp == 0xA0237ED8, hex(sp))
# 2. state struct sanity (phys 0x237ED8)
if sp == 0xA0237ED8:
    sph = sp & 0x1FFFFFFF
    g118 = aper_r(sph + 0x118)
    chk('2a state+0x118 bit1 set', g118 & 2, hex(g118))
    ns = aper_r(sph + 0x110); nr = aper_r(sph + 0x114)
    chk('2b NS/NR < 0x100', ns < 0x100 and nr < 0x100, f'NS={ns:#x} NR={nr:#x}')
    rx0 = aper_r(sph + 0x130); rx1 = aper_r(sph + 0x134)
    chk('2c RX fill/done <= 0x200', rx0 <= 0x200 and rx1 <= 0x200, f'{rx0:#x}/{rx1:#x}')
else:
    print('SKIP 2a-2c (state-ptr mismatch)')
    results += [False, False, False]
# 3. pool-ptr global (VA 0x8022700C -> phys 0x22700C)
pp = aper_r(0x22700C)
chk('3a pool-ptr *(0x8022700C)==0xA022F254', pp == 0xA022F254, hex(pp))
if pp == 0xA022F254:
    pph = pp & 0x1FFFFFFF
    p0 = aper_r(pph); p14 = aper_r(pph + 0x14)
    def va_ok(v): return v == 0 or ((v >> 29) in (4, 5) and (v & 0x1FFFFFFF) < 0x3F00000)
    chk('3b pool desc +0x00/+0x14 sane', va_ok(p0) and va_ok(p14), f'{p0:#x}/{p14:#x}')
else:
    print('SKIP 3b (pool-ptr mismatch)')
    results.append(False)
# 4. negative control at the OLD (wrong) addresses
o1 = aper_r(0x237050)
chk('4a negative *(0x80237050)==0x2B75AAC9', o1 == 0x2B75AAC9, hex(o1))
o2 = aper_r(0x23700C)
chk('4b negative *(0x8023700C)==0x2B55A2C9', o2 == 0x2B55A2C9, hex(o2))
# 5. ctx anchor (VA 0x80253308 -> phys 0x253308)
head = aper_r(0x253308)
ok5 = head not in (0, 0x80253308)
detail = f'head={head:#x}'
if ok5:
    f30 = aper_r((head & 0x1FFFFFFF) + 0x30)
    ok5 = bool(f30 & 0x10)
    detail += f' node+0x30={f30:#010x} bit0x10={bool(f30 & 0x10)}'
chk('5 ctx anchor head + bit0x10 node', ok5, detail)
set_field(0)
print('PREFLIGHT OVERALL:', 'PASS' if all(results) else 'FAIL', f'({sum(results)}/{len(results)})')
print('spot2 done (read-only)')
sys.exit(0 if all(results) else 1)
