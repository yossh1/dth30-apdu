#!/usr/bin/env python3
# n010b_lock_scan.py — enumerate all call sites of the spinlock helpers
#   0x40510 = AcquireLock(obj, &lock, &old_irql)  -> HAL KfAcquireSpinLock (IAT *0x50010)
#   0x4052C = ReleaseLock(obj, &lock, &old_irql)  -> HAL KfReleaseSpinLock (IAT *0x50008)
# in BufFsUSB.asm, classify the lock target from nearby lea/mov displacements,
# and group by enclosing function (heuristic: previous int3-pad boundary).
import re, sys
from collections import defaultdict

ASM = '~/dth30-re/disasm/BufFsUSB.asm'
insns = []  # (addr:int, text:str, raw:str)
pat = re.compile(r'^\s+([0-9a-f]+):\t((?:[0-9a-f]{2} )+|[0-9a-f ]*)\t(.*)$')
for line in open(ASM, errors='replace'):
    m = pat.match(line.rstrip('\n'))
    if m:
        insns.append((int(m.group(1), 16), m.group(3).strip(), line.rstrip('\n')))
addr2idx = {a: i for i, (a, t, r) in enumerate(insns)}

# function starts: instruction following a run of >=2 int3, or 'mov %edi,%edi' + push %ebp pattern
starts = []
prev_int3_run = 0
for i, (a, t, r) in enumerate(insns):
    if t == 'int3':
        prev_int3_run += 1
        continue
    if prev_int3_run >= 2:
        starts.append(a)
    prev_int3_run = 0
starts = sorted(set(starts))

def func_of(addr):
    import bisect
    j = bisect.bisect_right(starts, addr)
    return starts[j - 1] if j else None

lea_re = re.compile(r'lea\s+0x([0-9a-f]+)\(%\w+\),%\w+')
disp_re = re.compile(r'0x([0-9a-f]+)\(%')

def lock_hint(idx):
    """look back up to 30 insns for lea displacements (candidate lock/object offsets)"""
    hints = []
    for k in range(max(0, idx - 30), idx):
        t = insns[k][1]
        m = lea_re.search(t)
        if m:
            hints.append((insns[k][0], int(m.group(1), 16)))
    return hints

sites = []
for i, (a, t, r) in enumerate(insns):
    if t.startswith('call   0x40510'):
        kind = 'ACQ'
    elif t.startswith('call   0x4052c'):
        kind = 'REL'
    else:
        continue
    hints = lock_hint(i)
    disps = sorted(set(d for _, d in hints))
    tags = []
    if 0x16e3bac in disps: tags.append('ARENA_QUEUE_LOCK')
    if 0x118 in disps: tags.append('LISTHEAD_118')
    if any(d in (0xd0848, 0xd084c, 0xd0850, 0xd0854) for d in disps): tags.append('POOL_HEAD')
    sites.append((a, kind, func_of(a), disps, tags))

print(f'total sites: {len(sites)}  ACQ={sum(1 for s in sites if s[1]=="ACQ")}  REL={sum(1 for s in sites if s[1]=="REL")}')
byfunc = defaultdict(list)
for s in sites:
    byfunc[s[2]].append(s)
print(f'enclosing functions: {len(byfunc)}')
print()
print('== sites with notable lock targets ==')
for a, kind, f, disps, tags in sites:
    if tags:
        print(f'  site 0x{a:05x} {kind} func 0x{f:05x} tags={tags} lea_disps={[hex(d) for d in disps]}')
print()
print('== all sites grouped by function ==')
for f in sorted(byfunc):
    ss = byfunc[f]
    kinds = ''.join('A' if s[1] == 'ACQ' else 'R' for s in ss)
    alldisps = sorted(set(d for s in ss for d in s[3]))
    print(f'  func 0x{f:05x}: {len(ss)} sites [{kinds}] lea_disps={[hex(d) for d in alldisps][:14]}')
