#!/usr/bin/env python3
# dth30d: DT-H30/U2 tuner daemon for 検証ホスト.
# Boots the device once (vendor USB sequence replay, see dth30rec.py), keeps TS passthrough
# (EP 0x83) running, and retunes in place via the island I2C engine on request.
# Clients: unix socket /run/dth30.sock and TCP :40780. Protocol: send "<ch>\n", then read TS
# until you close the connection. One client at a time (single tuner); a busy tuner answers
# nothing and closes.
import os, sys, time, json, gzip, socket, struct, threading, queue, signal, selectors
import usb.core
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dth30rec as R

SOCK = '/run/dth30.sock'
DEBUG = os.environ.get('DTH30_DEBUG') == '1'
_dbg = open('/run/dth30_debug.log', 'a', buffering=1) if DEBUG else None
def dbg(msg):
    if _dbg: _dbg.write(f'{time.time():.3f} {msg}\n')
TCP_PORT = int(os.environ.get('DTH30_PORT', '40780'))
SEQ = json.load(open(os.path.join(R.HERE, 'classA_seq.json')))

class Tuner:
    def __init__(self):
        self.lock = threading.Lock()
        self.dev = None; self.ch = None
        self.subs = None             # queue of the current client, or None
        self.booted = threading.Event()
        self.discard_until = 0; self.discard_bytes = 0

    # ---- RPCI (writes are not answered, reads are) ----
    def W(self, a, v): self.dev.write(0x0e, struct.pack('<HII', 0x402f, a, v), timeout=2000)
    def R(self, a):
        self.dev.write(0x0e, struct.pack('<HI', 0x403f, a), timeout=2000)
        return struct.unpack('<I', bytes(self.dev.read(0x8e, 4, timeout=2000)))[0]

    def i2c_write(self, devaddr, payload):
        B = 0x20000000
        for i in range(0, len(payload), 4):
            self.W(B + 0x1004, struct.unpack('<I', (bytes(payload[i:i + 4]) + bytes(4))[:4])[0])
        self.W(B + 0x1000, 0x01060067)                      # 400 kHz, as the vendor filter
        self.W(B + 0x100C, ((devaddr & 0xFE) << 15) | (1 << 12) | (1 << 9) | (1 << 8) | len(payload))
        t = time.time() + 0.5
        while True:
            s = self.R(B + 0x1094)
            if s & 0x40: break
            if time.time() > t: return False
        self.W(B + 0x1094, 0x00300040); self.W(B + 0x1094, 0x80)
        return (s & 0x300000) == 0

    def demod_read(self, reg, n=1):
        B = 0x20000000
        if not self.i2c_write(0x20, bytes([reg])): return None
        self.W(B + 0x1000, 0x01060067)
        self.W(B + 0x100C, (0x20 << 15) | (1 << 9) | (1 << 8) | n)
        t = time.time() + 0.5
        while not (self.R(B + 0x1094) & 0x40):
            if time.time() > t: return None
        self.W(B + 0x1094, 0x00300040); self.W(B + 0x1094, 0x80)
        return struct.pack('<I', self.R(B + 0x1008))[:n]

    def tune(self, ch):
        fails = 0
        for o in SEQ['tune'][str(ch)]:
            if o[0] == 'S': time.sleep(o[1] / 1000)
            elif not self.i2c_write(o[1], bytes(o[2])): fails += 1
        lock = False
        for _ in range(30):
            time.sleep(0.1)
            st, b0 = self.demod_read(0x80), self.demod_read(0xB0)
            if st and b0 and (st[0] & 0x28) == 0 and (b0[0] & 0x0F) >= 8: lock = True; break
        # drop what the device/USB still holds from the previous channel (~16 x 0x17800 in FIFO C)
        self.discard_bytes = 2 << 20; self.discard_until = time.time() + 1.0
        while self.discard_bytes > 0 or time.time() < self.discard_until: time.sleep(0.05)
        R.log(f'tune ch{ch}: i2c fails {fails}, lock {lock}'); dbg(f'TUNE ch{ch} lock={lock}')
        self.ch = ch
        return lock

    def start(self, ch0):
        ops = R.load_ops(ch0); R.tsd_override(ops)
        self.dev = R.boot(ops); self.ch = ch0
        threading.Thread(target=self.reader, daemon=True).start()
        self.booted.set()

    def cc_scan(self, b):
        # continuity check on the busiest PID (0x100) across chunks; logs breaks with timestamps
        buf = self._tail + b; i = self._off
        while i + 188 <= len(buf):
            if buf[i] != 0x47:
                j = buf.find(b'\x47', i + 1)
                while j != -1 and j + 188 < len(buf) and buf[j + 188] != 0x47: j = buf.find(b'\x47', j + 1)
                if j == -1 or j + 188 >= len(buf): i = len(buf); break
                dbg(f'RESYNC skip={j - i} at_byte={self._total + i}'); i = j; continue
            if ((buf[i + 1] & 0x1f) << 8 | buf[i + 2]) == 0x100 and buf[i + 3] & 0x10:
                c = buf[i + 3] & 15
                if self._cc is not None and c != ((self._cc + 1) & 15) and c != self._cc:
                    dbg(f'CCBREAK missing={(c - self._cc - 1) % 16} at_byte={self._total + i}')
                self._cc = c
            i += 188
        self._total += i; self._tail = buf[i:]; self._off = 0

    def reader(self):
        self._tail = b''; self._off = 0; self._cc = None; self._total = 0
        while True:
            try:
                b = bytes(self.dev.read(0x83, R.RDSZ, timeout=2000))
                if DEBUG:
                    dbg(f'READ {len(b)}'); self.cc_scan(b)
            except usb.core.USBTimeoutError:
                R.log('no TS data (timeout)'); continue
            except Exception as e:
                R.log('read error', e); os._exit(1)        # let systemd restart us (fresh boot)
            if self.discard_bytes > 0 or time.time() < self.discard_until:
                self.discard_bytes -= len(b); continue
            q = self.subs
            if q is not None:
                try: q.put_nowait(b)
                except queue.Full: R.log('client too slow, dropping')

