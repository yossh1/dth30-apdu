import gzip, json, struct
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
stream = b''.join(bytes.fromhex(ops[k][3]) for k in (338,339,340,341,351))
def dw(b, off, n=8):
    return [hex(struct.unpack('<I', b[off+i*4:off+i*4+4])[0]) for i in range(n)]
print('img tbl @0xFF390:', dw(img, 0xFF390, 10))
print('stream @0xFF170:', dw(stream, 0xFF170, 10))
print('stream @0xFF180:', dw(stream, 0xFF180, 10))
# scan stream for any dword in {0x80153550, 0xA0153550, 0x8015361c, 0xA015361c}
for val in (0x80153550, 0xA0153550, 0x8015361C, 0xA015361C, 0x80153530):
    pat = struct.pack('<I', val); hits=[]; j=stream.find(pat)
    while j>=0: hits.append(hex(j)); j=stream.find(pat,j+1)
    print(hex(val), 'stream hits:', hits[:20], 'count', len(hits))
# check the disasm: what does the worker table VA 0x801FF390 correspond to in file terms?
# file 0xFF390 per AUDIT. In stream, what's around where table should be: search for sequence of >=6 dwords in 0x80153xxx range
import re
cnt=0
for i in range(0, len(stream)-4, 4):
    v = struct.unpack('<I', stream[i:i+4])[0]
    if 0x80153300 <= v <= 0x80153A00: cnt+=1
print('dwords in stream in 0x801533xx-0x80153Axx range:', cnt)
