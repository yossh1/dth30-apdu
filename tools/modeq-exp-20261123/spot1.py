#!/usr/bin/env python3
# spot1: READ-ONLY spot reads of the wedged modeq firmware state.
# No writes except the aperture field selector (restored to 0 at the end)
# and the standard EP0x0e read requests. No doorbell, no reset.
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
# PEND area in cave: phys 0x11E4A0 (field1 0x1E4A0), DATA_OFF=0x268
print('PEND dwords:', [hex(aper_r(0x11E4A0 + 4 * i)) for i in range(2)])
# handler entry bytes still intact?
print('cave first dwords:', [hex(aper_r(0x11E238 + 4 * i)) for i in range(4)])
# globals (phys = VA - 0x80000000): state-ptr 0x237050, pool-ptr 0x23700C, ctx anchor 0x253308
sp = aper_r(0x237050)
print('state-ptr global *(0x80237050):', hex(sp))
print('pool-ptr global *(0x8023700C):', hex(aper_r(0x23700C)))
if sp:
    sph = sp & 0x1FFFFF  # phys within aperture reach if KSEG0/KSEG1 alias of DDR
    print('state+0x118 (gate flags):', hex(aper_r((sp & 0xFFFFFF) + 0x118)) if (sp & 0xFFFFFF) < 0x3F00000 else 'out of reach')
head = aper_r(0x253308)
print('ctx anchor *(0x80253308) head:', hex(head))
node = head
for i in range(6):
    if node == 0x80253308 or node == 0:
        print(f'  node[{i}] = sentinel/null {hex(node)}'); break
    nphys = node & 0xFFFFFF
    if nphys >= 0x3F00000:
        print(f'  node[{i}] = {hex(node)} out of reach'); break
    nxt = aper_r(nphys); f30 = aper_r(nphys + 0x30)
    print(f'  node[{i}] va={hex(node)} next={hex(nxt)} +0x30={f30:#010x} bit0x10={bool(f30 & 0x10)}')
    node = nxt
set_field(0)
print('spot1 done (read-only)')
