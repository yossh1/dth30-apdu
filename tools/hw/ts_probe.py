#!/usr/bin/env python3
# ts_probe: read-only spot check of the TS endpoint (0x83) for the phys-session.
# No writes of any kind, NO set_configuration, no reset (same connection pattern
# as hw21). Reads for --seconds, then reports total bytes, 188-stride sync
# alignment and the scrambled-packet count over the captured stream.
# Usage: ts_probe.py [--seconds 10]
import sys, time, argparse
import usb.core, usb.util

ap = argparse.ArgumentParser()
ap.add_argument('--seconds', type=float, default=10.0)
args = ap.parse_args()

dev = usb.core.find(idVendor=0x0411, idProduct=0x0128)
assert dev is not None, 'device not found'
for i in range(3):
    try:
        if dev.is_kernel_driver_active(i): dev.detach_kernel_driver(i)
    except Exception: pass
for i in range(3):
    try: usb.util.claim_interface(dev, i)
    except Exception: pass

data = bytearray()
err = None
t_end = time.time() + args.seconds
while time.time() < t_end:
    try:
        b = bytes(dev.read(0x83, 0x17800 * 4, timeout=2000))
        data += b
    except Exception as e:
        err = repr(e)
        break
usb.util.dispose_resources(dev)

total = len(data)
print(f'total_bytes={total} seconds={args.seconds} err={err}')
# locate a 188-stride sync alignment: first offset where 10 consecutive
# packet starts are 0x47
off0 = None
for off in range(0, min(188, max(0, total - 188 * 10))):
    if all(data[off + 188 * k] == 0x47 for k in range(10)):
        off0 = off
        break
if off0 is None:
    print('sync_alignment=NOT_FOUND pkts=0 sync_ok=0 scrambled=0')
else:
    pkts = (total - off0) // 188
    sync_ok = 0
    scrambled = 0
    for k in range(pkts):
        p = off0 + 188 * k
        if data[p] == 0x47:
            sync_ok += 1
        if data[p + 3] & 0xC0:
            scrambled += 1
    print(f'sync_alignment=offset {off0} pkts={pkts} sync_ok={sync_ok} scrambled={scrambled}')
