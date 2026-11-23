import socket, sys, time
def grab(ch, nbytes):
    s = socket.create_connection(('127.0.0.1', 40780)); s.sendall(f'{ch}\n'.encode())
    t0 = time.time(); buf = bytearray(); tf = None
    while len(buf) < nbytes:
        b = s.recv(1 << 20)
        if not b: break
        if tf is None: tf = time.time() - t0
        buf += b
    s.close()
    d = bytes(buf); off = next((o for o in range(188) if len(d) > o+20*188 and all(d[o+k*188]==0x47 for k in range(20))), None)
    tsid = set()
    if off is not None:
        for i in range(off, len(d) - 188, 188):
            if d[i]==0x47 and ((d[i+1]&0x1f)<<8|d[i+2])==0 and d[i+1]&0x40:
                p = d[i+5+d[i+4]:]; tsid.add(hex((p[3]<<8)|p[4]))
    print(f'ch{ch}: first byte {tf if tf is None else round(tf,2)}s, {len(d)} bytes in {time.time()-t0:.1f}s, TSID {tsid}')
for ch in map(int, sys.argv[1:]): grab(ch, 8_000_000)
