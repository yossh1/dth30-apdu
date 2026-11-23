import gzip, json, struct
ops = json.load(gzip.open('../phase2-20261122/replay_base.json.gz','rt'))
def dec(o):
    if o[0]=='O':
        b = bytes.fromhex(o[3])
        if len(b)==10:
            op, a, v = struct.unpack('<HII', b)
            return f'O pkt op={op:#06x} addr={a:#010x} val={v:#010x}'
        return f'O ep={o[2]} len={len(b)} head={b[:8].hex()}'
    if o[0]=='I': return f'I ep={o[2]} len={o[3]} expect={o[4]}'
    if o[0]=='Q': return f'Q out={o[2]:#x} req={o[3]} in={o[4]} final={o[5]} tmo={o[6]}'
    return str(o)[:100]
for lo,hi,label in [(5800,5860,'Func0x19 issue'),(5960,5999,'Func0x08 issue')]:
    print(f'===== {label} ops[{lo}:{hi}] =====')
    for k in range(lo,hi):
        print(k, dec(ops[k]))
