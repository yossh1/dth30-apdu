import gzip, json, struct, hashlib, copy
base = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
def ophash(ops):
    return hashlib.sha256(json.dumps(ops).encode()).hexdigest()[:16]
def diff_ops(a, b):
    assert len(a)==len(b)
    out=[]
    for k,(x,y) in enumerate(zip(a,b)):
        if x!=y:
            xb = bytes.fromhex(x[3]); yb = bytes.fromhex(y[3])
            assert len(xb)==len(yb) and x[:3]==y[:3], k
            ds=[i for i in range(len(xb)) if xb[i]!=yb[i]]
            out.append((k, ds))
    return out
# --- hook replay: ops[341] local 0x3F180 dword 0x801534d0 -> 0x8015359c ---
hook = copy.deepcopy(base)
b = bytearray(bytes.fromhex(hook[341][3]))
cur = struct.unpack('<I', b[0x3F180:0x3F184])[0]
assert cur == 0x801534d0, hex(cur)
assert struct.unpack('<I', b[0x3F184:0x3F188])[0] == 0x8015359c
b[0x3F180:0x3F184] = struct.pack('<I', 0x8015359c)
hook[341][3] = b.hex()
d = diff_ops(base, hook)
print('hook diff:', [(k, [hex(i) for i in ds]) for k,ds in d], 'total bytes', sum(len(ds) for _,ds in d))
with gzip.open('replay_hook.json.gz','wt') as f: json.dump(hook, f)
# --- cave replay: ops[338] payload [0x1E238, 0x1FBFC) := pattern dword j = 0xC0DE0000+j ---
cave = copy.deepcopy(base)
b = bytearray(bytes.fromhex(cave[338][3]))
assert b[0x1E238:0x1FBFC] == bytes(6596)
for j in range(6596//4):
    b[0x1E238+j*4:0x1E238+j*4+4] = struct.pack('<I', 0xC0DE0000+j)
cave[338][3] = b.hex()
d = diff_ops(base, cave)
print('cave diff:', [(k, len(ds), hex(ds[0]), hex(ds[-1])) for k,ds in d], 'total bytes', sum(len(ds) for _,ds in d))
with gzip.open('replay_cave.json.gz','wt') as f: json.dump(cave, f)
import os
for fn in ('replay_hook.json.gz','replay_cave.json.gz'):
    print(fn, hashlib.sha256(open(fn,'rb').read()).hexdigest(), os.path.getsize(fn))
