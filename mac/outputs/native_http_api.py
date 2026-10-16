"""App-owned synchronous HTTP transport; never exports auth or opens a page."""
import json
import hashlib
import re
from urllib.parse import urlsplit
from native_webview_api import NativeWebViewApi,AppReadUnavailable,wire_value,verify_scope


class DispatchReceiptUnavailable(RuntimeError):
    """A write permit is already consumed; response logging cannot permit retry."""


def safe_status_message(value):
    if not isinstance(value,str):return ''
    # Only a short platform status message is eligible. Secret markers, URLs,
    # opaque credentials and embedded diagnostic objects are never retained.
    if (re.search(r'token|cookie|authorization|bearer|header|secret|password|credential|session|csrf|ticket|app[_ -]?key|签名|凭证|密钥',value,re.I)
            or re.search(r'https?://|[A-Za-z0-9+/=_-]{32,}|[{}]',value)):
        return '响应消息含敏感内容，已省略。'
    return re.sub(r'\s+',' ',value).strip()[:160]


def dispatch_summary(payload,result=None,exc=None):
    body=json.dumps(wire_value(payload.get('data',{})),sort_keys=True,ensure_ascii=False,allow_nan=False)
    result=result if isinstance(result,dict) else {}
    raw=result.get('raw');data={}
    if isinstance(raw,str):
        try:
            parsed=json.loads(raw)
            if isinstance(parsed,dict):data=parsed
        except (ValueError,TypeError):pass
    http=result.get('http');code=data.get('status_code')
    return {'phase':'transport_exception' if exc is not None else 'response_received',
        'http':http if type(http) is int else None,
        'status_code':code if type(code) is int else None,
        'status_msg':safe_status_message(data.get('status_msg',data.get('message',''))),
        'request_body_sha':hashlib.sha256(body.encode()).hexdigest(),
        'response_sha':hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw,str) else None,
        'error_class':type(exc).__name__ if exc is not None else None}


class NativeHttpApi(NativeWebViewApi):
    def __init__(self,account,expected_root,expected_account):
        self.account=account;self.expected_root=expected_root;self.expected_account=expected_account
        self.script=account.agent
        self.assert_scope()

    def close(self):
        # The account owner, not individual scoped clients, owns this script.
        self.script=None

    def assert_scope(self):
        current=self.account.identity()['active']
        verify_scope({'root':current.get('root'),'account_id':current.get('account_id')},self.expected_root,self.expected_account)

    def _dispatch_receipt(self,payload,result=None,exc=None):
        callback=getattr(self,'dispatch_receipt_callback',None)
        if callback is None:return
        try:callback(dispatch_summary(payload,result,exc))
        except Exception:
            # The native journal already consumed the only dispatch right. A
            # receipt failure becomes read-only uncertainty, never a second send.
            raise DispatchReceiptUnavailable('响应记录不可用；提交许可已消费，只允许复核。') from None

    def _fetch_raw(self,payload):
        url=urlsplit(payload['url'])
        if url.scheme!='https' or url.hostname!='life.douyin.com' or url.query or url.fragment:
            raise ValueError('Exact audited API URL required')
        packet=dict(payload,header={'Content-Type':'application/json','Cache-Control':'no-cache','referer':'https://life.douyin.com/'})
        if '/life/marketing/v1/minus_activity/' in url.path:packet['header']['Discount-Type']='20'
        encoded=json.dumps(wire_value(packet),allow_nan=False)
        writes={'/life/marketing/v1/minus_activity/save','/life/alliance/v1/merchant/broker/operation/confirm/'}
        try:
            result=(self.script.exports_sync.dispatch(encoded) if url.path in writes
                    else self.script.exports_sync.read(encoded))
        except Exception as exc:
            if url.path in writes:self._dispatch_receipt(payload,exc=exc)
            raise AppReadUnavailable('App 同步请求暂不可用') from exc
        if url.path in writes:self._dispatch_receipt(payload,result=result)
        if result.get('http')!=200:raise AppReadUnavailable('App 同步请求未正常返回')
        return result.get('raw')
