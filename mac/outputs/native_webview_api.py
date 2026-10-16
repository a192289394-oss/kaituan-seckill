"""App-owned native request bridge; independent of webpage framework/bundle IDs.

The fetch/getLocalAccountInfo bridge contracts were verified against the app's
official bridge library and live 10.6.5 runtime. This module is read-only.
"""
import json
import time
from urllib.parse import urlsplit,parse_qs
import requests

READ_ROUTES = {
    '/life/gate/v1/account/groupAccountList/': 'GET',
    '/life/gate/v1/account/poiAccountList/': 'GET',
    '/life/alliance/v1/merchant/task/product/search/': 'GET',
    '/life/alliance/v1/merchant/task/detail/get/': 'GET',
    '/life/alliance/v2/merchant/task/detail/get/': 'GET',
    '/life/marketing/v1/minus_activity/list': 'POST',
    '/life/marketing/v1/minus_activity/info': 'GET',
    '/life/marketing/v1/marketing/account/product/list': 'GET',
    '/life/marketing/v1/minus_activity/pre_check': 'POST',
    '/life/hermes/marketing_tool/live/douyin_id/batch_input': 'POST',
    '/life/alliance/v1/merchant/task/marketing/activity/get/': 'POST',
    '/life/alliance/v1/merchant/partner/permission/check/': 'GET',
}
PLAN_PATHS={
    '/h5/alliance/merchant/plan/oriented/info',
    '/h5/alliance/unite_plan/target_plan_detail',
}


class AppReadUnavailable(RuntimeError):
    """A read failure is not a business submission failure."""


class SubmissionUncertain(RuntimeError):
    """The dispatch gate is consumed: fresh readback only, never resend."""


def wire_value(value):
    # Native JS serialization must never round an exact Python int64 ID.
    if isinstance(value,int) and not isinstance(value,bool) and abs(value)>2**53-1:return str(value)
    if isinstance(value,dict):return {k:wire_value(v) for k,v in value.items()}
    if isinstance(value,list):return [wire_value(v) for v in value]
    return value


def select_page(pages,plan_id):
    if not isinstance(plan_id,str) or not plan_id.isdigit():
        raise ValueError('Exact plan id required')
    matches=[]
    for page in pages:
        url=urlsplit(page.get('url',''));query=parse_qs(url.query)
        if (page.get('type')=='page' and url.scheme=='https' and url.hostname=='life.douyin.com'
                and url.path in PLAN_PATHS
                and query.get('task_id')==[plan_id]):
            matches.append(page)
    # Android provides actual WebView visibility, independent of list order.
    # An old hidden plan page may remain alive after the official redirect.
    visible=[]
    for page in matches:
        try:description=json.loads(page.get('description','{}'))
        except (TypeError,ValueError):description={}
        if description.get('visible') is True:visible.append(page)
    if visible:matches=visible
    if len(matches)!=1:raise AppReadUnavailable('App 网络上下文尚未唯一就绪')
    return matches[0]


def verify_scope(identity,expected_root,expected_account):
    if not isinstance(identity,dict) or (identity.get('root')!=expected_root
            or identity.get('account_id')!=expected_account):
        raise AppReadUnavailable('App 实际商家身份已变化，停止本次读取')


