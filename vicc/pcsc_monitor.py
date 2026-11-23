#!/usr/bin/env python3
"""PC/SC monitor rig for the DT-H30 card-removal test (vicc).

Two threads against reader "Virtual PCD 00 00":
  (a) CardMonitor observer: logs every card insert/remove state change
      with a timestamp (insert includes ATR length + SHA-256 fingerprint).
  (b) Transmit loop: repeats the INITIAL_SETTING APDU (90 30 00 00 00)
      and logs each attempt's outcome -- success: response length, SW,
      SHA-256 fingerprint of data+SW; failure: exception class name.

Raw ATR / response bytes are never logged (length, SW, fingerprint only).
Log lines are appended to the file named by argv[1] (default monitor.log
in the current directory) and flushed per line so an external tail sees
events as they happen.
"""
import hashlib
import sys
import threading
import time
from datetime import datetime

from smartcard.CardMonitoring import CardMonitor, CardObserver
from smartcard.System import readers
from smartcard.Exceptions import CardConnectionException, NoCardException

APDU = [0x90, 0x30, 0x00, 0x00, 0x00]
INTERVAL = 0.3

_log_lock = threading.Lock()
_logf = None


def ts():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def log(tag, msg):
    line = f"{ts()} [{tag}] {msg}\n"
    with _log_lock:
        _logf.write(line)
        _logf.flush()


def fp(b):
    return hashlib.sha256(bytes(b)).hexdigest()


class StateObserver(CardObserver):
    def update(self, observable, actions):
        added, removed = actions
        for card in removed:
            log("state", f"REMOVED reader={card.reader}")
        for card in added:
            try:
                atr = card.atr
                log("state", f"INSERTED reader={card.reader} "
                             f"atr_len={len(atr)} atr_sha256={fp(atr)}")
            except Exception as e:  # noqa: BLE001 - log and continue
                log("state", f"INSERTED reader={card.reader} "
                             f"atr_error={type(e).__name__}")


def transmit_loop(reader):
    seq = 0
    conn = None
    while True:
        seq += 1
        try:
            if conn is None:
                conn = reader.createConnection()
                conn.connect()
                atr = conn.getATR()
                log("tx", f"#{seq} CONNECT ok atr_len={len(atr)} "
                          f"atr_sha256={fp(atr)}")
            t0 = time.monotonic()
            data, sw1, sw2 = conn.transmit(APDU)
            dt = time.monotonic() - t0
            resp = list(data) + [sw1, sw2]
            log("tx", f"#{seq} OK len={len(resp)} sw={sw1:02x}{sw2:02x} "
                      f"sha256={fp(resp)} dt={dt:.3f}s")
        except (CardConnectionException, NoCardException) as e:
            log("tx", f"#{seq} FAIL {type(e).__name__}: {e}")
            try:
                if conn is not None:
                    conn.disconnect()
            except Exception:  # noqa: BLE001
                pass
            conn = None
        except Exception as e:  # noqa: BLE001 - keep the loop alive
            log("tx", f"#{seq} FAIL {type(e).__name__}: {e}")
            conn = None
        time.sleep(INTERVAL)


def main():
    global _logf
    path = sys.argv[1] if len(sys.argv) > 1 else "monitor.log"
    _logf = open(path, "a", buffering=1)
    rs = readers()
    virt = [r for r in rs if "Virtual PCD 00 00" in str(r)]
    log("main", f"start readers={[str(r) for r in rs]}")
    if not virt:
        log("main", "FAIL: Virtual PCD 00 00 not found")
        return 1
    monitor = CardMonitor()
    monitor.addObserver(StateObserver())
    log("main", "state monitor armed")
    transmit_loop(virt[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
