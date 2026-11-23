import struct
data = open('~/dth30-re/xcode2emb_embedded.bin','rb').read()
def w(off): return struct.unpack_from('<I', data, off)[0]
# maximal run of code-range pointers around 0xffa28
def isptr(x): return 0x80100000 <= x < 0x80220000
start=0xffa28
while start-4>=0 and isptr(w(start-4)): start-=4
end=0xffa28
while isptr(w(end)): end+=4
print(f"table run: fileoff 0x{start:06x}..0x{end:06x}  ({(end-start)//4} entries), KSEG0 VA base 0x{0x80100000+start:08x}")
for off in range(start,end,4):
    print(f"  idx {(off-start)//4:3d}  fileoff 0x{off:06x} -> 0x{w(off):08x}")
