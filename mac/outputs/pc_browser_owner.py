"""Recover only a recorded, orphaned project headless Chrome; never kill a user's browser."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def owner_file(profile):
    return Path(profile) / 'automation-owner.json'


def alive(pid):
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def record(profile, chrome_pid):
    path = owner_file(profile)
    path.write_text(json.dumps({'owner_pid':os.getpid(), 'chrome_pid':chrome_pid,
                                'profile':str(Path(profile).resolve()), 'started_at':time.time()}))
    path.chmod(0o600)


def recover(profile):
    """Caller must hold the profile automation lock exclusively."""
    path = owner_file(profile)
    if not path.exists():
        return
    data = json.loads(path.read_text())
    if data.get('profile') != str(Path(profile).resolve()):
        raise RuntimeError('PC 浏览器所有权记录不一致，需要人工检查。')
    pid = data.get('chrome_pid')
    if not alive(pid):
        path.unlink()
        return
    if alive(data.get('owner_pid')):
        raise RuntimeError('PC 浏览器记录的拥有者仍在运行，拒绝接管。')
    args = subprocess.check_output(['ps','-p',str(pid),'-o','args='],text=True).strip()
    import shlex
    tokens = shlex.split(args)
    if (f'--user-data-dir={Path(profile).resolve()}' not in tokens
            or '--headless=new' not in tokens or not any(t.startswith('--remote-debugging-port=') for t in tokens)):
        raise RuntimeError('孤立浏览器身份未核对，拒绝终止。')
    os.kill(pid, signal.SIGTERM)
    for _ in range(40):
        if not alive(pid):
            path.unlink(missing_ok=True)
            return
        time.sleep(.2)
    raise RuntimeError('项目孤立浏览器尚未退出；没有重复启动或发布。')
