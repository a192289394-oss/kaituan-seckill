"""Coordinate-free App network lifecycle: no WebView, plan URL or page port."""
from native_account import NativeAccount
from native_http_api import NativeHttpApi


class NativeRuntime:
    def __init__(self,adb,serial,root,life,plan_id=None,timeout=35,autostart=False):
        if plan_id is not None and (not isinstance(plan_id,str) or not plan_id.isdigit()):raise ValueError('Exact plan id required')
        self.adb=adb;self.serial=serial;self.root=root;self.life=life
        self.autostart=autostart
        self.account=None;self.api=None
    def __enter__(self):
        try:
            self.account=NativeAccount(self.adb,self.serial,autostart=self.autostart)
            self.identity=self.account.switch(self.root,self.life)
            self.api=NativeHttpApi(self.account,self.root,self.identity['active']['account_id'])
            return self
        except Exception:
            self.close();raise
    def __exit__(self,*args):self.close()
    def close(self):
        if self.api:
            try:self.api.close()
            except Exception:pass
            self.api=None
        if self.account:self.account.close();self.account=None
