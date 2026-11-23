#!/usr/bin/env python3
# spot5: READ-ONLY follow-up probe after spot4 found the session slot table
# empty post-replay. Three parts:
#  A. Persistent reads needing no live job: the handler's ctx (anchor head)
#     *(ctx+0x14) -- the check-B gate value when prev is the head -- and the
#     ctx head self-links ctx+0x28 / ctx+0x2C (which alias the firmware
#     itself wrote there is corroborating evidence for the canonical form).
#  B. Full dump of the session object (0x80 words from its base) to check
#     for job pointers anywhere in the slot-table area.
#  C. 30 s activity monitor: state NS/NR/RX, session bitmap, ctx+0x2C and
#     slot[0..3] sampled every ~200 ms; any change is logged. This decides
#     whether stock jobs flow autonomously after the replay ends.
# No writes except the aperture field selector (restored to 0) and the
# standard EP0x0e read requests.
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
def plausible(va):
    return va != 0 and (va >> 29) in (4, 5) and (va & 0x1FFFFFFF) < 0x3F00000 and (va & 3) == 0
def s32(v): return struct.unpack('<i', struct.pack('<I', v))[0]

print('chip', hex(R(MMR + 0x478)), 'MMR 0x3028', hex(R(MMR + 0x3028)))
# --- A. ctx persistent reads
ctx_va = aper_r(0x253308)
print(f'ctx anchor head = {ctx_va:#010x}')
cp = ctx_va & 0x1FFFFFFF
gate = aper_r(cp + 0x14)
print(f'*(ctx+0x14) = {gate:#010x} (signed {s32(gate)}); gate >= 0 (check B can fire with prev=head): {s32(gate) >= 0}')
for off in (0x28, 0x2C, 0x30, 0x3C):
    print(f'  ctx+{off:#04x} = {aper_r(cp + off):#010x}')
# --- B. session dump
sess_va = aper_r(0x226F68)
sp = sess_va & 0x1FFFFFFF
print(f'session = {sess_va:#010x}; dump +0x00..+0x7C:')
for base in range(0x00, 0x80, 0x10):
    print('  +' + f'{base:02x}: ' + ' '.join(f'{aper_r(sp + base + 4 * i):08x}' for i in range(4)))
# --- C. activity monitor
state_ph = 0x237ED8
def snapshot():
    return {
        'NS': aper_r(state_ph + 0x110), 'NR': aper_r(state_ph + 0x114),
        'RX0': aper_r(state_ph + 0x130), 'RX1': aper_r(state_ph + 0x134),
        'bitmap': aper_r(sp + 0x0C), 'ctx_next': aper_r(cp + 0x2C),
        'slots': tuple(aper_r(sp + 0x1C + 4 * i) for i in range(4)),
    }
prev = snapshot()
print('monitor start:', {k: (hex(v) if not isinstance(v, tuple) else [hex(x) for x in v]) for k, v in prev.items()})
t_end = time.time() + 30
changes = 0
while time.time() < t_end:
    cur = snapshot()
    if cur != prev:
        changes += 1
        diff = {k: (prev[k], cur[k]) for k in cur if cur[k] != prev[k]}
        print(f'{time.strftime("%H:%M:%S")} CHANGE:', {k: ([hex(x) for x in v[0]], [hex(x) for x in v[1]]) if isinstance(v[0], tuple) else (hex(v[0]), hex(v[1])) for k, v in diff.items()})
        for s in cur['slots']:
            if plausible(s):
                jp = s & 0x1FFFFFFF
                f = {off: aper_r(jp + off) for off in (0x08, 0x0C, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x2C)}
                print(f'  job @{s:#010x}: ' + ' '.join(f'+{off:#04x}={f[off]:#010x}' for off in f))
        prev = cur
    time.sleep(0.2)
set_field(0)
print(f'monitor done: {changes} change events in 30 s')
print('spot5 done (read-only)')
