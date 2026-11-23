import struct
def rd(fn): return open(fn,'rb').read()
runs = ['A1','P','B','A2']
f1 = {t: rd(f'hw34_{t}_f1low.bin') for t in runs}
def diff(a, b):
    return [i for i in range(len(a)) if a[i]!=b[i]]
print('f1low A1 vs A2: diff bytes', len(diff(f1['A1'], f1['A2'])))
d = diff(f1['A1'], f1['P'])
print('f1low A1 vs P : diff bytes', len(d), 'range', hex(min(d)), '-', hex(max(d)), '(cave span 0x1e238-0x1fbfc)')
d = diff(f1['A1'], f1['B'])
print('f1low A1 vs B : diff bytes', len(d), [hex(x) for x in d], '(f1low covers [0,0x40000) only; table is in tblwin)')
for t in runs:
    w = rd(f'hw34_{t}_tblwin.bin')
    e4 = struct.unpack('<I', w[0x80:0x84])[0]
    print(f'tblwin {t}: entry[4] = {e4:#010x}')
    wp = rd(f'hw34_{t}_tblwin_postB.bin')
    print(f'         postB entry[4] = {struct.unpack("<I", wp[0x80:0x84])[0]:#010x}, window diff pre/post = {len(diff(w, wp))}')
    c = rd(f'hw34_{t}_cave_postB.bin')
    nz = sum(1 for x in c if x != 0)
    print(f'         cave postB: nonzero bytes {nz}/6596, first dword {c[:4].hex()}, last dword {c[-4:].hex()}')
