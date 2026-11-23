#!/usr/bin/env python3
# hw19: N-021 - read-only spot dumps of never-dumped DDR regions.
# Current device state: card inserted, session started (Stage B done), firmware
# left running. READ-ONLY except aperture page bits (MMR 0x43C), same pattern
# as hw11/hw14. Do NOT set_configuration, no reset, no replay, no writes to
# candidate MMRs, no Func 0x19.
#
# Phase 0: sanity reads (chip id, MMR baseline, field2 +0x37FF0 state dword).
# Phase 1: field reachability probe: fields 0..127, 8 sample offsets each.
#          Classify per field: error / all-zero / all-ones / mirror-of-lower /
#          unique. Stop expanding after 3 consecutive error fields.
# Phase 2: full 1MB dumps of: field 1, field 3 tail (offsets 0x90000..0x100000
#          = phys 0x290000..0x300000), every field >=4 whose probe vector is
#          unique, plus the first uniform (all-zero/all-ones) field >=4 as a
#          full-window uniformity check. Files: spot_f<f>_<HHMMSS>.bin,
#          spot_f3tail_<HHMMSS>.bin in the lab dir.
# Restores aperture field 0 at the end (and on error).
import sys, time, struct, os
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
LOGF = open(os.path.join(HERE, 'hw19.log'), 'a', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, flush=True)

dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None, 'device not found'
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
for i in range(3):
    try: usb.util.claim_interface(dev, i)
    except Exception: pass
MMR, APER = 0x20000000, 0x10000000
def W(a, v): dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
def R(a):
    dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
    return struct.unpack('<I', bytes(dev.read(0x8e, 4, timeout=2000)))[0]
def set_field(f):
    cur = R(MMR + 0x43c); W(MMR + 0x43c, (cur & 0xFFFF80FF) | (f << 8))
def dump_range(path, field, start, size):
    set_field(field)
    with open(path, 'wb') as fo:
        for off in range(start, start + size, 4):
            fo.write(struct.pack('<I', R(APER + off)))

TS = time.strftime('%H%M%S')
try:
    # ---- Phase 0: sanity ----
    chip = R(MMR + 0x478)
    m1420 = R(MMR + 0x1420); m1450 = R(MMR + 0x1450)
    set_field(2); st_ff0 = R(APER + 0x37FF0); st_fd8 = R(APER + 0x37FD8)
    set_field(0)
    log('phase0 chip=%08x 1420=%08x 1450=%08x field2+0x37FF0=%d +0x37FD8=%08x'
        % (chip, m1420, m1450, st_ff0, st_fd8))

    # ---- Phase 1: probe fields 0..127 ----
    PROBE_OFFS = [0x0, 0x40, 0x1000, 0x10000, 0x40000, 0x80000, 0xF0000, 0xFF000]
    vectors = {}   # field -> tuple(values) or 'ERR'
    consec_err = 0
    max_field = 127
    for f in range(0, 128):
        try:
            set_field(f)
            vec = tuple(R(APER + o) for o in PROBE_OFFS)
            vectors[f] = vec
            consec_err = 0
        except Exception as e:
            vectors[f] = 'ERR'
            consec_err += 1
            log('probe field %d ERROR %r (consec %d)' % (f, e, consec_err))
            if f >= 4 and consec_err >= 3:
                max_field = f
                log('probe stop: 3 consecutive error fields at %d' % f)
                break
    set_field(0)
    # classify
    seen = {}
    cls = {}
    for f in sorted(vectors):
        v = vectors[f]
        if v == 'ERR':
            cls[f] = 'error'
        elif all(x == 0 for x in v):
            cls[f] = 'all-zero(sampled)'
        elif all(x == 0xFFFFFFFF for x in v):
            cls[f] = 'all-ones(sampled)'
        elif v in seen:
            cls[f] = 'mirror-of-%d' % seen[v]
        else:
            seen[v] = f
            cls[f] = 'unique'
    log('phase1 probe done, fields probed 0..%d' % max_field)
    for f in sorted(cls):
        v = vectors[f]
        vs = ' '.join('%08x' % x for x in v) if v != 'ERR' else 'ERR'
        log('  field %3d %-18s %s' % (f, cls[f], vs))

    # ---- Phase 2: full dumps ----
    todo = []
    todo.append(('spot_f1_%s.bin' % TS, 1, 0, 0x100000))
    todo.append(('spot_f3tail_%s.bin' % TS, 3, 0x90000, 0x70000))
    first_uniform = None
    for f in range(4, max_field + 1):
        c = cls.get(f, 'error')
        if c == 'unique':
            todo.append(('spot_f%d_%s.bin' % (f, TS), f, 0, 0x100000))
        elif c.startswith('all-') and first_uniform is None:
            first_uniform = f
            todo.append(('spot_f%d_%s.bin' % (f, TS), f, 0, 0x100000))
    for name, f, start, size in todo:
        t0 = time.time()
        dump_range(os.path.join(HERE, name), f, start, size)
        log('dumped %s (field %d, off %#x, %d bytes) in %.1fs' % (name, f, start, size, time.time() - t0))
    set_field(0)
    log('hw19 done')
except Exception as e:
    log('hw19 FATAL', repr(e))
    try: set_field(0)
    except Exception: pass
    raise
