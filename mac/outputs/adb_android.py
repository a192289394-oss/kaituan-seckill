"""ADB-native Android control. Uses system XML dumps and input, no u2 agent."""
from dataclasses import dataclass
import re
import shlex
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


@dataclass
class ShellResult:
    output: str
    exit_code: int


class AdbReadTimeout(RuntimeError):
    """The ADB transport timed out; command completion is unconfirmed."""


class AdbAndroid:
    native_adb = True
    def __init__(self, adb, serial):
        self.adb,self.serial=adb,serial
        self._xml='';self._at=0.0

    def shell(self, command, timeout=20):
        if not isinstance(command,(list,tuple)):
            raise ValueError('ADB shell requires an argument list')
        # ADB shell reparses its arguments on Android. Quote the entire command.
        try:
            r=subprocess.run([self.adb,'-s',self.serial,'shell',shlex.join([str(x) for x in command])],
                             capture_output=True,text=True,timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise AdbReadTimeout('ADB 连接读取超时，等待模拟器恢复') from exc
        return ShellResult(r.stdout,r.returncode)

    def _checked(self, args, timeout=20):
        r=self.shell(args,timeout)
        if r.exit_code:raise RuntimeError('ADB 设备命令失败，等待连接恢复')
        return r.output

    def _invalidate(self):self._xml='';self._at=0.0

    def window_size(self):
        text=self._checked(['dumpsys','window','displays'])
        sizes=[(int(w),int(h)) for w,h in re.findall(r'\bcur=(\d+)x(\d+)',text)]
        sizes=[(w,h) for w,h in sizes if w>1 and h>1]
        if not sizes:raise RuntimeError('ADB 未读到实际 Android 窗口尺寸')
        return max(sizes,key=lambda s:s[0]*s[1])

    @property
    def info(self):
        power=self._checked(['dumpsys','power'])
        w,h=self.window_size()
        return {'screenOn':bool(re.search(r'mWakefulness=Awake|Display Power: state=ON',power)),
                'displayWidth':w,'displayHeight':h}

    def screen_on(self):self._checked(['input','keyevent','KEYCODE_WAKEUP']);self._invalidate()

    def dump_hierarchy(self):
        if self._xml and time.monotonic()-self._at<.25:return self._xml
        path='/data/local/tmp/kaituan-ui-'+uuid.uuid4().hex+'.xml'
        try:
            self._checked(['uiautomator','dump',path],timeout=15)
            xml=self._checked(['cat',path],timeout=5)
            ET.fromstring(xml)
            self._xml=xml;self._at=time.monotonic()
            return xml
        finally:
            self.shell(['rm','-f',path],timeout=5)

    def click(self,x,y):
        w,h=self.window_size()
        if not 0<=x<w or not 0<=y<h:raise RuntimeError('ADB 点击目标超出当前窗口')
        self._checked(['input','tap',int(x),int(y)]);self._invalidate()

    def swipe(self,x1,y1,x2,y2,duration=.5):
        w,h=self.window_size()
        if not all(0<=x<w and 0<=y<h for x,y in ((x1,y1),(x2,y2))):
            raise RuntimeError('ADB 滑动超出当前窗口')
        self._checked(['input','swipe',int(x1),int(y1),int(x2),int(y2),max(1,int(duration*1000))]);self._invalidate()

    def press(self,key):
        keys={'back':'KEYCODE_BACK','home':'KEYCODE_HOME','enter':'KEYCODE_ENTER'}
        self._checked(['input','keyevent',keys[key]]);self._invalidate()

    def app_stop(self,package):
        self._checked(['am','force-stop',package]);self._invalidate()

    def app_current(self):
        text=self._checked(['dumpsys','activity','activities'])
        match=re.search(r'(?:mResumedActivity|topResumedActivity).*?\s([\w.]+)/([\w.$]+)',text)
        if not match:raise RuntimeError('ADB 无法识别前台应用')
        return {'package':match[1],'activity':match[2]}

    def app_start(self,package,stop=False):
        if stop:self.app_stop(package)
        component=self._checked(['cmd','package','resolve-activity','--brief',package]).strip().splitlines()[-1]
        if '/' not in component:raise RuntimeError('ADB 未找到应用启动入口')
        self._checked(['am','start','-W','-n',component]);self._invalidate()

    def __call__(self,**selector):return AdbSelector(self,selector)


class AdbSelector:
    FIELDS={'text':'text','resourceId':'resource-id','description':'content-desc','className':'class'}
    def __init__(self,device,selector):
        if not selector or set(selector)-set(self.FIELDS):raise ValueError('Unsupported ADB selector')
        self.device,self.selector=device,selector

    def _matches(self):
        return [n for n in ET.fromstring(self.device.dump_hierarchy()).iter('node')
                if all(n.get(self.FIELDS[k])==v for k,v in self.selector.items())]

    @property
    def exists(self):return bool(self._matches())

    def wait(self,timeout=3):
        end=time.monotonic()+timeout
        while True:
            if self.exists:return True
            if time.monotonic()>=end:return False
            time.sleep(.3)

    def click(self,timeout=3):
        end=time.monotonic()+timeout
        while True:
            nodes=self._matches()
            if len(nodes)>1:raise RuntimeError('ADB 控件匹配不唯一，未点击')
            if nodes:
                n=nodes[0]
                if n.get('enabled')=='false':raise RuntimeError('ADB 目标控件不可用')
                bounds=list(map(int,re.findall(r'\d+',n.get('bounds',''))))
                if len(bounds)!=4:raise RuntimeError('ADB 控件范围不可读')
                x1,y1,x2,y2=bounds;w,h=self.device.window_size()
                if not 0<=x1<x2<=w or not 0<=y1<y2<=h:raise RuntimeError('ADB 控件不在当前窗口')
                self.device.click((x1+x2)//2,(y1+y2)//2);return
            if time.monotonic()>=end:raise RuntimeError('ADB 等待目标控件超时')
            time.sleep(.3)
