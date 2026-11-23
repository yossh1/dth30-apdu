#!/usr/bin/env python3
"""Static parse of xcode2emb_embedded.bin header zone + checksum-field hunt.
Read-only. Prints a report; also writes parse_image_out.txt next to itself.
"""
import struct, zlib, hashlib, os

IMG = os.path.expanduser("~/workspace/dth30-re/xcode2emb_embedded.bin")
data = open(IMG, "rb").read()
out = []
def p(s=""):
    out.append(s)
    print(s)

p(f"size = {len(data)} (0x{len(data):x})")
p(f"sha256 = {hashlib.sha256(data).hexdigest()}")

def w(off):
    return struct.unpack_from("<I", data, off)[0]

p("\n-- header words 0x000-0x200 --")
for off in range(0, 0x200, 16):
    ws = [w(off + 4 * i) for i in range(4)]
    p(f"{off:06x}: " + " ".join(f"{x:08x}" for x in ws))

p("\n-- +0x100 word (mikosu OWN_MAGIC offset) --")
p(f"0x100: {w(0x100):08x}  (CFW magic 'DTH3' would be 0x33485444)")

cnt = w(0x110)
p(f"\n-- vector table: count @0x110 = {cnt} --")
for k in range(min(cnt, 32)):
    e = 0x120 + 16 * k
    p(f"entry {k}: dst={w(e):#010x} w1={w(e+4):#010x} w2={w(e+8):#010x} w3={w(e+12):#010x}")

p("\n-- tail words (last 64 bytes) --")
for off in range(len(data) - 64, len(data), 16):
    ws = [w(off + 4 * i) for i in range(4)]
    p(f"{off:06x}: " + " ".join(f"{x:08x}" for x in ws))

# Checksum-field hunt: compute candidate checksums over several ranges and
# look for any of the values among header (0x0-0x200) or tail dwords.
def cksums(buf):
    n = len(buf) // 4
    dws = struct.unpack(f"<{n}I", buf[: n * 4])
    return {
        "crc32": zlib.crc32(buf) & 0xFFFFFFFF,
        "sum32": sum(dws) & 0xFFFFFFFF,
        "xor32": __import__("functools").reduce(lambda a, b: a ^ b, dws, 0),
    }

ranges = {
    "full": data,
    "skip0x200": data[0x200:],
    "skip0x1000": data[0x1000:],
    "first1MB": data[:0x100000],
}
header_words = {w(o): o for o in range(0, 0x200, 4)}
tail_words = {w(o): o for o in range(len(data) - 0x100, len(data), 4)}
p("\n-- checksum candidates vs header/tail dwords --")
found = False
for name, buf in ranges.items():
    for kind, val in cksums(buf).items():
        for table, tname in ((header_words, "header"), (tail_words, "tail")):
            if val in table:
                p(f"HIT: {kind}({name}) = {val:08x} found at {tname} offset {table[val]:#x}")
                found = True
if not found:
    p("no hit: no header/tail dword equals crc32/sum32/xor32 of full image, "
      "image[0x200:], image[0x1000:], or first 1MB")

open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "parse_image_out.txt"), "w").write("\n".join(out) + "\n")
