#!/usr/bin/env python3
# hw30: read-only APER calibration probe (firmware running). Uses hw1's
# set_page/aper_r32 addressing exactly. No reset, no set_configuration.
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
def set_page(p):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | ((p + 1) << 8))
def aper_r32(ddr):
    set_page(ddr >> 20)
    return R(APER + (ddr & 0xFFFFF))
def aper_read(ddr, n):
    out = b''
    for i in range(0, n, 4):
        out += struct.pack('<I', aper_r32(ddr + i))
    return out

print('chip id MMR 0x478 =', hex(R(MMR + 0x478)), ' 0x3028 =', R(MMR + 0x3028))
for base, n, label in [(0x100000, 64, 'image header page (DDR 0x100000)'),
                       (0x21BB80, 64, 'target string region (DDR 0x21BB80)'),
                       (0x137FD0, 48, 'band area (DDR 0x137FD0; +0x37FF0 dword at +0x20)')]:
    raw = aper_read(base, n)
    asc = ''.join(chr(c) if 32 <= c < 127 else '.' for c in raw)
    print(f'{label}: {raw.hex()}')
    print(f'   ascii: {asc}')
print('band +0x37FF0 (DDR 0x137FF0) =', aper_r32(0x137FF0), ' +0x37FD8 =', hex(aper_r32(0x137FD8)))
