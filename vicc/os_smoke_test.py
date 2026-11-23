#!/usr/bin/env python3
"""Smoke test for DthCardOS alone (no vpcd): prints lengths, SW and
SHA-256 fingerprints only -- never raw ATR/response bytes."""
import hashlib
import sys

sys.path.insert(0, "/usr/local/lib/dth-vicc")
import dth_vicc


def fp(b):
    return hashlib.sha256(b).hexdigest()


def main():
    os_ = dth_vicc.DthCardOS()
    status, atr = os_._query()
    print(f"query: status=0x{status:02x} atr_len={len(atr)} atr_sha256={fp(atr)}")
    atr2 = os_.getATR()
    print(f"getATR: len={len(atr2)} sha256={fp(atr2)}")
    resp = os_.execute(bytes.fromhex("9030000000"))
    sw = resp[-2:].hex() if len(resp) >= 2 else "----"
    print(f"exchange INITIAL_SETTING: len={len(resp)} sw={sw} sha256={fp(resp)}")
    resp61 = os_.execute(bytes(61))
    print(f"exchange 61-byte APDU: len={len(resp61)} sw={resp61.hex()} (expect 6700)")


if __name__ == "__main__":
    main()
