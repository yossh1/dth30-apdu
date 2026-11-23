#!/usr/bin/env python3
# Timed runner for mikosu `dth tune` measurements (N-060).
# Usage: run_tune.py <tag> <outfile.ts> [extra dth args...]
# - spawns: dth tune -c 27 -t 10 -o <outfile.ts> --stats -vv [extra...]
# - stderr lines are logged with monotonic elapsed + wall timestamps
# - output file size is polled every 10 ms; first-byte time and a 100 ms
#   growth series are recorded
import os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = '/srv/dth30-lab/mikosu/dth'
tag = sys.argv[1]
out_ts = sys.argv[2]
extra = sys.argv[3:]

env = dict(os.environ)
env['DTH_STATE_DIR'] = '/srv/dth30-lab/mikosu/state'
cmd = [BIN, 'tune', '-c', '27', '-t', '10', '-o', out_ts,
       '--stats', '-vv', '--state-dir', '/srv/dth30-lab/mikosu/state'] + extra
logf = open(os.path.join(HERE, f'tune_{tag}.log'), 'w', buffering=1)
growf = open(os.path.join(HERE, f'tune_{tag}_growth.csv'), 'w', buffering=1)

t0 = time.monotonic()
def wall():
    return time.strftime('%H:%M:%S')
def log(s):
    logf.write(f'{time.monotonic()-t0:9.3f} {wall()} {s}\n')

log('CMD ' + ' '.join(cmd))
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                     env=env, text=True, bufsize=1)

def reader(stream, name):
    for line in stream:
        log(f'{name}: {line.rstrip()}')
t_out = threading.Thread(target=reader, args=(p.stdout, 'OUT'), daemon=True)
t_err = threading.Thread(target=reader, args=(p.stderr, 'ERR'), daemon=True)
t_out.start(); t_err.start()

first_ts = None
last_sample = 0.0
size = 0
while p.poll() is None:
    try:
        size = os.path.getsize(out_ts)
    except OSError:
        size = 0
    now = time.monotonic() - t0
    if size > 0 and first_ts is None:
        first_ts = now
        log(f'FIRST_TS size={size}')
    if now - last_sample >= 0.1:
        growf.write(f'{now:.3f},{size}\n')
        last_sample = now
    time.sleep(0.01)
rc = p.wait()
try:
    size = os.path.getsize(out_ts)
except OSError:
    size = 0
log(f'EXIT rc={rc} final_size={size} first_ts={first_ts}')
t_out.join(timeout=2); t_err.join(timeout=2)
print(f'tag={tag} rc={rc} size={size} first_ts={first_ts} total={time.monotonic()-t0:.3f}')
