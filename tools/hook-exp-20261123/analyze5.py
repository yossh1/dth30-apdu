import gzip, json, struct
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
def pkt(o):
    if o[0]!='O': return None
    b=bytes.fromhex(o[3])
    if len(b)==10: return struct.unpack('<HII', b)
    return None
for target in (338,339,340,341,351):
    print(f'--- setup before ops[{target}] ---')
    for k in range(target-14, target):
        p = pkt(ops[k])
        if p: print(k, f'op={p[0]:#06x} addr={p[1]:#x} val={p[2]:#x}')
        else:
            o=ops[k]; print(k, o[0], 'ep', o[2] if len(o)>2 else '', 'len', len(bytes.fromhex(o[3])) if o[0]=='O' else o[3] if len(o)>3 else '')
