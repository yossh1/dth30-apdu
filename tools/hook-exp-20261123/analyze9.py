import gzip, json, struct
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
for k, label in ((5837,'Func0x19 block @slot 0x1840'), (5976,'Func0x08 block @slot 0xCB00'), (5837+0,'x')):
    if label=='x': continue
    b = bytes.fromhex(ops[k][3])
    dwords = [hex(struct.unpack('<I', b[i*4:i*4+4])[0]) for i in range(12)]
    print(label, 'len', len(b), 'head dwords:', dwords)
    print('  param[0x24:0x44]:', b[0x24:0x44].hex())
