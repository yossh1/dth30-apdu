import gzip, json, struct
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
print('total ops', len(ops))
from collections import Counter
print(Counter(o[0] for o in ops))
# 'O' ops: [kind, dt, ep, hexdata]; RPCI write packet = 2f40 + addrLE + valLE (10B)
def pkt(o):
    if o[0]!='O': return None
    try: b = bytes.fromhex(o[3])
    except Exception: return None
    if len(b)==10 and b[0]==0x2f and b[1]==0x40:
        return struct.unpack('<I', b[2:6])[0], struct.unpack('<I', b[6:10])[0]
    return None
doors=[]
for k,o in enumerate(ops):
    p = pkt(o)
    if p and p[0] in (0x20003020, 0x20003030):
        doors.append((k, hex(p[0]), hex(p[1])))
print('doorbell writes:', len(doors))
for d in doors: print(d)
