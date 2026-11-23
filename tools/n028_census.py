#!/usr/bin/env python3
# N-028 driver-side census (BufFsUSB.sys, objdump AT&T syntax):
#  - all $0x40000 immediate uses (or/test/and/mov)
#  - the SDEV open functions' cmd+0x7c flag tests (txc_open_ts_dev @0x1b9a8,
#    txc_open_secured_ts_dev @0x1f040)
#  - stores that could fill a slot image's param fields (offsets 0x58/0x5c/0x60
#    param-relative, 0x7c/0x80/0x84 slot-relative) with immediate values
import re

lines = open('~/dth30-re/disasm/BufFsUSB.asm').read().splitlines()

def va_of(line):
    m = re.match(r'\s+([0-9a-f]+):', line)
    return int(m.group(1), 16) if m else None

print("== [1] all $0x40000 immediate uses ==")
for ln in lines:
    if '$0x40000' in ln and '$0x400000' not in ln.replace('$0x40000,', '$0x40000 ,'):
        # exclude $0x400000 / $0x4000000 / $0x40000000 by requiring the next char after 40000 to be ','
        if re.search(r'\$0x40000,', ln):
            print(f"  {ln.strip()}")

print("\n== [2] flag-bit tests in txc_open_ts_dev range (0x1b9a8-0x1d320) on the cmd flags local -0x14(%ebp) ==")
for ln in lines:
    va = va_of(ln)
    if va is not None and 0x1b9a8 <= va < 0x1d320:
        if re.search(r'test.*-0x14\(%ebp\)', ln):
            print(f"  {ln.strip()}")

print("\n== [3] immediate stores to offsets 0x58/0x5c/0x60/0x7c/0x80/0x84 (any base) ==")
for ln in lines:
    if re.search(r'movl\s+\$0x[0-9a-f]+,0x(58|5c|60|7c|80|84)\(%', ln):
        print(f"  {ln.strip()}")

print("\n== [4] slot-size 0x23c0 references ==")
for ln in lines:
    if '0x23c0' in ln:
        print(f"  {ln.strip()}")
