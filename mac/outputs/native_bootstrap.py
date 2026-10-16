"""Bounded recovery of the installed native helper, never roots or resets Android."""
import re
import time
from adb_android import AdbReadTimeout

SERVER='/data/local/tmp/kaituan-frida-server'
PACKAGE='com.bytedance.ls.merchant'


def ensure_installed_runtime(device,version,allow_start=False):
    if not re.fullmatch(r'\d+\.\d+\.\d+',version):raise ValueError('Exact runtime version required')
    if 'uid=0(root)' not in device.shell(['su','-c','id']).output:
        raise RuntimeError('BlueStacks root 尚未就绪；不会自动修改镜像')
    actual=device.shell(['su','-c',SERVER+' --version'],timeout=10)
    if actual.exit_code or actual.output.strip()!=version:
        raise RuntimeError('已安装原生服务版本不一致，需要重新核验；不会自动替换二进制')
    pid=device.shell(['su','-c','pidof kaituan-frida-server']).output.strip()
    if not pid:
        if not allow_start:raise RuntimeError('原生连接服务未启动')
        try:
            result=device.shell(['su','-c',SERVER+' -D -l 127.0.0.1:27042'],timeout=10)
        except AdbReadTimeout:
            # The confirmed installed binary may already have daemonized while
            # ADB still holds stdout. A timeout is not evidence it failed to start.
            # Only this transport exception permits independent process readback;
            # nonzero exits and other failures never widen recovery rights.
            result=None
        if result is not None and result.exit_code:
            raise RuntimeError('原生连接服务未启动；不终止其他监听进程')
        pid=device.shell(['su','-c','pidof kaituan-frida-server']).output.strip()
        if not pid:raise RuntimeError('原生连接服务启动后未读到进程')
    if len(pid.split())!=1 or not pid.isdigit():
        raise RuntimeError('原生连接服务进程身份未唯一确认')
    # NativeAccount still requires forward + Frida attach + identity to succeed;
    # a PID alone never marks the runtime healthy or a business task successful.
    result=device.shell(['pidof',PACKAGE]).output.strip().split()
    if not result and allow_start:
        device.app_start(PACKAGE)
        for _ in range(10):
            result=device.shell(['pidof',PACKAGE]).output.strip().split()
            if result:break
            time.sleep(.5)
    if not result:raise RuntimeError('来客 App 尚未启动')
    if len(result)!=1 or not result[0].isdigit():raise RuntimeError('来客进程身份未唯一确认')
    return int(result[0])
