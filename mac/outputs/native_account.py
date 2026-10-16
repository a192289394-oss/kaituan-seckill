"""Root BlueStacks account adapter; no UI selectors, clicks or business writes.

Requires a local-only Frida server already installed on the emulator.
The production worker opens this adapter only after the configured loopback
device is connected.
"""
import json
import fcntl
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time
import tempfile
from adb_android import AdbAndroid

PACKAGE='com.bytedance.ls.merchant'


class NativeAccountUnavailable(RuntimeError):pass


def pick_account(rows,life_id):
    matches=[r for r in rows if str((r.get('detail') or {}).get('life_account_id'))==life_id]
    if len(matches)!=1:raise NativeAccountUnavailable('当前授权目录未唯一定位商家账号')
    return matches[0]


def verify_identity(identity,root,life,group):
    active=identity.get('active') or {}
    if (active.get('root')!=root or active.get('life')!=life or identity.get('group')!=group):
        raise NativeAccountUnavailable('App 实际公司或门店身份尚未核验通过')
    return identity


class NativeAccount:
    def __init__(self,adb,serial,server_port=27042,autostart=False):
        if not re.fullmatch(r'127\.0\.0\.1:\d{1,5}',serial):raise ValueError('Explicit loopback emulator required')
        if not isinstance(server_port,int) or not 1<=server_port<=65535:raise ValueError('Invalid server port')
        self.device=AdbAndroid(adb,serial);self.session=None;self.forward=None;self.catalog_api=None;self.owner_lock=None
        key=hashlib.sha256((serial+'|'+PACKAGE).encode()).hexdigest()[:16]
        path=Path(tempfile.gettempdir())/f'kaituan-native-{os.getuid()}-{key}.lock'
        self.owner_lock=os.fdopen(os.open(path,os.O_CREAT|os.O_RDWR,0o600),'a+')
        try:fcntl.flock(self.owner_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner_lock.close();self.owner_lock=None
            raise NativeAccountUnavailable('App 原生执行端正在处理其他任务，稍后自动恢复')
        try:
            import frida
            from native_bootstrap import ensure_installed_runtime
            if server_port!=27042 and autostart:raise ValueError('Autostart requires the installed loopback port')
            self.pid=ensure_installed_runtime(self.device,frida.__version__,autostart)
            r=subprocess.run([adb,'-s',serial,'forward','tcp:0','tcp:'+str(server_port)],capture_output=True,text=True,timeout=10,check=True)
            self.forward=int(r.stdout.strip())
            remote=frida.get_device_manager().add_remote_device(f'127.0.0.1:{self.forward}')
            self.session=remote.attach(self.pid)
            # One Java bridge isolate owns both identity and HTTP. Multiple
            # independent Java scripts can invalidate each other's lifecycle.
            source=Path(__file__).with_name('native_account_agent.js').read_text()+'\n'+Path(__file__).with_name('native_http_agent.js').read_text()
            self.agent=self.session.create_script(source)
            self.agent.load();self.identity()
        except Exception as exc:
            self.close()
            if isinstance(exc,NativeAccountUnavailable):raise
            raise NativeAccountUnavailable('App 内部账号服务暂不可连接：'+str(exc)[:160]) from exc

    def identity(self):return self.agent.exports_sync.identity()
    def debug_web(self):return self.agent.exports_sync.debugweb()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def close(self):
        if self.catalog_api:self.catalog_api.close();self.catalog_api=None
        if self.session:
            try:self.session.detach()
            except Exception:pass
            self.session=None
        if self.forward:
            try:subprocess.run([self.device.adb,'-s',self.device.serial,'forward','--remove','tcp:'+str(self.forward)],capture_output=True,timeout=5)
            except Exception:pass
            self.forward=None
        if self.owner_lock:
            self.owner_lock.close();self.owner_lock=None

    def accounts(self,group=None):
        path='poiAccountList/' if group else 'groupAccountList/'
        from native_http_api import NativeHttpApi
        active=self.identity()['active']
        if self.catalog_api and (self.catalog_api.expected_root!=active['root'] or self.catalog_api.expected_account!=active['account_id']):
            self.catalog_api.close();self.catalog_api=None
        if not self.catalog_api:self.catalog_api=NativeHttpApi(self,active['root'],active['account_id'])
        rows=[];seen=set()
        for page in range(1,51):
            params={'page_index':page,'page_size':100,'detail':'true'}
            if group:params['groupId']=group
            else:params['support_bd_switch']='true'
            _,data=self.catalog_api.read('/life/gate/v1/account/'+path,params=params)
            body=data.get('data') or {};batch=body.get('list');p=body.get('pagination') or {}
            if not isinstance(batch,list):raise NativeAccountUnavailable('App 账号目录格式不完整')
            for a in batch:
                aid=str(a.get('account_id'))
                if not aid.isdigit() or aid in seen:raise NativeAccountUnavailable('App 账号分页重复或缺少身份')
                seen.add(aid);rows.append(a)
            if isinstance(p.get('page_count'),int) and page>=p['page_count']:return rows
            if isinstance(p.get('total_count'),int) and len(rows)>=p['total_count']:return rows
            if not batch:raise NativeAccountUnavailable('App 账号目录分页未明确结束')
        raise NativeAccountUnavailable('App 账号目录超过分页上限')

    def switch(self,root,life):
        if not all(isinstance(x,str) and x.isdigit() for x in (root,life)):raise ValueError('Exact root and merchant IDs required')
        parent=pick_account(self.accounts(),root);group=str(parent['account_id'])
        # Resolve the subordinate before switching. Absence is not permission
        # to use a similarly named hotel or silently stay at the company root.
        target=parent if life==root else pick_account(self.accounts(group),life)
        if str((target.get('detail') or {}).get('root_life_account_id'))!=root:
            raise NativeAccountUnavailable('App 门店与公司关系不符')
        current=self.identity()
        try:return verify_identity(current,root,life,group)
        except NativeAccountUnavailable:pass
        active=current.get('active') or {}
        if (current.get('group')!=group or active.get('root')!=root
                or life==root and active.get('life')!=root):
            # The official switch function needs a resumed Activity. A live
            # process can be in the background; normal launcher activation is
            # coordinate-free and never approves a business action.
            if self.device.app_current().get('package')!=PACKAGE:
                self.device.app_start(PACKAGE)
            self.agent.exports_sync.switchgroup(json.dumps(parent,ensure_ascii=False))
            self._settle(root,root,group)
        if life!=root:
            result=self.agent.exports_sync.switchaccount(str(target['account_id']),root)
            if result.get('ok') is not True:raise NativeAccountUnavailable('App 内部门店切换未成功')
        return self._settle(root,life,group)

    def _settle(self,root,life,group):
        deadline=time.monotonic()+30;matching=0
        while time.monotonic()<deadline:
            try:
                value=verify_identity(self.identity(),root,life,group);matching+=1
                if matching>=2:return value
            except NativeAccountUnavailable:matching=0
            time.sleep(1)
        raise NativeAccountUnavailable('App 切换后身份未稳定；需回读，不代表业务提交失败')
