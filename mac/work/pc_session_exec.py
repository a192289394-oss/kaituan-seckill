"""Run a local inspection snippet in the locked headless acceptance session."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
s = json.loads((root / 'work/pc-acceptance/session.json').read_text())
env = dict(os.environ, BU_NAME='kaituan-acceptance', BU_CDP_URL=f"http://127.0.0.1:{s['port']}", BH_RECORD='0')
script = Path(sys.argv[1]).read_text() if len(sys.argv) > 1 else sys.stdin.read()
compile(script, '<pc-session>', 'exec')
r = subprocess.run([str(Path.home() / '.local/bin/browser-use')], input=script, text=True,
                   capture_output=True, env=env, timeout=180)
print(r.stdout, end='')
if r.returncode:
    for line in r.stderr.splitlines():
        if re.match(r'^\w+(Error|Exception):', line):
            print(re.sub(r'https?://\S+', '[url]', line)[:250])
sys.exit(r.returncode)