def serve_client(tun, conn):
    f = conn.makefile('rb')
    try:
        line = f.readline().decode().strip()
        ch = int(line)
        assert 13 <= ch <= 62
    except Exception:
        conn.close(); return
    if not tun.lock.acquire(timeout=3):
        R.log('busy, rejecting client'); conn.close(); return
    try:
        tun.booted.wait()
        if ch != tun.ch: tun.tune(ch)
        q = queue.Queue(maxsize=256); tun.subs = q
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
        while True:
            b = q.get()
            conn.sendall(b)
    except (BrokenPipeError, ConnectionResetError, OSError):
        pass
    finally:
        tun.subs = None
        try: conn.close()
        except Exception: pass
        tun.lock.release()
        R.log('client done')

def main():
    tun = Tuner()
    threading.Thread(target=tun.start, args=(int(os.environ.get('DTH30_CH0', '27')),), daemon=True).start()
    try: os.unlink(SOCK)
    except FileNotFoundError: pass
    us = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); us.bind(SOCK); os.chmod(SOCK, 0o666); us.listen(4)
    ts = socket.socket(); ts.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ts.bind((os.environ.get('DTH30_BIND', '127.0.0.1'), TCP_PORT)); ts.listen(4)
    sel = selectors.DefaultSelector()
    sel.register(us, selectors.EVENT_READ); sel.register(ts, selectors.EVENT_READ)
    R.log(f'listening on {SOCK} and :{TCP_PORT}')
    while True:
        for key, _ in sel.select():
            c, _ = key.fileobj.accept()
            threading.Thread(target=serve_client, args=(tun, c), daemon=True).start()

if __name__ == '__main__':
    main()
