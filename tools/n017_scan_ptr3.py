import struct
data = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
for val in (0x801be144, 0xa01be144, 0x000be144):
    pat=struct.pack('<I',val); hits=[]; i=0
    while True:
        j=data.find(pat,i)
        if j<0: break
        hits.append(j); i=j+1
    print(f"exact 0x{val:08x}: {len(hits)} hits at {[hex(h) for h in hits]}")
# any aligned word equal to entry in any segment form, plus lui/addiu construction check via jal encoding
# jal target encoding scan: word>>26==3 (jal) or ==2 (j); target field
import sys
for off in range(0, len(data)-3, 4):
    w=struct.unpack_from('<I',data,off)[0]
    op=w>>26
    if op in (2,3):
        tgt=((w&0x03ffffff)<<2)
        if tgt in (0x0be144,0x0be140):
            va=0xa0100000+off
            print(f"{'jal' if op==3 else 'j'} at VA 0x{va:08x} -> 0x{tgt:08x}")
