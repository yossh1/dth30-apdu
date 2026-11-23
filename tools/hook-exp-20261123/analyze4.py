import gzip, json, struct
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
p341 = bytes.fromhex(ops[341][3]); p338 = bytes.fromhex(ops[338][3])
print('ops341 len', len(p341), 'ops338 len', len(p338))
# check ops338 == img[0:0x40000]?
seg = img[0:0x40000]
d = [i for i in range(len(seg)) if seg[i]!=p338[i]]
print('ops338 vs img[0:0x40000] diff bytes:', len(d), d[:10])
seg = img[0xC0000:0x100000]
d = [i for i in range(min(len(seg),len(p341))) if seg[i]!=p341[i]]
print('ops341 vs img[0xC0000:0x100000] diff bytes:', len(d), 'first:', [hex(x) for x in d[:20]])
# search entry dwords in ops341
for name, pat in [('stub 80153550', bytes.fromhex('50351580')), ('case5 8015361c', bytes.fromhex('1c361580')),
                  ('tbl start 80153530', bytes.fromhex('30351580'))]:
    hits=[]; j=p341.find(pat)
    while j>=0: hits.append(j); j=p341.find(pat,j+1)
    print(name, 'in ops341 at', [hex(h) for h in hits], '-> file', [hex(h+0xC0000) for h in hits])
# dump payload around expected table offset 0x3F390
print('ops341[0x3F380:0x3F3D0]:', p341[0x3F380:0x3F3D0].hex())
print('img   [0xFF380:0xFF3D0]:', img[0xFF380:0xFF3D0].hex())