class NativeWebViewApi:
    def __init__(self,port,plan_id,expected_root,expected_account,timeout=20):
        if not isinstance(port,int) or not 1<=port<=65535:raise ValueError('Invalid local port')
        if not all(isinstance(x,str) and x.isdigit() for x in (expected_root,expected_account)):
            raise ValueError('Explicit exact native account/root scope required')
        self.expected_root=expected_root;self.expected_account=expected_account
        import websocket
        pages=requests.get(f'http://127.0.0.1:{port}/json',timeout=5).json()
        page=select_page(pages,plan_id)
        socket=page['webSocketDebuggerUrl'];parsed=urlsplit(socket)
        if parsed.scheme!='ws' or parsed.hostname!='127.0.0.1' or parsed.port!=port:
            raise AppReadUnavailable('拒绝非本机 App 调试地址')
        self.ws=websocket.create_connection(socket,timeout=timeout,suppress_origin=True)
        self.timeout=timeout;self.seq=0
        try:
            valid=self.js('typeof window.ToutiaoJSBridge?.call==="function"')
            if valid is not True:raise AppReadUnavailable('App 网页版本未通过网络桥核验')
            self.assert_scope()
        except Exception:
            self.close();raise

    def close(self):self.ws.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

    def assert_scope(self):
        raw=self.js('new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error("native_identity_timeout")),10000);'
            'window.ToutiaoJSBridge.call("getLocalAccountInfo",{},r=>{clearTimeout(t);'
            'const a=r.data?.accountInfo||r.data?.data?.accountInfo;'
            'resolve(JSON.stringify({account_id:a?.account_id,root:a?.detail?.root_life_account_id}));})})')
        try:identity=json.loads(raw)
        except (ValueError,TypeError) as exc:raise AppReadUnavailable('App 未返回有效商家身份') from exc
        verify_scope(identity,self.expected_root,self.expected_account)

    def js(self,expression):
        self.seq+=1;seq=self.seq;deadline=time.monotonic()+self.timeout
        self.ws.send(json.dumps({'id':seq,'method':'Runtime.evaluate','params':{
            'expression':expression,'returnByValue':True,'awaitPromise':True}}))
        while time.monotonic()<deadline:
            self.ws.settimeout(max(.1,deadline-time.monotonic()))
            r=json.loads(self.ws.recv())
            if r.get('id')!=seq:continue
            if 'error' in r or 'exceptionDetails' in r.get('result',{}):
                raise AppReadUnavailable('App 内部网络桥暂不可读')
            return r.get('result',{}).get('result',{}).get('value')
        raise AppReadUnavailable('App 网络读取超时')

    def read(self,path,params=None,body=None):
        method=READ_ROUTES.get(path)
        if method is None:raise ValueError('Endpoint is not an audited read-only route')
        if (method=='POST') != (body is not None):raise ValueError('Read method/body mismatch')
        self.assert_scope()
        payload={'url':'https://life.douyin.com'+path,'method':method,'params':params or {}}
        if body is not None:payload['data']=body
        raw=self._fetch_raw(payload)
        self.assert_scope()
        return raw,self._parse(raw)

    def _fetch_raw(self,payload):
        payload=dict(payload,header={'Content-Type':'application/json','Cache-Control':'no-cache'})
        if '/life/marketing/v1/minus_activity/' in payload['url']:
            payload['header']['Discount-Type']='20'
        # _raw is the bridge's original response text. Never serialise its
        # parsed JS response: numeric 19-digit IDs have already lost precision.
        raw=self.js('new Promise((resolve,reject)=>{const t=setTimeout(()=>reject(Error("native_fetch_timeout")),15000);'
            'window.ToutiaoJSBridge.call("fetch",'+json.dumps(wire_value(payload),allow_nan=False)+',r=>{clearTimeout(t);'
            'resolve(typeof r._raw==="string"?r._raw:null);})})')
        return raw

    @staticmethod
    def _parse(raw):
        if not isinstance(raw,str):raise AppReadUnavailable('App 未返回可精确解析的接口原文')
        try:data=json.loads(raw)
        except (ValueError,TypeError) as exc:raise AppReadUnavailable('App 接口原文不是有效 JSON') from exc
        if not isinstance(data,dict):raise AppReadUnavailable('App 接口结构未核验')
        if data.get('status_code')!=0:
            raise AppReadUnavailable('App 接口读取被拒绝，状态码 '+str(data.get('status_code')))
        return data

    def submit_activity_once(self,body,permit):
        # This is intentionally NOT a general write API or retryable read route.
        from native_commit import ActivityPermit
        if not isinstance(permit,ActivityPermit):raise ValueError('Durable activity permit required')
        self.assert_scope()
        permit.consume(self.expected_root,body)
        try:
            raw=self._fetch_raw({'url':'https://life.douyin.com/life/marketing/v1/minus_activity/save',
                                 'method':'POST','data':body})
            self.assert_scope()
            return raw,self._parse(raw)
        except Exception as exc:
            raise SubmissionUncertain('原生提交已进入结果复核，不会重复发送') from exc

    def submit_plan_once(self,body,permit):
        from native_plan_journal import PlanPermit
        if not isinstance(permit,PlanPermit):raise ValueError('Durable plan permit required')
        self.assert_scope();permit.consume(self.expected_root,body)
        try:
            raw=self._fetch_raw({'url':'https://life.douyin.com/life/alliance/v1/merchant/broker/operation/confirm/',
                                 'method':'POST','data':body})
            self.assert_scope();return raw,self._parse(raw)
        except Exception as exc:raise SubmissionUncertain('计划确认已进入结果复核，不会重复发送') from exc
