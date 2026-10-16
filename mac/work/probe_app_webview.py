"""Read-only WebView network investigation; never print headers or credentials."""
import json
import time
from urllib.parse import urlsplit,parse_qs
import requests
import websocket

class WebView:
    def __init__(self,port=38743):
        pages=requests.get(f'http://127.0.0.1:{port}/json',timeout=5).json()
        pages=[p for p in pages if urlsplit(p.get('url','')).hostname=='life.douyin.com'
               and urlsplit(p.get('url','')).path=='/h5/alliance/merchant/plan/oriented/info']
        if len(pages)!=1:raise RuntimeError('Expected one exact life.douyin.com WebView')
        self.ws=websocket.create_connection(pages[0]['webSocketDebuggerUrl'],timeout=20,suppress_origin=True)
        self.counter=0;self.events=[]
    def call(self,method,**params):
        self.counter+=1;seq=self.counter
        self.ws.send(json.dumps({'id':seq,'method':method,'params':params}))
        while True:
            obj=json.loads(self.ws.recv())
            if obj.get('id')==seq:
                if 'error' in obj:raise RuntimeError(obj['error'].get('message','CDP error'))
                return obj.get('result',{})
            self.events.append(obj)
    def js(self,expression):
        r=self.call('Runtime.evaluate',expression=expression,awaitPromise=True,returnByValue=True)
        if 'exceptionDetails' in r:raise RuntimeError('WebView JavaScript failed')
        return r.get('result',{}).get('value')
    def close(self):self.ws.close()

if __name__=='__main__':
    w=WebView();seen={}
    try:
        w.call('Network.enable');w.call('Page.reload',ignoreCache=True)
        end=time.monotonic()+12;w.ws.settimeout(1)
        while time.monotonic()<end:
            try:w.events.append(json.loads(w.ws.recv()))
            except websocket.WebSocketTimeoutException:continue
        w.ws.settimeout(10)
        for e in list(w.events):
            if e.get('method')=='Network.requestWillBeSent':
                r=e['params']['request'];path=urlsplit(r['url']).path
                if '/life/' not in path:continue
                seen[e['params']['requestId']]=r
                print('REQUEST',path,r['method'],'QUERY_NAMES',list(parse_qs(urlsplit(r['url']).query)),'HEADER_NAMES',list(r.get('headers',{})))
            if e.get('method')=='Network.responseReceived' and e['params']['requestId'] in seen:
                req=e['params']['requestId'];path=urlsplit(seen[req]['url']).path
                try:
                    body=json.loads(w.call('Network.getResponseBody',requestId=req)['body'])
                    print('RESPONSE',path,body.get('status_code'),body.get('status_msg'),list(body))
                except Exception:print('BODY_UNAVAILABLE',path)
    finally:w.close()
