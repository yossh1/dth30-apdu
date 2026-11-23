import struct, re, sys
def sections(path):
    data=open(path,'rb').read()
    pe=struct.unpack_from('<I', data, 0x3c)[0]
    nsec=struct.unpack_from('<H', data, pe+6)[0]
    optsize=struct.unpack_from('<H', data, pe+20)[0]
    imagebase=struct.unpack_from('<I', data, pe+24+28)[0]
    secs=[]
    off=pe+24+optsize
    for i in range(nsec):
        name=data[off+i*40:off+i*40+8].rstrip(b'\x00').decode()
        vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', data, off+i*40+8)
        secs.append((name, vaddr, vsize, raddr, rsize))
    return imagebase, secs, data
def foff_to_va(imagebase, secs, foff):
    for name,va,vs,ra,rs in secs:
        if ra <= foff < ra+rs:
            return imagebase+va+(foff-ra)
    return None
def find_utf16(data, s):
    pat=s.encode('utf-16le')
    idxs=[]; i=0
    while True:
        j=data.find(pat,i)
        if j<0: break
        idxs.append(j); i=j+1
    return idxs

path=sys.argv[1]; asm=sys.argv[2]; terms=sys.argv[3:]
ib,secs,data=sections(path)
print("imagebase",hex(ib),"secs",secs)
asmtext=open(asm, errors='ignore').read()
for term in terms:
    for foff in find_utf16(data, term):
        va=foff_to_va(ib,secs,foff)
        print(f"\n== '{term}' fileoff 0x{foff:x} VA 0x{va:x}")
        # xref search
        pat=re.compile(r'0x%x\b'%va)
        for m in pat.finditer(asmtext):
            s=max(0,m.start()-200); print("XREF:", asmtext[s:m.end()+80].replace('\n',' | ')[-280:])
        # also ascii version
    # ascii
    patb=term.encode()
    i=0
    while True:
        j=data.find(patb,i)
        if j<0: break
        va=foff_to_va(ib,secs,j)
        if va:
            hits=[m for m in re.finditer(r'0x%x\b'%va, asmtext)]
            if hits: print(f" ascii '{term}' 0x{j:x} VA 0x{va:x} xrefs {len(hits)}")
        i=j+1
