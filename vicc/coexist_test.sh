#!/bin/sh
# Coexistence test: Mirakurun GR27 stream running while a PC/SC client
# does ATR + APDU exchanges through dth-vicc. Log: coexist.log beside
# this script; TS kept as gr27-vicc.ts.
cd /srv/dth30-lab/vicc || exit 1
{
    echo "=== coexist test start: $(date -u +%FT%TZ) ==="
    rm -f gr27-vicc.ts
    curl -s http://127.0.0.1:40772/api/channels/GR/27/stream -o gr27-vicc.ts &
    CURLPID=$!
    sleep 20
    echo "--- pcsc_check during stream ---"
    python3 pcsc_check.py 2>&1
    echo "pcsc_exit=$?"
    sleep 15
    kill $CURLPID 2>/dev/null
    wait $CURLPID 2>/dev/null
    ls -la gr27-vicc.ts
    python3 /srv/dth30-lab/tscheck.py gr27-vicc.ts
    echo "=== coexist test end: $(date -u +%FT%TZ) ==="
} > coexist.log 2>&1
