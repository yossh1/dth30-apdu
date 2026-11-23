#!/usr/bin/env python3
# hw24_analyze: post-hoc analysis of hw24 dumps (runs on 検証ホスト, lab dir).
# 1) Did the constructed slot image land at phys 0xEEC0? (header check)
# 2) Validate slot addressing against the recorded Func8 slot 0xCB00.
# 3) Search fields 1..3 post dumps for any ctx instance (init-marker pair
#    +0x8E24==1 / +0x4B1C==1) and for the constructor's self-referential
#    embedded descriptor (ctx+0x318 -> own +0x7a68, desc+0x10 == 0x14).
import struct, os

HERE = os.path.dirname(os.path.abspath(__file__))
def dw(data, off): return struct.unpack('<I', data[off:off+4])[0]

f1 = open(os.path.join(HERE, 'n024_f1_post.bin'), 'rb').read()
f2 = open(os.path.join(HERE, 'n024_f2_post.bin'), 'rb').read()
f3 = open(os.path.join(HERE, 'n024_f3_post.bin'), 'rb').read()
f2pre = open(os.path.join(HERE, 'n024_f2_pre.bin'), 'rb').read()

print('== slot image at phys 0xEEC0 (field1 dump) ==')
for name, off in [('+0x08', 8), ('+0x0c', 0x0c), ('+0x10', 0x10), ('+0x14', 0x14),
                  ('+0x18', 0x18), ('+0x1c', 0x1c), ('+0x3c', 0x3c),
                  ('param+0x58', 0x24+0x58), ('param+0x5c', 0x24+0x5c), ('param+0x60', 0x24+0x60)]:
    print(f'  slot{name} = {dw(f1, 0xEEC0+off):#010x}')
print('== recorded slot 0xCB00 for addressing validation ==')
for name, off in [('+0x08', 8), ('+0x0c', 0x0c), ('+0x10', 0x10), ('+0x14', 0x14), ('+0x1c', 0x1c), ('+0x3c', 0x3c)]:
    print(f'  oldslot{name} = {dw(f1, 0xCB00+off):#010x}')

print('== distinctive image pattern (0x30080000 run) anywhere in f1 ==')
pat = struct.pack('<I', 0x30080000) * 4
i = f1.find(pat)
while i != -1:
    print(f'  run at phys {i:#x}')
    i = f1.find(pat, i + 4)

fields = [(1, f1, 0x000000), (2, f2, 0x100000), (3, f3, 0x200000)]
print('== ctx marker-pair scan (+0x8E24==1 and +0x4B1C==1), fields 1..3 post ==')
for fno, data, base in fields:
    for off in range(0, len(data) - 0x8E28, 4):
        if dw(data, off + 0x8E24) == 1 and dw(data, off + 0x4B1C) == 1:
            phys = base + off
            print(f'  candidate ctx at phys {phys:#x} (field{fno} off {off:#x}): '
                  f'+0x318={dw(data, off+0x318):#010x} +0x324={dw(data, off+0x324):#010x} '
                  f'+0x30={dw(data, off+0x30):#010x} +0x2408={dw(data, off+0x2408):#010x} '
                  f'+0x4bdc={dw(data, off+0x4BDC):#010x}')

print('== embedded-descriptor self-reference scan, fields 1..3 post ==')
found = 0
for fno, data, base in fields:
    for off in range(0, len(data) - 0x7A78, 4):
        p318 = dw(data, off + 0x318)
        phys = base + off
        for cand in (0xA0000000 + phys + 0x7A68, phys + 0x7A68):
            if p318 == cand and dw(data, off + 0x7A68 + 0x10) == 0x14:
                print(f'  HIT ctx phys {phys:#x}: +0x318={p318:#010x} desc+0x10=0x14')
                found += 1
print(f'  self-ref hits: {found}')

print('== any nonzero +0x318 among marker candidates is reported above; '
      'also scan f2 for dwords equal to 0xa01088dc+0x7a68 (old ctx desc VA) ==')
target = 0xA0000000 + 0x1088DC + 0x7A68
cnt = 0
for fno, data, base in fields:
    for off in range(0, len(data) - 4, 4):
        if dw(data, off) == target:
            print(f'  value {target:#x} at phys {base+off:#x}')
            cnt += 1
print(f'  old-ctx-desc pointer hits: {cnt}')
