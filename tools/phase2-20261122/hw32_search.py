#!/usr/bin/env python3
# hw32: read-only aperture search. Firmware running; no reset/config.
# 1) header page check at field 1 offset 0 (image stub / vector table).
# 2) dump field 2 offsets [0, 0x27000) and save for payload comparison.
import sys, time, struct, os
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

print('chip =', hex(R(MMR + 0x478)), '0x3028 =', R(MMR + 0x3028))
try:
    set_field(1)
    hdr = b''.join(struct.pack('<I', R(APER + 4 * i)) for i in range(96))
    print('field1[0:384] =', hdr[:64].hex())
    print('field1 vec count @0x110 =', struct.unpack('<I', hdr[0x110:0x114])[0] if len(hdr) >= 0x114 else 'n/a')
    set_field(2)
    out = bytearray()
    t0 = time.time()
    for off in range(0, 0x27000, 4):
        out += struct.pack('<I', R(APER + off))
    print(f'field2 dump 0x27000 bytes in {time.time()-t0:.1f}s')
    open('/srv/dth30-lab/f2_head_dump.bin', 'wb').write(bytes(out))
    s = bytes(out)
    print('string ViXS in field2 dump at', s.find(b'ViXS AAC encode'))
    print('payload head (e0ffb1ff...) at', s.find(bytes.fromhex('e0ffb1ff64fffdfe')))
finally:
    try: set_field(0)
    except Exception: pass
print('done')
