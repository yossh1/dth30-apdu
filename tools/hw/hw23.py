#!/usr/bin/env python3
# hw23: faithful poller reproduction for N-031 / design B.1 (N-029 read set).
# Reproduces the Windows driver's mailbox poller (BufFsUSB 0x1A5C2) read set:
#   status = MMR 0x30E0, mask = MMR 0x30E4
#   bit1 (command response, consumer 0x1A388): read MMR 0x3048 (completed slot
#     DDR address), then slot +0x1C and slot +0x10 via APER. That is ALL the
#     consumer reads; the slot body is additionally dumped to a lab-local bin
#     file (read-only observation) when a new completed slot appears.
#   bit0 (unsolicited message, handler 0x1897C): read MMR 0x3028 (type value),
#     MMR 0x3040 (slot DDR address), then 0x24 bytes (9 dword) at the slot
#     via APER.
#   ACK: write the bit value (2 for bit1, 1 for bit0) to MMR 0x30E0, exactly
#     the driver's known doorbell semantics (design B.1: recorded-replay form).
# Writes are limited to MMR 0x30E0 (values 1/2 only) and the aperture field
# bits (MMR 0x43C, restored to field 0 after every read and on exit).
# NO writes to candidate card-controller MMRs, NO set_configuration, NO reset.
# All raw output (poller.jsonl, poller_slot_*.bin) stays in the lab dir.
# Usage: hw23.py [--seconds 180] [--interval 0.1]
import sys, time, struct, os, json, argparse
import usb.core, usb.util
HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--seconds', type=float, default=180.0)
ap.add_argument('--interval', type=float, default=0.1)
args = ap.parse_args()
LOGF = open(os.path.join(HERE, 'poller.log'), 'w', buffering=1)
OUTF = open(os.path.join(HERE, 'poller.jsonl'), 'w', buffering=1)
def log(*a):
    s = ' '.join(str(x) for x in a); LOGF.write(time.strftime('%H:%M:%S ') + s + '\n'); print(s, file=sys.stderr, flush=True)
def rec(d):
    d.setdefault('t', time.time()); d.setdefault('wall', time.strftime('%H:%M:%S'))
    OUTF.write(json.dumps(d) + '\n')

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
def read_ddr(addr, ndw):
    # aperture convention (hw19): field 0 = shared 64KB; field N>=1 maps
    # DDR (N-1)*1MB .. N*1MB. Restore field 0 afterwards.
    if addr < 0x10000:
        f, off = 0, addr
    else:
        f, off = (addr >> 20) + 1, addr & 0xFFFFF
    try:
        set_field(f)
        return [R(APER + off + 4 * i) for i in range(ndw)]
    finally:
        try: set_field(0)
        except Exception: pass

log('chip =', hex(R(MMR + 0x478)), f'hw23 poller start seconds={args.seconds} interval={args.interval}')
t_end = time.time() + args.seconds
handled = set()
n_polls = 0; n_events = 0; last_hb = 0.0
try:
    while time.time() < t_end:
        t0 = time.time()
        try:
            st = R(MMR + 0x30E0); mask = R(MMR + 0x30E4); eff = st & mask
            n_polls += 1
            if t0 - last_hb >= 10.0:
                rec({'kind': 'heartbeat', 'status': st, 'mask': mask, 'eff': eff, 'polls': n_polls})
                last_hb = t0
            if eff & 2:
                slot = R(MMR + 0x3048)
                sig = ('bit1', slot)
                if sig not in handled:
                    handled.add(sig); n_events += 1
                    ev = {'kind': 'bit1_completed', 'status': st, 'slot_addr': slot}
                    if slot:
                        ev['slot_1c'] = read_ddr(slot + 0x1C, 1)[0]
                        ev['slot_10'] = read_ddr(slot + 0x10, 1)[0]
                        sig2 = ('slotbody', slot, ev['slot_1c'])
                        if sig2 not in handled:
                            handled.add(sig2)
                            body = read_ddr(slot, 0x23C0 // 4)
                            fn = os.path.join(HERE, 'poller_slot_%08x.bin' % slot)
                            with open(fn, 'wb') as bf:
                                bf.write(struct.pack('<%dI' % len(body), *body))
                            ev['slot_body_file'] = os.path.basename(fn)
                            ev['slot_body_nonzero'] = sum(1 for v in body if v != 0)
                    rec(ev); log('bit1 completed slot=%08x' % slot)
                W(MMR + 0x30E0, 2)  # driver ACK semantics: write bit value
            if eff & 1:
                typ = R(MMR + 0x3028); slot = R(MMR + 0x3040)
                sig = ('bit0', typ, slot)
                if sig not in handled:
                    handled.add(sig); n_events += 1
                    ev = {'kind': 'bit0_unsolicited', 'status': st, 'type': typ, 'slot_addr': slot}
                    if slot:
                        ev['slot_24b'] = ['%08x' % v for v in read_ddr(slot, 9)]
                    rec(ev); log('bit0 unsolicited type=%d slot=%08x' % (typ, slot))
                W(MMR + 0x30E0, 1)  # driver ACK semantics: write bit value
        except Exception as e:
            rec({'kind': 'error', 'error': repr(e)})
            log('poll ERROR', repr(e))
            time.sleep(0.5)
        dt = args.interval - (time.time() - t0)
        if dt > 0: time.sleep(dt)
finally:
    try: set_field(0)
    except Exception: pass
rec({'kind': 'end', 'polls': n_polls, 'events': n_events})
log(f'hw23 poller end: polls={n_polls} events={n_events}')
