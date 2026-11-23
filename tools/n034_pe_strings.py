#!/usr/bin/env python3
# N-034 helper: read strings from BufFsUSB.sys at given RVAs (printed disasm addresses = RVA).
import struct, sys

PATH = "~/dth30-re/pkg/DTH30U2DRV_143/Drivers/BufFsUSB.sys"
data = open(PATH, "rb").read()
e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
nsec = struct.unpack_from("<H", data, e_lfanew + 6)[0]
opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
secs = []
off = e_lfanew + 24 + opt_size
for i in range(nsec):
    name = data[off + i * 40: off + i * 40 + 8].rstrip(b"\0").decode()
    vsize, vaddr, rsize, raddr = struct.unpack_from("<IIII", data, off + i * 40 + 8)
    secs.append((name, vaddr, vsize, raddr, rsize))

def rva2off(rva):
    for name, vaddr, vsize, raddr, rsize in secs:
        if vaddr <= rva < vaddr + max(vsize, rsize):
            return raddr + (rva - vaddr)
    return None

def read_str(rva, maxlen=200):
    o = rva2off(rva)
    if o is None:
        return "<no section>"
    # try UTF-16LE first if pattern matches
    raw = data[o:o + maxlen * 2]
    out = []
    i = 0
    while i + 1 < len(raw) and raw[i + 1] == 0 and 0x20 <= raw[i] < 0x7F:
        out.append(chr(raw[i])); i += 2
    if len(out) >= 3:
        return "U16: " + "".join(out)
    out = []
    i = 0
    while i < len(raw) and 0x20 <= raw[i] < 0x7F:
        out.append(chr(raw[i])); i += 1
    return "A: " + "".join(out)

if __name__ == "__main__":
    for s in sys.argv[1:]:
        rva = int(s, 0)
        print(f"{rva:#x}: {read_str(rva)}")
