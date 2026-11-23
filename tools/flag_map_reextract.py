#!/usr/bin/env python3
"""Mechanical re-extraction of txc_read_return_code flag mapping.

Parses driver_txc_read_return_code.asm.txt (objdump of BufFsUSB.sys):
for each test against return-struct+0x9C, capture the tested value,
the following `push $VA` string address, and side effects (orl to sdev,
mov copies from struct+0xB0/+0xB4) until the next test.
Resolves the pushed VA to the ASCII string in BufFsUSB.sys via PE sections.
No relog, no execution of target code.
"""
import re, struct, pathlib

BASE = pathlib.Path.home()
ASM = BASE / "dth30-re/driver_txc_read_return_code.asm.txt"
SYS = BASE / "dth30-re/pkg/DTH30U2DRV_143/Drivers/BufFsUSB.sys"
OUT = BASE / "dth30-lab/bcas_flag_map_corrected.txt"

data = SYS.read_bytes()
e_lfanew = struct.unpack_from('<I', data, 0x3c)[0]
num = struct.unpack_from('<H', data, e_lfanew + 6)[0]
optsize = struct.unpack_from('<H', data, e_lfanew + 20)[0]
imagebase = struct.unpack_from('<I', data, e_lfanew + 24 + 28)[0]
sections = []
off = e_lfanew + 24 + optsize
for i in range(num):
    vs, va, rs, rp = struct.unpack_from('<IIII', data, off + i * 40 + 8)
    sections.append((va, max(vs, rs), rp))

def va_to_off(va_abs):
    rva = va_abs - imagebase
    for va, size, rp in sections:
        if va <= rva < va + size:
            return rp + (rva - va)
    return None

def read_string(va_abs):
    o = va_to_off(va_abs)
    if o is None:
        return "<unmapped>"
    end = data.index(b'\x00', o)
    return data[o:end].decode('ascii', 'replace')

lines = ASM.read_text(errors='replace').splitlines()
# state
ebx_val = None
entries = []
cur = None
test_re = re.compile(r'test[bwl]\s+\$(0x[0-9a-f]+),0x9c\(%edi\)')
test_ebx_re = re.compile(r'test\s+%ebx,0x9c\(%edi\)')
mov_ebx_re = re.compile(r'mov\s+\$(0x[0-9a-f]+),%ebx')
push_re = re.compile(r'push\s+\$(0x[0-9a-f]+)')
orl_re = re.compile(r'orl?\s+\$(0x[0-9a-f]+),0x([0-9a-f]+)\(%esi\)')
or_ebx_re = re.compile(r'or\s+%ebx,0x([0-9a-f]+)\(%esi\)')
copy_re = re.compile(r'mov\s+0x(b0|b4)\(%edi\),%eax')
store_re = re.compile(r'mov\s+%eax,0x(1f4|1f8)\(%esi\)')

site_re = re.compile(r'^\s+([0-9a-f]+):')
for ln in lines:
    m = mov_ebx_re.search(ln)
    if m:
        ebx_val = int(m.group(1), 16)
    m = test_re.search(ln)
    if m:
        sm = site_re.match(ln)
        cur = {'value': int(m.group(1), 16), 'push': None, 'orl': [], 'copies': [],
               'site': int(sm.group(1), 16) if sm else None}
        entries.append(cur)
        continue
    if test_ebx_re.search(ln):
        sm = site_re.match(ln)
        cur = {'value': ebx_val, 'push': None, 'orl': [], 'copies': [],
               'site': int(sm.group(1), 16) if sm else None}
        entries.append(cur)
        continue
    if cur is None:
        continue
    m = push_re.search(ln)
    if m and cur['push'] is None:
        cur['push'] = int(m.group(1), 16)
        cur['string'] = read_string(cur['push'])
        continue
    # Only the first orl/or after a test is that flag's side effect. The asm
    # continues past the flag blocks into a data-copy section (e.g. after the
    # second VIDEO_BLACK_OUT test at VA 0x3825A) whose orl $0x10/$0x20 to
    # sdev+0x90 are data-validity checks, not flag side effects; the old
    # unbounded "until next test" collection wrongly appended them to the
    # last entry, producing a spurious duplicate row with extra orls.
    m = orl_re.search(ln)
    if m and not cur['orl']:
        cur['orl'].append(f"orl ${m.group(1)} -> sdev+0x{m.group(2)}")
    m = or_ebx_re.search(ln)
    if m and not cur['orl']:
        cur['orl'].append(f"or %ebx (=0x{ebx_val:X}) -> sdev+0x{m.group(1)}")
    m = copy_re.search(ln)
    if m:
        cur['_pending_copy'] = m.group(1)
    m = store_re.search(ln)
    if m and cur.get('_pending_copy'):
        cur['copies'].append(f"struct+0x{cur['_pending_copy']} -> sdev+0x{m.group(1)}")
        cur['_pending_copy'] = None

rows = []
seen = {}
for e in entries:
    s = e.get('string', '')
    m = re.search(r'OUTPUT_READY_FLAG_(.+)$', s)
    name = m.group(1) if m else s
    key = (e['value'], e['push'], name)
    dup = key in seen
    if not dup:
        seen[key] = e.get('site')
    rows.append((e['value'], e['push'], name, '; '.join(e['orl']), '; '.join(e['copies']),
                 e.get('site'), dup, seen[key]))

with OUT.open('w') as f:
    f.write("# txc_read_return_code (BufFsUSB.sys VA 0x37F9C) flag mapping — mechanically re-extracted\n")
    f.write("# source asm: artifacts/driver_txc_read_return_code.asm.txt ; strings resolved via PE sections of pkg BufFsUSB.sys (imagebase 0x10000)\n")
    f.write("# columns: tested value at return-struct+0x9C | push VA | flag name (from pushed string) | sdev side-effect orl | struct->sdev copies\n")
    f.write("# note: VIDEO_BLACK_OUT (0x000002) is genuinely tested twice in the same function\n")
    f.write("# (test sites VA 0x37FB1 and VA 0x3825A, the second after the BCASCARD_CARDID block).\n")
    f.write("# The second row is annotated as a duplicate below and must not be double-counted;\n")
    f.write("# it is not a BCAS flag and does not affect the BCAS subset. Only the first orl after\n")
    f.write("# each test is that flag's side effect (see flag_map_reextract.py).\n")
    for v, p, name, orl, cp, site, dup, first_site in rows:
        note = ""
        if dup:
            note = (f"\t# duplicate: second test site VA 0x{site:05X} for the same flag "
                    f"(first at VA 0x{first_site:05X}); do not double-count")
        f.write(f"0x{v:06X}\t0x{p:05X}\t{name}\t{orl}\t{cp}{note}\n")
    f.write("\n# BCAS subset:\n")
    for v, p, name, orl, cp, site, dup, first_site in rows:
        if name.startswith('BCASCARD_'):
            f.write(f"0x{v:06X}\t{name}\t{orl}\t{cp}\n")
print(f"wrote {OUT} with {len(rows)} entries")
for r in rows:
    print(r)
