#!/usr/bin/env python3
"""イメージ内ポインタ dword census: 指定 VA (KSEG0/KSEG1 両形式) が
データとして現れる file offset を列挙する。"""
import struct, sys
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
targets = [0xA012BE18,0xA012BD5C,0xA012BC90,0xA01262CC,0xA0129924,
           0xA0125D5C,0xA01A6138,0xA0136C9C,0xA0123E08,0xA012BE6C]
for t in targets:
    hits = []
    for form in (t, t & 0x1FFFFFFF | 0x80000000):  # KSEG1 / KSEG0
        pat = struct.pack('<I', form)
        i = 0
        while True:
            i = img.find(pat, i)
            if i < 0: break
            if i % 4 == 0: hits.append((i, form))
            i += 1
    print(f"0x{t:08X}: {len(hits)} hits")
    for off, form in hits:
        print(f"    file 0x{off:06X} (VA 0x{0xA0100000+off:08X}) form 0x{form:08X}")
