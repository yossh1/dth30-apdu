#!/usr/bin/env python3
# Scrambled-flag distribution: by PID and by file position (10 buckets).
import sys
from collections import Counter

data = open(sys.argv[1], 'rb').read()
pk = len(data) // 188
bypid = Counter()
bybucket = Counter()
first = []
for i in range(pk):
    o = i * 188
    if data[o] != 0x47:
        continue
    if data[o + 3] >> 6:
        pid = ((data[o + 1] & 0x1F) << 8) | data[o + 2]
        bypid[pid] += 1
        bybucket[i * 10 // pk] += 1
        if len(first) < 5:
            first.append(i)
print('scrambled by pid:', {hex(k): v for k, v in bypid.most_common()})
print('scrambled by decile:', dict(sorted(bybucket.items())))
print('first scrambled pkt idx:', first, 'of', pk)
