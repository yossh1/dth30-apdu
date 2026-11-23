#!/usr/bin/env python3
# spot7: READ-ONLY focused dump of the FIRST freelist entries (this boot's
# own frees sit at the head; deeper entries may be cross-boot ghosts in
# DDR). For each of the first N header blocks: header +0x00/+0x08/+0x0C and
# the data block's job/request signature fields. A data block is a
# candidate ex-job if +0x2C looks like a callback VA (or 0) and +0x24
# points at another pool data block; a candidate ex-request if +0x80 is a
# plausible INS byte, +0x84 a short length, +0x88 in {0,1,2}, +0x8C a VA.
# The decisive fields: job data+0x18 and request data+0x8C when their phys
# is the ctx (0x2BD010) -- the raw stored alias is the stock submit form.
# Ghost guard: the exp2 Mode Q job had callback 0xA011E3F0 (inside the
# cave); any block with +0x2C == 0xA011E3F0 is OUR exp2 ghost, not stock.
# No writes except the aperture field selector (restored to 0).
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

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
pool_va = aper_r(0x22700C)
pp = pool_va & 0x1FFFFFFF
cur = aper_r(pp + 0x00)
print(f'pool {pool_va:#010x}, freelist head {cur:#010x}; dumping first {N} entries')
for i in range(N):
    if not plausible(cur):
        print(f'[{i}] head implausible: {cur:#x}; stop'); break
    bp = cur & 0x1FFFFFFF
    nxt = aper_r(bp + 0x00); data = aper_r(bp + 0x08); magic = aper_r(bp + 0x0C)
    print(f'[{i}] hdr {cur:#010x} magic {magic:#010x} next {nxt:#010x} data {data:#010x}')
    if plausible(data):
        dp = data & 0x1FFFFFFF
        job = {off: aper_r(dp + off) for off in (0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x2C)}
        req = {off: aper_r(dp + off) for off in (0x80, 0x84, 0x88, 0x8C)}
        print('     job-sig: ' + ' '.join(f'+{off:#04x}={job[off]:#010x}' for off in job))
        print('     req-sig: ' + ' '.join(f'+{off:#04x}={req[off]:#010x}' for off in req))
        tags = []
        if job[0x2C] == 0xA011E3F0: tags.append('GHOST=exp2 modeq job (our callback)')
        if (job[0x18] & 0x1FFFFFFF) == 0x2BD010: tags.append(f"JOB-CTX form={'KSEG1' if job[0x18] >> 28 == 0xA else 'KSEG0' if job[0x18] >> 28 == 0x8 else 'OTHER'}")
        if (req[0x8C] & 0x1FFFFFFF) == 0x2BD010: tags.append(f"REQ-CTX form={'KSEG1' if req[0x8C] >> 28 == 0xA else 'KSEG0' if req[0x8C] >> 28 == 0x8 else 'OTHER'}")
        print('     tags:', tags if tags else '-')
    cur = nxt
set_field(0)
print('spot7 done (read-only)')
