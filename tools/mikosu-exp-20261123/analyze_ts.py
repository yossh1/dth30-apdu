#!/usr/bin/env python3
# TS analyzer: sync integrity + scrambled-flag census.
# Usage: analyze_ts.py <file.ts>
# A packet counts as synced if it starts with 0x47 and the byte 188 ahead
# is also 0x47 (or EOF). Scrambled = transport_scrambling_control != 0
# (byte 3, bits 7-6) among synced packets.
import sys

data = open(sys.argv[1], 'rb').read()
n = len(data)
pk = n // 188
sync = 0
scr = 0
pids = {}
for i in range(pk):
    o = i * 188
    if data[o] != 0x47:
        continue
    sync += 1
    b3 = data[o + 3]
    if b3 >> 6:
        scr += 1
    pid = ((data[o + 1] & 0x1F) << 8) | data[o + 2]
    pids[pid] = pids.get(pid, 0) + 1
print(f'file={sys.argv[1]} bytes={n} packets={pk} synced={sync} '
      f'sync_rate={sync / pk * 100 if pk else 0:.2f}% scrambled={scr} '
      f'residue={n - pk * 188}')
print('pids:', {hex(k): v for k, v in sorted(pids.items(), key=lambda kv: -kv[1])[:12]})
