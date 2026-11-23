#!/usr/bin/env python3
# Offline simulation of replay_base host writes -> sparse DDR image (page>=1 APER writes only).
# Then hunt the SDEV-object -> return-structure pointer chain (dword at obj+0x11C).
import gzip, json, struct, collections, sys
ops = json.load(gzip.open('replay_base.json.gz', 'rt'))
ddr = {}   # ddr_addr -> dword value (host-written)
page = None
nw = 0
for k, o in enumerate(ops):
    if o[0] != 'O' or o[2] != 14: continue
    data = bytes.fromhex(o[3])
    if len(data) < 6: continue
    opc, addr = struct.unpack('<HI', data[:6])
    if opc == 0x402f and addr == 0x2000043c and len(data) >= 10:
        page = (struct.unpack('<I', data[6:10])[0] >> 8) & 0x7f
    elif opc == 0x402f and 0x10000000 <= addr < 0x10100000 and len(data) >= 10:
        if page is None or page == 0: continue
        v = struct.unpack('<I', data[6:10])[0]
        ddr[(page - 1) * 0x100000 + (addr - 0x10000000)] = v
        nw += 1
print(f'host APER dwords written to DDR: {nw}, distinct addrs: {len(ddr)}')
if ddr:
    print('DDR write range: %#x .. %#x' % (min(ddr), max(ddr)))
    hist = collections.Counter(a >> 20 for a in ddr)
    print('per-MB counts:', dict(sorted(hist.items())))
# candidate: aligned A where dword at A+0x11C is a plausible DDR pointer V (aligned, < 0x2000000),
# and V points into a region the host also wrote (or zeroed) with size >= 0x100
def val(a): return ddr.get(a)
cands = []
for a in list(ddr):
    if a % 4: continue
    v = val(a + 0x11c) if (a + 0x11c) in ddr else None
    if v is None or v % 4 or v >= 0x2000000: continue
    # region around V: count host-written dwords within [V, V+0x100)
    near = sum(1 for x in range(v, v + 0x100, 4) if x in ddr)
    cands.append((a, v, near))
print('pointer-chain candidates (obj, retptr, hostwords near retptr):')
for a, v, near in sorted(cands, key=lambda t: -t[2])[:30]:
    print(f'  obj={a:#x} retptr={v:#x} near={near} obj+0x40={val(a+0x40) if (a+0x40) in ddr else None}')
# also dump all host-written dwords in any region that contains a pointer to itself+0x11c pattern is done;
# print regions summary: contiguous host-written runs >= 16 dwords
addrs = sorted(ddr)
runs = []
start = prev = None
for a in addrs:
    if start is None: start = prev = a; continue
    if a == prev + 4: prev = a; continue
    runs.append((start, prev + 4 - start)); start = prev = a
if start is not None: runs.append((start, prev + 4 - start))
print('host-written runs >= 64B:')
for s, ln in runs:
    if ln >= 64: print(f'  {s:#x} len {ln:#x}')
