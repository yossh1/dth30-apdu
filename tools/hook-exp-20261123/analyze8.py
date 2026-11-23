import gzip, json, struct
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
stream = b''.join(bytes.fromhex(ops[k][3]) for k in (338,339,340,341,351))
p341 = bytes.fromhex(ops[341][3])
def dw(b, off, n=1): return [hex(struct.unpack('<I', b[off+i*4:off+i*4+4])[0]) for i in range(n)]
print('ops341 local 0x3F170 table:', dw(p341, 0x3F170, 10))
# stream stub VA hits
for val in (0x801534d0, 0x8015359c):
    pat = struct.pack('<I', val); hits=[]; j=stream.find(pat)
    while j>=0: hits.append(hex(j)); j=stream.find(pat,j+1)
    print(hex(val), 'stream hits:', hits)
# case code: stream[0x5359C..] vs img[0x5361C..]
a = stream[0x5359C:0x5359C+64]; b = img[0x5361C:0x5361C+64]
print('case5 code stream==img?', a==b)
print('case5 stream dwords:', dw(stream, 0x5359C, 8))
print('case5 img    dwords:', dw(img, 0x5361C, 8))
# stub code at stream 0x534D0 vs img 0x53550
a = stream[0x534D0:0x534D0+32]; b = img[0x53550:0x53550+32]
print('stub code stream==img?', a==b, a[:16].hex(), b[:16].hex())
# cave zero run in stream starting at 0x1E238
i = 0x1E238
while i < len(stream) and stream[i]==0: i+=1
print('stream zero run from 0x1E238: len', i-0x1E238, 'ends at', hex(i), 'next bytes', stream[i:i+16].hex())
print('img bytes at 0x1FBFC:', img[0x1FBFC:0x1FC0C].hex())
# check stream dword at cave start region: what's before, at 0x1E230
print('stream[0x1E230:0x1E240]', stream[0x1E230:0x1E240].hex(), ' img same:', img[0x1E230:0x1E240].hex())
