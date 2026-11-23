#!/usr/bin/env python3
# spot6: READ-ONLY pool forensics for SECOND-ISSUE plan 2.
# This stock boot already submitted and tore down stock jobs (session-start
# INITIAL_SETTING at minimum). Their descriptors were freed to the job pool
# (pool descriptor VA 0xA022F254; freelist head at pool+0x00; each free
# header block's +0x00 = next free header, +0x08 = data block pointer --
# alloc @0xA0154854 pops *(pool+0) and returns *(block+8)). free() does not
# rewrite the job/request payload fields (+0x18 ctx in a job descriptor,
# +0x8C ctx in a request object), so a freed stock job/request still shows
# the exact alias form stock submit stored.
# Scan: walk the freelist (<= 512 headers), for each data block check
#   data+0x18 phys == 0x2BD010 (ctx)  -> ex-job descriptor witness
#   data+0x8C phys == 0x2BD010 (ctx)  -> ex-request object witness
# and report the raw stored values (alias form) plus neighbouring fields.
# Also reads the trace page: if this boot's session-start teardown had hit
# check B, record [1] would be 0x8018276C.
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

CTX_PH = 0x2BD010
print('trace page:', [hex(aper_r(0x530 + 4 * i)) for i in range(8)])
pool_va = aper_r(0x22700C)
print(f'pool-ptr = {pool_va:#010x}')
pp = pool_va & 0x1FFFFFFF
print('pool desc:', {f'+{off:#04x}': hex(aper_r(pp + off)) for off in (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14)})
head = aper_r(pp + 0x00)
seen_blocks = set()
job_wit, req_wit = [], []
n = 0
cur = head
while plausible(cur) and n < 512:
    bp = cur & 0x1FFFFFFF
    if bp in seen_blocks: break
    seen_blocks.add(bp)
    nxt = aper_r(bp + 0x00)
    data = aper_r(bp + 0x08)
    magic = aper_r(bp + 0x0C)
    n += 1
    if plausible(data):
        dp = data & 0x1FFFFFFF
        v18 = aper_r(dp + 0x18)
        if (v18 & 0x1FFFFFFF) == CTX_PH:
            f = {off: aper_r(dp + off) for off in (0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24, 0x2C)}
            job_wit.append((data, f))
            print(f'JOB witness data@{data:#010x} (hdr {cur:#010x} magic {magic:#010x}): ' +
                  ' '.join(f'+{off:#04x}={f[off]:#010x}' for off in f))
        v8c = aper_r(dp + 0x8C)
        if (v8c & 0x1FFFFFFF) == CTX_PH:
            f = {off: aper_r(dp + off) for off in (0x80, 0x84, 0x88, 0x8C)}
            req_wit.append((data, f))
            print(f'REQ witness data@{data:#010x} (hdr {cur:#010x} magic {magic:#010x}): ' +
                  ' '.join(f'+{off:#04x}={f[off]:#010x}' for off in f))
    cur = nxt
set_field(0)
print(f'freelist walked: {n} header blocks; job witnesses: {len(job_wit)}, request witnesses: {len(req_wit)}')
def form(v): return 'KSEG1' if (v >> 28) == 0xA else ('KSEG0' if (v >> 28) == 0x8 else 'OTHER')
for data, f in job_wit:
    print(f'job+0x18 = {f[0x18]:#010x} [{form(f[0x18])}], job+0x1C (prev) = {f[0x1C]:#010x}, job+0x20 (next) = {f[0x20]:#010x}')
for data, f in req_wit:
    print(f'req+0x8C = {f[0x8C]:#010x} [{form(f[0x8C])}]')
print('spot6 done (read-only)')
