#!/usr/bin/env python3
"""Extended host-side string search (verifier return item, high-2).

Adds roots/files not covered by search_host.py:
 tve7125/ tve7222/ (non-_x installer trees, raw incl. .cab payloads as bytes),
 mtvhd/ research/ wincap/ replay/, and unexpanded installer files
 dth30u2drv_143.exe / pcast115.exe / tve7125.cab / tve7222.cab / archive.lzh / pcast115.lzh
 (raw byte search only -- nothing is executed, extracted or unpacked;
  research/ .git internals are excluded, only working-tree text/binary files are read).
All terms are searched in ASCII, UTF-16LE and UTF-16BE extracted strings.
Precise string extraction for 7222 PCMRRec4.dll / TVECapSvc.exe is emitted separately.
"""
import os, re, pathlib

BASE = pathlib.Path.home() / "workspace/dth30-re"
OUT = pathlib.Path.home() / "dth30-lab/host_string_hits_extended.txt"
OUT7222 = pathlib.Path.home() / "dth30-lab/strings_7222_precise.txt"

DIR_ROOTS = [
    "pkg", "tve7125_x", "tve7222_x", "pcast115", "disasm",   # previously covered (re-run for completeness)
    "tve7125", "tve7222", "mtvhd", "research", "wincap", "replay",  # NEW
]
SINGLE_FILES = ["dth30u2drv_143.exe", "pcast115.exe", "pcast115.lzh",
                "tve7125.cab", "tve7222.cab", "archive.lzh"]  # NEW, raw bytes only

TERMS = [r'APDU', r'TPDU', r'7816', r'ISO.?7816', r'SCard', r'WinSCard', r'PC/SC',
         r'\bATR\b', r'B-?CAS', r'BCAS', r'SmartCard', r'Smart Card',
         r'SetSmartCardSN', r'GetCardID', r'CardID', r'conditional access']
PAT = re.compile('|'.join(TERMS), re.I)

def strings_ascii(data, minlen=4):
    for m in re.finditer(rb'[\x20-\x7e]{%d,}' % minlen, data):
        yield m.start(), m.group().decode('ascii', 'replace')

def strings_utf16(data, byteorder):
    # sequences of printable char + 00 (LE) or 00 + char (BE)
    if byteorder == 'le':
        pat = rb'(?:[\x20-\x7e]\x00){4,}'
        for m in re.finditer(pat, data):
            yield m.start(), m.group().decode('utf-16le', 'replace')
    else:
        pat = rb'(?:\x00[\x20-\x7e]){4,}'
        for m in re.finditer(pat, data):
            yield m.start(), m.group().decode('utf-16be', 'replace')

def iter_files():
    for root in DIR_ROOTS:
        r = BASE / root
        for dirpath, dirnames, files in os.walk(r):
            if '.git' in pathlib.Path(dirpath).parts:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d != '.git']
            for fn in sorted(files):
                yield os.path.join(dirpath, fn), root
    for fn in SINGLE_FILES:
        yield str(BASE / fn), '(single-file)'

counts = {}
hits = []
total = 0
for path, root in iter_files():
    total += 1
    counts[root] = counts.get(root, 0) + 1
    try:
        data = open(path, 'rb').read()
    except Exception:
        continue
    found = []
    for enc, gen in (('ascii', strings_ascii(data)), ('utf16le', strings_utf16(data, 'le')), ('utf16be', strings_utf16(data, 'be'))):
        for off, s in gen:
            if PAT.search(s):
                # ATR as bare 3 letters inside longer words is noise: require token boundary already in PAT (\bATR\b)
                found.append((enc, off, s.strip()))
    if found:
        hits.append((path, found))

with OUT.open('w') as f:
    f.write("# Extended search — roots and file counts\n")
    for r in DIR_ROOTS:
        f.write(f"root {r}: {counts.get(r,0)} files\n")
    for fn in SINGLE_FILES:
        f.write(f"single {fn}: 1 file (raw bytes, unexpanded)\n")
    f.write(f"TOTAL files scanned: {total}\n")
    f.write(f"TOTAL files with hits: {len(hits)}\n")
    f.write("# terms: APDU TPDU 7816 ISO7816 SCard WinSCard PC/SC ATR(word) B-CAS BCAS SmartCard 'Smart Card' SetSmartCardSN GetCardID CardID 'conditional access'\n")
    f.write("# encodings: ascii, utf16le, utf16be (all terms, all encodings)\n\n")
    for path, found in sorted(hits):
        f.write(f"== {path}\n")
        seen = set()
        for enc, off, s in found:
            key = (enc, s)
            if key in seen:
                continue
            seen.add(key)
            f.write(f"  [{enc} @0x{off:x}] {s[:300]}\n")

# precise extraction: 7222 PCMRRec4 / TVECapSvc, only card-related strings, all encodings
targets = []
for dirpath, _, files in os.walk(BASE / "tve7222_x"):
    for fn in files:
        if fn in ("PCMRRec4.dll", "TVECapSvc.exe", "CLCapEngine.dll"):
            targets.append(os.path.join(dirpath, fn))
with OUT7222.open('w') as f:
    f.write("# Precise card-related string extraction — 7222 variants (ascii+utf16le+utf16be)\n")
    for path in sorted(targets):
        data = open(path, 'rb').read()
        f.write(f"\n== {path} ({len(data)} bytes)\n")
        seen = set()
        for enc, gen in (('ascii', strings_ascii(data)), ('utf16le', strings_utf16(data, 'le')), ('utf16be', strings_utf16(data, 'be'))):
            for off, s in gen:
                if PAT.search(s) and s not in seen:
                    seen.add(s)
                    f.write(f"  [{enc} @0x{off:x}] {s.strip()[:300]}\n")
print(f"scanned {total} files, {len(hits)} with hits -> {OUT}")
print(f"7222 precise targets: {len(targets)} -> {OUT7222}")
for r in DIR_ROOTS:
    print(r, counts.get(r, 0))
