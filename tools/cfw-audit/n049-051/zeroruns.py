data=open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
print('image len', hex(len(data)))
# find all zero runs >= 256 bytes
runs=[]
i=0
n=len(data)
while i<n:
    if data[i]==0:
        j=i
        while j<n and data[j]==0: j+=1
        if j-i>=256: runs.append((i,j-i))
        i=j
    else: i+=1
for off,l in sorted(runs,key=lambda r:-r[1])[:20]:
    print(f'file {off:#x} len {l} ({l:#x})  VA kseg1 {0xa0100000+off:#x} kseg0 {0x80100000+off:#x} end {off+l:#x}')
