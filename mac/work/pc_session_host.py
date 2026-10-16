"""Hold the project profile lock while an acceptance session uses headless Chrome."""
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time
import urllib.request

os.umask(0o077)
root = Path(__file__).resolve().parents[1]
state = root / 'work/pc-acceptance'
state.mkdir(exist_ok=True)
profile = root / 'work/pc-profile'
lock = open(str(profile) + '.automation.lock', 'a+')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
proc = subprocess.Popen([
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    f'--user-data-dir={profile}', f'--remote-debugging-port={port}',
    '--remote-debugging-address=127.0.0.1', '--headless=new',
    '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
    '--window-size=1440,1000', '--remote-allow-origins=*',
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stop(*args):
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    for _ in range(60):
        if proc.poll() is not None:
            raise RuntimeError('Chrome exited before ready')
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1).close()
            break
        except Exception:
            time.sleep(.3)
    else:
        raise RuntimeError('Chrome CDP startup timeout')
    (state / 'session.json').write_text(json.dumps({'host_pid': os.getpid(), 'chrome_pid': proc.pid, 'port': port}))
    proc.wait()
finally:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    (state / 'session.json').unlink(missing_ok=True)
    lock.close()
