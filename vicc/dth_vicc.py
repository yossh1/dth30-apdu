#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""dth-vicc: present the DT-H30's B-CAS card to PC/SC as a virtual reader.

A vsmartcard SmartcardOS (same shape as upstream's cards/Relay.py RelayOS)
whose backend is not a local PC/SC reader but the `dth serve` APDU socket
(/run/dth/dth.sock, one line-protocol request per connection):

    apdu query       -> card status (bit0 present, bit1 active) + ATR
    apdu data=<hex>  -> one APDU exchange with the card

Design: ../VICC-DESIGN.md; presence/deadlock fix: ../VICC-FIX-REPORT.md.
Points of care:

* Card responses are passed through verbatim, including 61xx/6Cxx
  chaining status words; the reader layer never chases GET RESPONSE.
* A failure that kept the APDU from reaching the card is reported as a
  status-word-only response (a real reader's transport failure looks the
  same to a PC/SC client).  execute() must never raise: VirtualICC.run()
  has no guard around it and an exception would kill the connection.
* powerUp/powerDown/reset are no-ops: the card session belongs to
  dth serve and is shared with the tuner's ECM processing, so a PC/SC
  power cycle must not touch the real card.
* Nothing of the ATR or of card responses is logged (lengths, status
  words of *synthetic* errors and dth reason/code numbers only).  The
  VirtualICC log level is kept at WARNING so vicc's own INFO-level
  APDU hexdumps stay out of the journal.

Presence model (the fix): upstream's design is *connection <=> card
present* -- vpcd decides presence from the ATR answer, and a
zero-length ATR answer is a trap: vpcd's recvFromVICC() waits for it
with a zero-length MSG_WAITALL receive, which blocks until further
data arrives, wedging pcscd's reader thread (and, via vpcd's io_lock,
every later transmit) for good.  So this bridge never sends an empty
frame.  A supervisor thread polls `apdu query`; the vpcd connection
exists only while the card is present and active.  Sustained absence
(~8 s, longer than serve's slowest straddling-APDU answer) drops the
connection, which is what makes pcscd report REMOVED; the card's
return reconnects, which reports INSERTED.  A serve outage is not a
removal: query *errors* never drop the connection, and transmits
during an outage fail bounded (deadline below) instead of hanging.
"""

import logging
import re
import socket
import sys
import threading
import time

# vsmartcard 0.8's CryptoUtils wants PyCrypto's `Crypto` namespace.
# Debian ships pycryptodome under the `Cryptodome` namespace instead;
# alias it before importing virtualsmartcard.
try:
    import Crypto  # noqa: F401
except ImportError:
    try:
        import Cryptodome

        sys.modules.setdefault("Crypto", Cryptodome)
    except ImportError:
        pass

try:
    from virtualsmartcard.VirtualSmartcard import SmartcardOS, VirtualICC
except ImportError:
    # Debian's python3-virtualsmartcard installs the package below
    # /usr/lib/python3/site-packages/virtualsmartcard, which is not on
    # the default sys.path.
    sys.path.insert(0, "/usr/lib/python3/site-packages/virtualsmartcard")
    from virtualsmartcard.VirtualSmartcard import SmartcardOS, VirtualICC

DTH_SOCKET = "/run/dth/dth.sock"
VPCD_HOST = "localhost"
VPCD_PORT = 35963
QUERY_TTL = 1.0        # s; absorbs pcscd's presence polling (vicc_present
                       # asks for the ATR on every poll)
SOCKET_TIMEOUT = 65.0  # serve may take seconds to answer (activation)
EXEC_DEADLINE = 30.0   # s; hard bound for one execute(), retries included
BUSY_RETRIES = 5
BUSY_WAIT = 0.2
WATCH_INTERVAL = 1.0   # s; supervisor's `apdu query` polling cadence
ABSENT_GRACE = 8       # consecutive definitive-absence polls (~8 s)
                       # before the vpcd connection is dropped; longer
                       # than serve's ~5.1 s straddling-APDU answer, so
                       # an APDU in flight at removal still returns its
                       # 6985 before REMOVED is signalled

log = logging.getLogger("dth-vicc")

_QUERY_RE = re.compile(r"card=0x([0-9a-fA-F]+)\s+atr=([0-9a-fA-F]+|-)")
_EXCHANGE_RE = re.compile(r"(?:^|\s)apdu=([0-9a-fA-F]+)")
_APDU_ERR_RE = re.compile(r"apdu (reason|code)=(\d+)")


def dth_request(line, timeout=SOCKET_TIMEOUT):
    """Send one request line to dth serve; return its reply line."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(DTH_SOCKET)
        s.sendall(line.encode("ascii") + b"\n")
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(512)
            if not chunk:
                break
            buf += chunk
    return buf.decode("ascii", "replace").strip()


def parse_reply(line):
    """Split a serve reply into (kind, rest): ok / error / busy."""
    if line.startswith("ok "):
        return "ok", line[3:]
    if line.startswith("error "):
        return "error", line[6:]
    if line.startswith("busy"):
        return "busy", line[4:].lstrip(" :")
    return "error", line


def serve_card_present():
    """Definitive card state from serve: True / False / None (unknown).

    Only a parsed `ok` query reply is definitive.  Errors, busy replies
    and socket failures are "unknown" -- a serve outage must never be
    mistaken for a card removal.
    """
    try:
        kind, rest = parse_reply(dth_request("apdu query", timeout=10.0))
    except OSError:
        return None
    if kind != "ok":
        return None
    m = _QUERY_RE.search(rest)
    if not m:
        return None
    status = int(m.group(1), 16)
    return bool(status & 0x01 and status & 0x02)


class CardAbsent(Exception):
    """getATR() has no card to describe; drop the connection instead
    of sending vpcd a zero-length frame (see module docstring)."""


class DthCardOS(SmartcardOS):
    """SmartcardOS relaying to the DT-H30's card through dth serve."""

    def __init__(self):
        self._q_cache = None  # (monotonic time, status, atr bytes)
        self._last_atr = b""  # last ATR of a present, active card

    # -- backend helpers -------------------------------------------------

    def _query(self):
        now = time.monotonic()
        if self._q_cache is not None and now - self._q_cache[0] < QUERY_TTL:
            return self._q_cache[1], self._q_cache[2]
        status, atr = 0, b""
        try:
            kind, rest = parse_reply(dth_request("apdu query"))
            if kind == "ok":
                m = _QUERY_RE.search(rest)
                if m:
                    status = int(m.group(1), 16)
                    atr = b"" if m.group(2) == "-" else bytes.fromhex(m.group(2))
                else:
                    log.warning("query: unparseable ok reply")
            else:
                log.warning("query answered %s: %s", kind, rest)
        except OSError as e:
            log.warning("query failed: %s", e)
        self._q_cache = (now, status, atr)
        return status, atr

    # -- SmartcardOS interface -------------------------------------------

    def getATR(self):
        status, atr = self._query()
        if status & 0x01 and status & 0x02 and atr:
            self._last_atr = atr
            return atr
        if self._last_atr:
            # Absent (or not yet active) but the supervisor has not
            # dropped the connection yet: keep answering with the last
            # real ATR.  An empty answer would deadlock vpcd; the
            # connection drop, not this answer, signals the removal.
            return self._last_atr
        # Connected while no ATR is known (card vanished between the
        # supervisor's check and vpcd's first ATR request): refuse to
        # answer at all.  Raising unwinds VirtualICC.run(); the worker
        # closes the socket and vpcd sees the reader go away.
        raise CardAbsent("no card at first ATR request")

    def powerUp(self):
        log.warning("powerUp: no-op (card session is owned by dth serve)")

    def powerDown(self):
        log.warning("powerDown: no-op (card session is owned by dth serve)")

    def reset(self):
        log.warning("reset: no-op (card session is owned by dth serve)")

    def execute(self, msg):
        try:
            return self._execute(msg)
        except Exception:
            # VirtualICC.run() has no guard around os.execute(); never
            # let anything escape and kill the connection thread.
            log.exception("exchange: unexpected failure, answering 6F00")
            return b"\x6f\x00"

    def _execute(self, msg):
        if isinstance(msg, str):
            apdu = msg.encode("latin-1")
        else:
            apdu = bytes(msg)
        line = "apdu data=" + apdu.hex()
        kind = rest = ""
        deadline = time.monotonic() + EXEC_DEADLINE
        for attempt in range(BUSY_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("exchange: deadline exceeded, answering 6F00")
                return b"\x6f\x00"
            try:
                kind, rest = parse_reply(
                    dth_request(line, timeout=min(SOCKET_TIMEOUT, remaining)))
            except OSError as e:
                log.warning("exchange: dth socket failed: %s", e)
                return b"\x6f\x00"
            if kind == "ok":
                m = _EXCHANGE_RE.search(rest)
                if m:
                    return bytes.fromhex(m.group(1))
                log.warning("exchange: unparseable ok reply")
                return b"\x6f\x00"
            err = _APDU_ERR_RE.search(rest)
            busy = kind == "busy" or (err is not None and err.groups() == ("reason", "2"))
            if busy and attempt < BUSY_RETRIES:
                time.sleep(BUSY_WAIT)
                continue
            break
        # The APDU never reached (or never came back from) the card:
        # answer with a status word only, as a reader transport error.
        err = _APDU_ERR_RE.search(rest)
        if err is not None and err.groups() == ("reason", "3"):
            log.warning("exchange refused: reason 3 (bad length, %d bytes)", len(apdu))
            return b"\x67\x00"
        if err is not None and err.groups() == ("reason", "1"):
            log.warning("exchange refused: reason 1 (no active card)")
            return b"\x69\x85"
        log.warning("exchange failed: %s %s", kind, rest)
        return b"\x6f\x00"


class ViccWorker(threading.Thread):
    """One vpcd connection's lifetime: construct, run, clean up.

    VirtualICC connects in __init__ and sys.exit()s when the
    connection breaks; both are contained in this thread so the
    supervisor survives them.
    """

    def __init__(self):
        super().__init__(daemon=True, name="vicc-connection")
        self.vicc = None

    def run(self):
        try:
            # The card type only steers VirtualICC's OS factory; the
            # generated OS is replaced below before run() and is never
            # used.  ("handler_test" would be lighter, but Debian's
            # package does not ship HandlerTest.py.)
            vicc = VirtualICC(None, "iso7816", VPCD_HOST, VPCD_PORT,
                              logginglevel=logging.WARNING)
            vicc.os = DthCardOS()
            self.vicc = vicc
            log.warning("vicc connected to vpcd (card present)")
            vicc.run()
        except SystemExit:
            log.warning("vicc connection closed by vpcd side")
        except CardAbsent:
            log.warning("vicc connection dropped: card absent")
        except Exception:
            log.exception("vicc connection died unexpectedly")
        finally:
            self.drop()
            self.vicc = None

    def drop(self):
        """Tear the vpcd connection down (idempotent).

        shutdown() is what wakes the worker's blocking recv; the
        resulting socket error ends vicc.run() on the worker thread.
        """
        vicc = self.vicc
        if vicc is not None:
            try:
                vicc.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                vicc.sock.close()
            except OSError:
                pass


def main():
    log.warning("dth-vicc up: DT-H30 card bridged via %s (supervised)",
                DTH_SOCKET)
    worker = None
    absent_polls = 0
    while True:
        present = serve_card_present()
        if worker is not None and not worker.is_alive():
            worker = None  # connection ended on its own (vpcd restart…)
        if worker is None:
            absent_polls = 0
            if present:
                worker = ViccWorker()
                worker.start()
        elif present is False:
            absent_polls += 1
            if absent_polls >= ABSENT_GRACE:
                log.warning(
                    "card absent for %d polls: dropping vpcd connection "
                    "(PC/SC will see the card removed)", absent_polls)
                worker.drop()
                worker.join(timeout=5.0)
                worker = None
                absent_polls = 0
        elif present is True:
            absent_polls = 0
        # present is None (serve unreachable/unparseable): hold state.
        time.sleep(WATCH_INTERVAL)


if __name__ == "__main__":
    main()
