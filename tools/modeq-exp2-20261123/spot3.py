#!/usr/bin/env python3
# spot3: READ-ONLY diagnostics of the post-issue-#2 wedged patched state.
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

print('chip', hex(R(MMR + 0x478)))
for a in (0x3028, 0x3020, 0x302c, 0x3030, 0x3048, 0x30e0):
    print(f'MMR {a:#x} = {R(MMR + a):#010x}')
print('trace page:', [hex(aper_r(0x530 + 4 * i)) for i in range(8)])
SLOT = 0x1840
print('slot hdr:', [hex(aper_r(SLOT + 4 * i)) for i in range(8)])
print('slot+0x40 dword:', hex(aper_r(SLOT + 0x40)))
# PEND at cave DATA_OFF=0x290: phys 0x11E238+0x290 = 0x11E4C8
print('PEND dwords:', [hex(aper_r(0x11E4C8 + 4 * i)) for i in range(2)])
print('cave first dwords:', [hex(aper_r(0x11E238 + 4 * i)) for i in range(4)])
sp = aper_r(0x227050)
print('state-ptr *(0x80227050):', hex(sp))
print('pool-ptr *(0x8022700C):', hex(aper_r(0x22700C)))
if sp:
    sph = sp & 0x1FFFFFFF
    for off in (0x110, 0x114, 0x118, 0x12C, 0x130, 0x134):
        print(f'state+{off:#x}:', hex(aper_r(sph + off)))
head = aper_r(0x253308)
print('ctx anchor head:', hex(head))
set_field(0)
print('spot3 done (read-only)')
