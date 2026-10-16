"""Android transport and viewport adaptation for USB devices and BlueStacks."""
import os
import re
import subprocess
import time

_last_launch = 0.0
# Launch the bundle binary directly. `open -a` delivers a launch event and
# drops `--instance` when BlueStacks is already running.
PLAYER = '/Applications/BlueStacks.app/Contents/MacOS/BlueStacks'


def emulator(cfg):
    return (cfg.get('android_device') or {}).get('backend', 'usb') == 'bluestacks'


def endpoint(cfg):
    device = cfg.get('android_device') or {}
    value = device.get('adb_endpoint') or cfg.get('serial')
    match = re.fullmatch(r'127\.0\.0\.1:(\d{1,5})', value or '')
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise ValueError('BlueStacks ADB 必须指定本机 127.0.0.1:端口')
    if cfg.get('serial') != value:
        raise ValueError('BlueStacks serial 与 adb_endpoint 不一致，未连接其他设备')
    return value


def probe(cfg, adb, allow_launch=True):
    """Bounded reconnect of the configured device only; never reset the ADB server."""
    global _last_launch
    serial = endpoint(cfg) if emulator(cfg) else cfg['serial']
    def state():
        return subprocess.run([adb, '-s', serial, 'get-state'],capture_output=True,text=True,timeout=5)
    result = state()
    if result.returncode == 0 and result.stdout.strip() == 'device':
        return result
    if emulator(cfg):
        connected = subprocess.run([adb, 'connect', serial],capture_output=True,text=True,timeout=5)
        result = state()
        if (result.returncode or result.stdout.strip() != 'device') and allow_launch:
            options = cfg.get('android_device') or {}
            instance = options.get('instance', '')
            if (options.get('autostart') and re.fullmatch(r'[A-Za-z0-9_-]+', instance)
                    and os.path.isfile(PLAYER) and time.monotonic()-_last_launch >= 60):
                _last_launch = time.monotonic()
                subprocess.Popen([PLAYER, '--instance', instance],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True, close_fds=True)
                # The ordinary queue/health backoff waits for Android boot; no blocking boot loop.
        return result
    return result


def unavailable_message(cfg, result):
    if emulator(cfg):
        return 'BlueStacks 暂未连接，等待模拟器启动或 ADB 恢复（'+endpoint(cfg)+'）'
    return ('手机尚未允许 USB 调试，请在手机上确认授权' if 'unauthorized' in result.stderr.lower()
            else '手机连接已断开，请检查 USB 数据线和手机连接状态')


def swipe_reference(d, x1, y1, x2, y2, duration, width=1080, height=2400):
    """Scale legacy navigation gestures into the actual Android viewport."""
    w, h = d.window_size()
    if not isinstance(w,int) or not isinstance(h,int) or w <= 0 or h <= 0:
        raise RuntimeError('无法读取 Android 窗口尺寸')
    def point(x,y):
        return min(w-1,max(0,round(x*w/width))),min(h-1,max(0,round(y*h/height)))
    a,b=point(x1,y1);c,e=point(x2,y2)
    d.swipe(a,b,c,e,duration)
