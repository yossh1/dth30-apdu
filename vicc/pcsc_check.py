#!/usr/bin/env python3
"""PC/SC-side check of the dth-vicc virtual reader.

Prints reader names, ATR length + SHA-256 fingerprint, and for each
transmit the response length, SW and SHA-256 fingerprint of
data+SW -- never raw ATR/response bytes.
"""
import hashlib
import sys

from smartcard.System import readers
from smartcard.util import toHexString


def fp(b):
    return hashlib.sha256(bytes(b)).hexdigest()


def main():
    rs = readers()
    print(f"readers ({len(rs)}):")
    for r in rs:
        print(f"  - {r}")
    virt = [r for r in rs if "Virtual" in str(r)]
    if not virt:
        print("FAIL: no Virtual PCD reader found")
        return 1
    conn = virt[0].createConnection()
    conn.connect()
    atr = conn.getATR()
    print(f"ATR: len={len(atr)} sha256={fp(atr)}")
    data, sw1, sw2 = conn.transmit([0x90, 0x30, 0x00, 0x00, 0x00])
    resp = list(data) + [sw1, sw2]
    print(f"INITIAL_SETTING via PC/SC: len={len(resp)} sw={sw1:02x}{sw2:02x} sha256={fp(resp)}")
    data, sw1, sw2 = conn.transmit([0x00] * 61)
    print(f"61-byte APDU via PC/SC: data_len={len(data)} sw={sw1:02x}{sw2:02x} (expect 6700)")
    conn.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
