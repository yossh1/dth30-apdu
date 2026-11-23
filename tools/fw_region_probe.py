import struct, re
data=open("~/dth30-re/xcode2emb_embedded.bin",'rb').read()
print("size",hex(len(data)))
terms=[b'CableCard',b'CableCARD',b'BCAS',b'B-CAS',b'APDU',b'ECM',b'EMM',b'DesKey',b'smart',b'Smart',b'7816',b'ATR',b'POD',b' descram',b'Descram',b'CA ',b'cipher',b'Cipher',b'AES',b'DES']
for t in terms:
    idxs=[]; i=0
    while True:
        j=data.find(t,i)
        if j<0: break
        idxs.append(j); i=j+1
    if idxs: print(t, [hex(x) for x in idxs[:20]], "count", len(idxs))
# dump all printable strings in 0xE0000-end with offsets
strs=[]
for m in re.finditer(rb'[\x20-\x7e]{6,}', data):
    if m.start()>=0xE0000:
        strs.append((m.start(), m.group().decode()))
print("strings >=0xE0000:", len(strs))
for o,s in strs: print(hex(o), s)
