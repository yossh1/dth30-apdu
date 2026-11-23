#!/usr/bin/env python3
# N-010: scan BufFsUSB.sys for dword references (function-pointer tables) to
# txc_read_return_code (0x37F9C) and its sibling at 0x383DC, plus neighbours.
import struct, sys

SYS = "~/dth30-re/pkg/DTH30U2DRV_143/Drivers/BufFsUSB.sys"
data = open(SYS, "rb").read()

# section map (VA == RVA, image base 0): fileoff = VA - sectVA + sectFileOff
sections = [
    (".text",  0x11000, 0x3E789, 0x400),
    (".rdata", 0x50000, 0x5F4,   0x3EC00),
    (".data",  0x51000, 0x1271B0, 0x3F200),
    ("INIT",   0x179000, 0x97A,  0x166400),
    (".rsrc",  0x17A000, 0x418,  0x166E00),
]
def va_of(off):
    for name, va, size, foff in sections:
        if foff <= off < foff + size:
            return va + (off - foff), name
    return None, None

targets = {
    0x37F9C: "txc_read_return_code",
    0x383DC: "sibling_383DC",
    0x378E4: "helper_378E4 (called by 383DC)",
}
for va, name in targets.items():
    pat = struct.pack("<I", va)
    hits = []
    start = 0
    while True:
        i = data.find(pat, start)
        if i < 0:
            break
        hva, sec = va_of(i)
        hits.append((i, hva, sec))
        start = i + 1
    print(f"== {name} VA {va:#x}: {len(hits)} dword hits")
    for off, hva, sec in hits:
        print(f"   fileoff {off:#x} -> VA {hva:#x} ({sec})")
    # also dump neighbouring dwords for table context
    for off, hva, sec in hits:
        lo = max(0, off - 16)
        words = struct.unpack("<8I", data[lo:lo + 32])
        print(f"   context @fileoff {off:#x}: " + " ".join(f"{w:#010x}" for w in words))
