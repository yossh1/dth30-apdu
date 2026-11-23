#!/usr/bin/env python3
# N-027 census: writers of ctx+0x2408 (== obj+0x1000, obj = ctx+0x1408)
# Scope: literal immediate offsets in firmware.asm (direct +0x2408, obj-view +0x1000),
# immediate 0x2408 address computations, and direct jal callers of the identified
# writer chain (determiner 0xa01cc7c4 -> copy 0xa01c8f7c -> apply 0xa01db154).
import re

lines = open('~/dth30-re/disasm/firmware.asm').read().splitlines()

def va_of(line):
    m = re.match(r'0x([0-9a-f]+):', line)
    return int(m.group(1), 16) if m else None

# crude function split (same method as n023_census.py)
funcs = []
cur = None
prev_jr = True
for ln in lines:
    va = va_of(ln)
    if va is None:
        continue
    if prev_jr and re.search(r'addiu \$sp, \$sp, -', ln):
        cur = (va, [])
        funcs.append(cur)
        prev_jr = False
    if cur is not None:
        cur[1].append(ln)
    if 'jr $ra' in ln:
        prev_jr = True

def func_of(va):
    best = None
    for start, fl in funcs:
        if start <= va:
            best = start
        else:
            break
    return best

print(f"total crude functions: {len(funcs)}")

print("\n== [1] ALL accesses with literal offset 0x2408 (loads and stores) ==")
n_store = 0
for ln in lines:
    if '0x2408(' in ln:
        va = va_of(ln)
        is_store = re.search(r'\b(sw|sh|sb)\b', ln) is not None
        if is_store:
            n_store += 1
        print(f"  func @{func_of(va):#x}  {ln.strip()}  {'<== STORE' if is_store else ''}")
print(f"  --> literal stores to +0x2408: {n_store}")

print("\n== [2] ALL stores with literal offset 0x1000 (obj-view candidates) ==")
for ln in lines:
    if re.search(r'\b(sw|sh|sb) \$\w+, 0x1000\(\$\w+\)', ln):
        va = va_of(ln)
        print(f"  func @{func_of(va):#x}  {ln.strip()}")

print("\n== [3] immediate 0x2408 used in non-load/store instructions ==")
for ln in lines:
    if '0x2408' in ln and '0x2408(' not in ln:
        print(f"  {ln.strip()}")

print("\n== [4] addiu address computations with 0x2408 / 0x2400 ==")
for ln in lines:
    if re.search(r'addiu \$\w+, \$\w+, (0x2408|0x2400)\b', ln):
        print(f"  {ln.strip()}")
print("  (none printed above = no such addiu)")

print("\n== [5] direct jal callers of the writer chain ==")
for target in (0xa01cc7c4, 0xa01c8f7c, 0xa01db154):
    print(f" -- jal {target:#x}:")
    for ln in lines:
        if f'jal {target:#x}' in ln:
            va = va_of(ln)
            print(f"    func @{func_of(va):#x}  {ln.strip()}")

print("\n== [6] stores inside determiner 0xa01cc7c4 (crude range to next prologue) ==")
started = False
for start, fl in funcs:
    if start == 0xa01cc7c4:
        for ln in fl:
            if re.search(r'\b(sw|sh|sb) \$\w+, (0x1000|0x1008)\(\$\w+\)', ln):
                print(f"  {ln.strip()}")
        started = True
        break
if not started:
    print("  (crude splitter did not isolate 0xa01cc7c4)")

print("\n== [7] loads of +0x2408 inside task 0xa013e3e0 / start 0xa019c1bc ranges ==")
for lo, hi, name in ((0xa013e3e0, 0xa0142000, 'task region'),
                     (0xa019c1bc, 0xa019c754, 'start routine')):
    for ln in lines:
        va = va_of(ln)
        if va is not None and lo <= va < hi and '0x2408(' in ln:
            print(f"  [{name}] {ln.strip()}")
