import gzip, json, struct
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
stream = b''.join(bytes.fromhex(ops[k][3]) for k in (338,339,340,341,351))
print('stream len', len(stream), hex(len(stream)))
print('Video delta in img at', hex(img.find(b'Video delta')))
print('Video delta in stream at', hex(stream.find(b'Video delta')))
def s(pat, label):
    hits=[]; j=stream.find(pat)
    while j>=0: hits.append(j); j=stream.find(pat,j+1)
    print(label, [hex(h) for h in hits])
s(img[0xFF390:0xFF398], 'tbl e0-1 (8B)')
s(bytes.fromhex('503515801c361580'), 'tbl e4-5 (8B)')
s(img[0xFF3A0:0xFF3A8], 'tbl e4-5 img (8B)')
s(img[0x1E1F8:0x1E238], 'cave-pre (64B)')
s(img[0x1FBFC:0x1FCFC], 'cave-post (256B)')
# how much of stream matches img at same offset?
n=min(len(stream),len(img)); same=sum(1 for i in range(0,n,4) if stream[i:i+4]==img[i:i+4])
print('dword match rate at same offset:', same, '/', n//4)
# find first divergence
for i in range(n):
    if stream[i]!=img[i]:
        print('first byte divergence at', hex(i)); break
print('stream[0x5c0:0x600]', stream[0x5c0:0x600].hex())
print('img   [0x5c0:0x600]', img[0x5c0:0x600].hex())
