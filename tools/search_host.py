import os, re, pathlib
roots = [
  "~/dth30-re/pkg",
  "~/dth30-re/tve7125_x",
  "~/dth30-re/tve7222_x",
  "~/dth30-re/pcast115",
  "~/dth30-re/disasm",
]
terms = [r'B-?CAS', r'BCAS', r'\bCAS\b', r'ECM', r'EMM', r'ATR', r'smart\s*card', r'SmartCard', r'CardID', r'card.?id', r'7816', r'ISO.?7816', r'TPDU', r'APDU', r'WinSCard', r'SCard', r'PC/SC', r'descrambl', r'DRM', r'CA[_ ]', r'conditional.?access', r'BcasCard', r'IC.?Card', r'card.?reader']
pat = re.compile("|".join(terms), re.I)
out=[]
for root in roots:
  for dirpath,_,files in os.walk(root):
    for fn in files:
      p=os.path.join(dirpath,fn)
      try:
        data=open(p,'rb').read()
      except: continue
      # ascii + utf16le strings extraction quick: search raw bytes case-insensitive for ascii terms, and utf16
      hits=set()
      low=data.lower()
      for t in [b'bcas',b'b-cas',b'ecm',b'emm',b'atr',b'smartcard',b'smart card',b'7816',b'apdu',b'tpdu',b'scard',b'winscard',b'descrambl',b'cardid',b'card id',b'conditional']:
        if t in low: hits.add(t.decode())
      # utf16
      for t in [b'bcas',b'card']:
        u=b''.join(bytes([c,0]) for c in t)
        if u in low: hits.add('utf16:'+t.decode())
      if hits:
        out.append((p, sorted(hits), len(data)))
for p,h,s in sorted(out):
  print(f"{p}\t{s}\t{h}")
print(f"TOTAL files with any hit: {len(out)}")
