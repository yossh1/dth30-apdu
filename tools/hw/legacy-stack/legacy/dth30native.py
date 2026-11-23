# dth30native: standalone DT-H30/U2 TS capture on Linux (runs on 検証ホスト, pyusb only).
# Replays the USB op list recorded from the vendor driver stack (mkreplay.py), then
# streams TS passthrough from EP 0x83.
# usage: dth30native.py replay.json.gz <seconds> <out.ts> [speed]
#   speed: divide recorded inter-op delays by this factor (default 1 = as recorded)
import gzip, json, sys, time, subprocess, struct, os
import usb.core, usb.util

ops = json.load(gzip.open(sys.argv[1], 'rt'))
secs, out = float(sys.argv[2]), sys.argv[3]
speed = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0

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

import threading
drain_stats = {}
def drain(ep, n):
    while True:
        try:
            b = dev.read(ep, n, timeout=1000); drain_stats[ep] = drain_stats.get(ep, 0) + len(b)
        except usb.core.USBTimeoutError: continue
        except Exception as e:
            print(f'drain {ep:#x} stopped: {e}', file=sys.stderr); return
MINDT = float(os.environ.get('DTH30_MINDT', '0'))
dev = None; mism = 0; t0 = time.time(); mlog = open('/tmp/dth30_mismatch.log', 'w')
for k, o in enumerate(ops):
    kind = o[0]
    if kind == 'S':
        threading.Thread(target=drain, args=(o[2], o[3]), daemon=True).start(); continue
    if kind == 'P':
        subprocess.run(['/root/usbcycle.sh', '3'], check=False); time.sleep(1); dev = find(); continue
    dt = o[1] / speed
    if dt < MINDT: dt = 0
    if dt > 0.0005: time.sleep(dt)
    if dev is None: dev = find()
    if kind == 'C':
        dev.set_configuration(1)
        for i in range(3):
            try: usb.util.claim_interface(dev, i)
            except Exception: pass
    elif kind == 'D':
        dev.ctrl_transfer(0x80, 6, (o[2] << 8) | o[3], 0, o[4])
    elif kind == 'X':
        rt, req, val, idx, data, ln = o[2:8]
        if rt & 0x80: dev.ctrl_transfer(rt, req, val, idx, ln)
        else: dev.ctrl_transfer(rt, req, val, idx, bytes.fromhex(data))
    elif kind == 'O':
        dev.write(o[2], bytes.fromhex(o[3]), timeout=5000)
    elif kind == 'I':
        d = bytes(dev.read(o[2], o[3], timeout=5000))
        if o[4] is not None and d.hex() != o[4]:
            mism += 1; mlog.write(f'{k} ep{o[2]:#x} exp {o[4]} got {d.hex()} prev {ops[k-1][3][:20] if ops[k-1][0]=="O" else ""}\n'); mlog.flush()
    elif kind == 'Q':                             # poll a register until the recorded final value
        _, _, epo, req, epi, final, tmo = o
        tq = time.time() + tmo; n = 0
        while True:
            dev.write(epo, bytes.fromhex(req), timeout=5000)
            d = bytes(dev.read(epi, 4, timeout=5000)); n += 1
            if final is None or d.hex() == final or time.time() > tq: break
        if final is not None and d.hex() != final:
            mism += 1; mlog.write(f'{k} POLL timeout req {req} exp {final} got {d.hex()} after {n}\n'); mlog.flush()
    elif kind == 'R':
        try: dev.reset()
        except Exception: pass
        dev = find()
print(f'replay done: {len(ops)} ops in {time.time() - t0:.0f}s, read mismatches {mism}', file=sys.stderr)

# TS passthrough streaming: keep several reads in flight via a reader thread
import threading, queue
RDSZ = int(os.environ.get("DTH30_RDSZ", str(0x17800 * 4)))
qd = queue.Queue(maxsize=256); stop = threading.Event()
def reader():
    while not stop.is_set():
        try: qd.put(bytes(dev.read(0x83, RDSZ, timeout=2000)))
        except usb.core.USBTimeoutError: continue
        except Exception as e: print('read error', e, file=sys.stderr); break
th = threading.Thread(target=reader, daemon=True); th.start()
f = open(out, 'wb'); total = 0; t1 = time.time()
while time.time() - t1 < secs:
    try: b = qd.get(timeout=1)
    except queue.Empty: continue
    f.write(b); total += len(b)
stop.set(); f.close()
print('drained', {hex(k): v for k, v in drain_stats.items()}, file=sys.stderr)
print(f'TS: {total} bytes in {secs:.0f}s = {total * 8 / secs / 1e6:.2f} Mbps', file=sys.stderr)
sys.stderr.flush(); import os; os._exit(0)
