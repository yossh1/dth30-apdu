import sys

for p in sys.argv[1:]:
    d = open(p, "rb").read()
    n = len(d) // 188
    sync = 0
    scr = []
    for i in range(n):
        o = i * 188
        if d[o] == 0x47:
            sync += 1
        if d[o + 3] & 0xC0:
            scr.append(i)
    print(
        p.split("/")[-1],
        "bytes", len(d),
        "packets", n,
        "sync", sync,
        "scrambled", len(scr),
        "last_scrambled_idx", (scr[-1] if scr else -1),
        "scrambled_after_5000", sum(1 for i in scr if i >= 5000),
    )
