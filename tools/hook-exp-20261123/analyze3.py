import gzip, json, struct
img = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
print('img len', len(img), hex(len(img)))
# verify table at file 0xFF390
for f in range(0x1C):
    v = struct.unpack('<I', img[0xFF390+f*4:0xFF390+f*4+4])[0]
    print(f'Func {f:#04x} entry = {v:#010x}')
print('cave all zero?', img[0x1E238:0x1E238+6596] == bytes(6596), 'range end', hex(0x1E238+6596))
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
# download chunk ops: 'O' with big payloads in ops[0:355]
chunks=[]
for k in range(0,355):
    o=ops[k]
    if o[0]=='O':
        b=bytes.fromhex(o[3])
        chunks.append((k,o[2],len(b)))
print('O ops in stage A seg1:', [(k,ep,l) for k,ep,l in chunks if l>1000])
def search(anchor, label):
    hits=[]
    for k,o in enumerate(ops):
        if o[0]!='O': continue
        b=bytes.fromhex(o[3])
        j=b.find(anchor)
        while j>=0:
            hits.append((k,j)); j=b.find(anchor,j+1)
    print(label, 'hits:', hits)
search(img[0xFF380:0xFF3C0], 'table ctx (file 0xFF380, 64B)')
search(img[0x1E1F8:0x1E238], 'cave-pre ctx (file 0x1E1F8, 64B)')
search(img[0x1FBFC:0x1FC3C], 'cave-post ctx (file 0x1FBFC, 64B)')
